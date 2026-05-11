#!/usr/bin/env python3
"""
批量回补索引脚本 — 将数据库中所有 pending/failed 状态的 PDF 重新索引到 ES。

用法：
  ./env_xiaoye/bin/python scripts/reindex_pending_docs.py
  ./env_xiaoye/bin/python scripts/reindex_pending_docs.py --doc-id <uuid>  # 只处理指定文档

确保 ES 和后端依赖已就绪后再运行。
"""

import sys
import os
import argparse

# 把项目根目录加入路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 清除代理
for key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(key, None)


def reindex_doc(doc_id: str, pdf_path: str, filename: str) -> bool:
    """对单个文档运行完整索引管线，返回是否成功。"""
    from src.core.config import settings
    os.environ["OPENAI_API_KEY"] = settings.QWEN_API_KEY
    os.environ["OPENAI_API_BASE"] = settings.QWEN_BASE_URL

    from src.pipeline.pdf_parser import (
        extract_pdf_with_marker,
        split_markdown_into_chunk_documents,
        process_figures,
        enhance_chunks_with_figures,
    )
    from src.pipeline.es_indexer import ElasticsearchIndexer
    from src.db.session import SessionLocal
    from src.models.document import DocumentMetadata

    print(f"\n{'='*60}")
    print(f"[ReIndex] Processing: {filename} ({doc_id})")
    print(f"{'='*60}")

    db = SessionLocal()
    try:
        # Step 1: Marker PDF 解析
        marker_out = os.path.join(PROJECT_ROOT, "data", "marker_output")
        os.makedirs(marker_out, exist_ok=True)

        try:
            md_text, image_paths, out_metadata = extract_pdf_with_marker(
                filepath=pdf_path,
                out_dir=marker_out,
            )
            print(f"  ✅ Marker: {len(md_text)} chars, {len(image_paths)} images")
        except Exception as e:
            print(f"  ⚠️  Marker failed: {e}")
            print(f"  → Falling back to PyMuPDF...")
            try:
                import fitz
                doc = fitz.open(pdf_path)
                md_text = "\n\n".join(page.get_text() for page in doc)
                image_paths, out_metadata = [], {}
                print(f"  ✅ PyMuPDF fallback: {len(md_text)} chars")
            except Exception as e2:
                print(f"  ❌ All extraction failed: {e2}")
                _set_status(db, doc_id, "failed")
                return False

        if not md_text.strip():
            print(f"  ❌ No text extracted")
            _set_status(db, doc_id, "failed")
            return False

        # Step 2: Chunking
        text_chunks = split_markdown_into_chunk_documents(
            md_text=md_text,
            out_metadata=out_metadata,
            doc_id=doc_id,
            source_pdf_id=filename,
        )
        print(f"  ✅ Text chunks: {len(text_chunks)}")

        # Step 3: 图片 Chunks
        figure_chunks = []
        if image_paths:
            try:
                figure_chunks = process_figures(
                    md_text=md_text,
                    image_paths=image_paths,
                    doc_id=doc_id,
                    source_pdf_id=filename,
                    analyze_with_vlm=False,
                )
                print(f"  ✅ Figure chunks: {len(figure_chunks)}")
            except Exception as e:
                print(f"  ⚠️  Figure processing skipped: {e}")

        # Step 4: ES 索引
        all_chunks = enhance_chunks_with_figures(text_chunks, figure_chunks)
        print(f"  → Indexing {len(all_chunks)} total chunks to ES...")

        try:
            indexer = ElasticsearchIndexer()
            indexer.index_chunk_documents(all_chunks)
            print(f"  ✅ ES indexing complete")
        except Exception as e:
            print(f"  ❌ ES indexing failed: {e}")
            _set_status(db, doc_id, "failed")
            return False

        # Step 5: 更新状态
        _set_status(db, doc_id, "ready")
        print(f"  ✅ Status → ready")
        return True

    except Exception as e:
        print(f"  ❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        _set_status(db, doc_id, "failed")
        return False
    finally:
        db.close()


def _set_status(db, doc_id: str, status: str):
    from src.models.document import DocumentMetadata
    doc = db.query(DocumentMetadata).filter(DocumentMetadata.id == doc_id).first()
    if doc:
        doc.status = status
        db.commit()


def main():
    parser = argparse.ArgumentParser(description="Re-index pending PDF documents to Elasticsearch")
    parser.add_argument("--doc-id", help="Only re-index specific document ID")
    parser.add_argument("--force", action="store_true", help="Also re-index 'ready' documents")
    args = parser.parse_args()

    from src.db.session import SessionLocal
    from src.models.document import DocumentMetadata

    db = SessionLocal()
    try:
        query = db.query(DocumentMetadata)
        if args.doc_id:
            query = query.filter(DocumentMetadata.id == args.doc_id)
        elif not args.force:
            query = query.filter(DocumentMetadata.status.in_(["pending", "failed"]))

        docs = query.all()
        print(f"\n[ReIndex] Found {len(docs)} document(s) to process")

        if not docs:
            print("[ReIndex] Nothing to do. Use --force to re-index all documents.")
            return
    finally:
        db.close()

    success, failure = 0, 0
    for doc in docs:
        if not os.path.exists(doc.real_path):
            print(f"  ⚠️  File not found: {doc.real_path} — skipping")
            failure += 1
            continue

        ok = reindex_doc(doc.id, doc.real_path, doc.filename)
        if ok:
            success += 1
        else:
            failure += 1

    print(f"\n{'='*60}")
    print(f"[ReIndex] Done: {success} success, {failure} failed")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
