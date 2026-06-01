"""
PDF 上传路由 — 含自动索引管线触发

上传成功后自动在后台执行：
  1. marker_single  → Markdown + 图片
  2. split_markdown → ChunkDocument 列表
  3. process_figures → 图片 ChunkDocument（无 VLM，节省调用）
  4. es_indexer.index_chunk_documents → 向量化 + ES 批量写入
  5. 更新 DB status: pending → ready
"""
import hashlib
import uuid
import os
import shutil
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.logger import setup_logger

logger = setup_logger("xiaoye.upload")

from src.core.config import settings
from src.db.session import get_db
from src.models.document import DocumentMetadata

router = APIRouter()

STORAGE_DIR = "data/storage"
MARKER_OUT_DIR = "data/marker_output"
os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(MARKER_OUT_DIR, exist_ok=True)


def get_db_session():
    from src.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_ingestion_pipeline_task(doc_id: str, pdf_path: str, filename: str):
    """
    后台索引管线（委托给 IngestionPipeline 编排器）。
    """
    from src.ingestion.pipeline import IngestionPipeline
    
    pipeline = IngestionPipeline(doc_id=doc_id, pdf_path=pdf_path, filename=filename)
    pipeline.run()


@router.post("/upload_pdf")
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db_session),
):
    """
    PDF 安全上传与防重机制：
    1. 计算文件 SHA-256 hash
    2. 查库：若已存在，直接返回已有 document_id（秒传）
    3. 若不存在：保存文件 → 写入 DB(pending) → 后台触发索引管线
    """
    if not file.filename or not file.filename.endswith(".pdf"):
        logger.warning(f"Rejected invalid file upload: {file.filename}")
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    content = await file.read()
    logger.info(f"Received upload request for file: {file.filename} (Size: {len(content)} bytes)")
    from src.ingestion.dedup import DedupChecker
    file_hash = DedupChecker.compute_hash(content)

    # 防重检查
    existing = DedupChecker.check_existing(file_hash)
    if existing:
        logger.info(f"Fast resume hit for {file.filename} -> doc_id: {existing['id']}")
        return {
            "status": "fast_resume",
            "message": "File already exists",
            "documentId": existing["id"],
            "filename": existing["filename"],
        }

    # 保存文件
    doc_id = str(uuid.uuid4())
    real_path = os.path.join(STORAGE_DIR, f"{doc_id}.pdf")
    with open(real_path, "wb") as f:
        f.write(content)

    # 写入数据库（pending）
    db_doc = DocumentMetadata(
        id=doc_id,
        filename=file.filename,
        hash=file_hash,
        real_path=real_path,
        status="pending",
    )
    db.add(db_doc)
    db.commit()

    # 触发后台索引管线
    logger.info(f"Triggering ingestion pipeline for {doc_id} ({file.filename})")
    background_tasks.add_task(run_ingestion_pipeline_task, doc_id, real_path, file.filename)

    return {
        "status": "success",
        "documentId": doc_id,
        "filename": file.filename,
        "message": "上传成功，正在后台索引（约 1-3 分钟后可检索）",
    }


class LocalUploadRequest(BaseModel):
    filepath: str

@router.post("/upload_local_pdf")
async def upload_local_pdf(
    req: LocalUploadRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_session),
):
    """
    Electron 专供极速上传通道：
    直接通过绝对路径读取本地文件，规避 HTTP form-data 封包解包的内存消耗，打破大小限制。
    """
    if not os.path.exists(req.filepath) or not req.filepath.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="文件不存在或不是 PDF")

    filename = os.path.basename(req.filepath)
    logger.info(f"Received local file upload request: {req.filepath}")

    from src.ingestion.dedup import DedupChecker
    
    # 读文件以计算 Hash
    with open(req.filepath, "rb") as f:
        content = f.read()
    file_hash = DedupChecker.compute_hash(content)

    # 防重检查
    existing = DedupChecker.check_existing(file_hash)
    if existing:
        logger.info(f"Fast resume hit for {filename} -> doc_id: {existing['id']}")
        return {
            "status": "fast_resume",
            "message": "File already exists",
            "documentId": existing["id"],
            "filename": existing["filename"],
        }

    # 保存文件（直接硬拷贝，速度极快）
    doc_id = str(uuid.uuid4())
    real_path = os.path.join(STORAGE_DIR, f"{doc_id}.pdf")
    shutil.copy(req.filepath, real_path)

    # 写入数据库（pending）
    db_doc = DocumentMetadata(
        id=doc_id,
        filename=filename,
        hash=file_hash,
        real_path=real_path,
        status="pending",
    )
    db.add(db_doc)
    db.commit()

    # 触发后台索引管线
    logger.info(f"Triggering ingestion pipeline for {doc_id} ({filename})")
    background_tasks.add_task(run_ingestion_pipeline_task, doc_id, real_path, filename)

    return {
        "status": "success",
        "documentId": doc_id,
        "filename": filename,
        "message": "极速入库成功，正在后台索引（约 1-3 分钟后可检索）",
    }


