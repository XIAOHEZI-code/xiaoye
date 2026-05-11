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
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session

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
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    content = await file.read()
    from src.ingestion.dedup import DedupChecker
    file_hash = DedupChecker.compute_hash(content)

    # 防重检查
    existing = DedupChecker.check_existing(file_hash)
    if existing:
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
    background_tasks.add_task(run_ingestion_pipeline_task, doc_id, real_path, file.filename)

    return {
        "status": "success",
        "documentId": doc_id,
        "filename": file.filename,
        "message": "上传成功，正在后台索引（约 1-3 分钟后可检索）",
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