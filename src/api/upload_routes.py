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


async def run_ingestion_pipeline(doc_id: str, pdf_path: str, filename: str):
    """
    后台索引管线：PDF → Chunks → Embeddings → Elasticsearch。
    完成后将 DocumentMetadata.status 更新为 'ready'。
    """
    from src.db.session import SessionLocal
    from src.pipeline.pdf_parser import (
        extract_pdf_with_marker,
        split_markdown_into_chunk_documents,
        process_figures,
        enhance_chunks_with_figures,
    )
    from src.pipeline.es_indexer import ElasticsearchIndexer

    import os
    # 确保代理已清除（避免影响 Qwen embedding API）
    for key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
        os.environ.pop(key, None)
    os.environ["OPENAI_API_KEY"] = settings.QWEN_API_KEY
    os.environ["OPENAI_API_BASE"] = settings.QWEN_BASE_URL

    print(f"[Ingestion] Starting pipeline for doc_id={doc_id}, file={filename}")

    db = SessionLocal()
    try:
        # ── Step 1: Marker PDF → Markdown ──────────────────────────────────
        try:
            md_text, image_paths, out_metadata = extract_pdf_with_marker(
                filepath=pdf_path,
                out_dir=MARKER_OUT_DIR,
            )
            print(f"[Ingestion] Marker done: {len(md_text)} chars, {len(image_paths)} images")
        except Exception as e:
            print(f"[Ingestion] Marker failed: {e}. Falling back to text extraction.")
            # 降级：直接用 PyMuPDF 提取纯文本
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(pdf_path)
                md_text = "\n\n".join(page.get_text() for page in doc)
                image_paths = []
                out_metadata = {}
                print(f"[Ingestion] PyMuPDF fallback: {len(md_text)} chars")
            except Exception as e2:
                print(f"[Ingestion] All extraction failed: {e2}")
                _update_status(db, doc_id, "failed")
                return

        if not md_text.strip():
            print(f"[Ingestion] No text extracted from {filename}")
            _update_status(db, doc_id, "failed")
            return

        # ── Step 2: 文本 Chunking ────────────────────────────────────────
        text_chunks = split_markdown_into_chunk_documents(
            md_text=md_text,
            out_metadata=out_metadata,
            doc_id=doc_id,
            source_pdf_id=filename,
        )
        print(f"[Ingestion] Text chunks: {len(text_chunks)}")

        # ── Step 3: 图片 Chunks（仅图注，不调 VLM 节省费用）──────────────
        figure_chunks = []
        if image_paths:
            try:
                figure_chunks = process_figures(
                    md_text=md_text,
                    image_paths=image_paths,
                    doc_id=doc_id,
                    source_pdf_id=filename,
                    analyze_with_vlm=False,  # 节省 API 调用
                )
                print(f"[Ingestion] Figure chunks: {len(figure_chunks)}")
            except Exception as e:
                print(f"[Ingestion] Figure processing failed (non-fatal): {e}")

        # ── Step 4: 合并并写入 Elasticsearch ─────────────────────────────
        all_chunks = enhance_chunks_with_figures(text_chunks, figure_chunks)
        print(f"[Ingestion] Total chunks to index: {len(all_chunks)}")

        try:
            indexer = ElasticsearchIndexer()
            indexer.index_chunk_documents(all_chunks)
            print(f"[Ingestion] Indexed {len(all_chunks)} chunks into ES for doc={doc_id}")
        except Exception as e:
            print(f"[Ingestion] ES indexing failed: {e}")
            _update_status(db, doc_id, "failed")
            return

        # ── Step 5: 更新状态为 ready ───────────────────────────────────
        _update_status(db, doc_id, "ready")
        print(f"[Ingestion] ✅ Pipeline complete for doc_id={doc_id}")

    except Exception as e:
        print(f"[Ingestion] Unexpected error: {e}")
        _update_status(db, doc_id, "failed")
    finally:
        db.close()


def _update_status(db, doc_id: str, status: str):
    """更新文档状态"""
    doc = db.query(DocumentMetadata).filter(DocumentMetadata.id == doc_id).first()
    if doc:
        doc.status = status
        db.commit()
        print(f"[Ingestion] Status updated: {doc_id} → {status}")


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
    file_hash = hashlib.sha256(content).hexdigest()

    # 防重检查
    existing = db.query(DocumentMetadata).filter(DocumentMetadata.hash == file_hash).first()
    if existing:
        return {
            "status": "fast_resume",
            "message": "File already exists",
            "documentId": existing.id,
            "filename": existing.filename,
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
    background_tasks.add_task(run_ingestion_pipeline, doc_id, real_path, file.filename)

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