@router.get("/documents")
async def list_documents(db: Session = Depends(get_db_session)):
    """返回用户所有已上传的 PDF 列表（含状态）"""
    docs = db.query(DocumentMetadata).order_by(DocumentMetadata.created_at.desc()).all()
    return {
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ],
        "total": len(docs),
    }


@router.get("/documents/{doc_id}/pdf")
async def serve_pdf(doc_id: str, db: Session = Depends(get_db_session)):
    """
    按文档 ID 返回 PDF 原始文件。
    前端用于在 PdfViewer 中加载知识库中的 PDF（包括检索命中的文献）。
    """
    from fastapi.responses import FileResponse

    doc = db.query(DocumentMetadata).filter(DocumentMetadata.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    if not os.path.exists(doc.real_path):
        raise HTTPException(status_code=404, detail="PDF 文件不存在于磁盘")

    return FileResponse(
        path=doc.real_path,
        media_type="application/pdf",
        filename=doc.filename,
    )

@router.get("/images")
async def serve_local_image(path: str):
    """
    提供本地绝对路径图片的访问，用于展示 Marker 提取出来的图表
    """
    from fastapi.responses import FileResponse
    import os
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, db: Session = Depends(get_db_session)):
    """
    级联删除知识库文档 — 清理四层数据：
      1. PostgreSQL document_metadata 记录
      2. Elasticsearch 中该 doc_id 的所有向量 chunk
      3. Neo4j 中该 doc_id 注入的所有关系
      4. 磁盘文件（PDF 存储 + Marker 解析产物）
    """
    # 0. 查找文档记录
    doc = db.query(DocumentMetadata).filter(DocumentMetadata.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    filename = doc.filename
    real_path = doc.real_path
    cleanup_report = {"doc_id": doc_id, "filename": filename, "cleaned": []}

    # 1. 删除 Elasticsearch chunks
    try:
        from elasticsearch import Elasticsearch
        es = Elasticsearch(settings.ELASTICSEARCH_URL)
        result = es.delete_by_query(
            index="metallurgy_chunks",
            body={"query": {"term": {"doc_id": doc_id}}},
            ignore=[404],
        )
        deleted_count = result.get("deleted", 0)
        cleanup_report["cleaned"].append(f"ES: {deleted_count} chunks")
        logger.info(f"[Delete] ES: deleted {deleted_count} chunks for {doc_id}")
    except Exception as e:
        logger.warning(f"[Delete] ES cleanup failed (non-fatal): {e}")
        cleanup_report["cleaned"].append(f"ES: failed ({e})")

    # 2. 删除 Neo4j 关系和孤立节点
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        with driver.session() as session:
            # 删除该文档注入的所有关系
            result = session.run(
                "MATCH ()-[r {doc_id: $doc_id}]->() DELETE r RETURN count(r) AS cnt",
                doc_id=doc_id,
            )
            rel_count = result.single()["cnt"]
            # 清理孤立节点（没有任何关系的节点）
            session.run("MATCH (n) WHERE NOT (n)--() DELETE n")
        driver.close()
        cleanup_report["cleaned"].append(f"Neo4j: {rel_count} relations")
        logger.info(f"[Delete] Neo4j: deleted {rel_count} relations for {doc_id}")
    except Exception as e:
        logger.warning(f"[Delete] Neo4j cleanup failed (non-fatal): {e}")
        cleanup_report["cleaned"].append(f"Neo4j: failed ({e})")

    # 3. 删除磁盘文件
    try:
        # PDF 存储文件
        if real_path and os.path.exists(real_path):
            os.remove(real_path)
            cleanup_report["cleaned"].append(f"PDF: {real_path}")
        # Marker 解析产物目录
        import shutil
        marker_dir = os.path.join(MARKER_OUT_DIR, os.path.splitext(filename)[0])
        if os.path.isdir(marker_dir):
            shutil.rmtree(marker_dir)
            cleanup_report["cleaned"].append(f"Marker: {marker_dir}")
    except Exception as e:
        logger.warning(f"[Delete] Disk cleanup failed (non-fatal): {e}")
        cleanup_report["cleaned"].append(f"Disk: failed ({e})")

    # 4. 删除 PostgreSQL 记录（最后执行，确保前面的清理已完成）
    db.delete(doc)
    db.commit()
    cleanup_report["cleaned"].append("PostgreSQL: record deleted")
    logger.info(f"[Delete] ✅ Document {doc_id} ({filename}) fully cleaned")

    return {"status": "deleted", **cleanup_report}