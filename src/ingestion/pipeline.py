"""
Ingestion Pipeline — 统一入库管线编排器

将 upload_routes.py 中的 run_ingestion_pipeline 逻辑提取为独立管线，
支持进度追踪、SSE 推送、错误恢复。

数据流：
  PDF → Marker 解析 → 文本分块 → 图片处理 → ES 向量化索引 → 状态更新

设计原则：
  1. 不依赖任何 Agent/Tools/Delivery 管线代码
  2. 所有对外通信通过 StatusTracker SSE 事件
  3. 每一步均有独立错误处理和降级策略
"""

import os
from typing import Optional
from src.core.config import settings
from src.ingestion.status_tracker import StatusTracker, IngestionStage


class IngestionPipeline:
    """PDF 入库管线编排器"""

    def __init__(self, doc_id: str, pdf_path: str, filename: str,
                 marker_out_dir: str = "data/marker_output"):
        self.doc_id = doc_id
        self.pdf_path = pdf_path
        self.filename = filename
        self.marker_out_dir = marker_out_dir
        self.tracker = StatusTracker(doc_id)

        os.makedirs(self.marker_out_dir, exist_ok=True)

    def run(self):
        """
        同步执行完整入库管线。

        步骤：
          1. Marker PDF → Markdown + 图片
          2. 文本分块 (ChunkDocument)
          3. 图片处理 (图注提取，可选 VLM)
          4. ES 向量化批量写入
          5. 更新文档状态为 ready
        """
        from src.db.session import SessionLocal

        # 清除代理，确保直连 Dashscope
        self._clear_proxy()

        self.tracker.emit(IngestionStage.STARTED, "入库管线已启动")
        print(f"[Ingestion] Starting pipeline for doc_id={self.doc_id}, file={self.filename}")

        db = SessionLocal()
        try:
            # ── Step 1: Marker PDF → Markdown ──────────────────────────
            md_text, image_paths, out_metadata = self._step_parse_pdf()
            if md_text is None:
                self._update_db_status(db, "failed")
                return

            # ── Step 2: 文本分块 ──────────────────────────────────────
            text_chunks = self._step_chunk_text(md_text, out_metadata)

            # ── Step 3: 图片处理 ──────────────────────────────────────
            figure_chunks = self._step_process_figures(md_text, image_paths)

            # ── Step 4: ES 向量化写入 ─────────────────────────────────
            success = self._step_index_to_es(text_chunks, figure_chunks)
            if not success:
                self._update_db_status(db, "failed")
                return

            # ── Step 5: 更新状态 ──────────────────────────────────────
            self._update_db_status(db, "ready")
            self.tracker.emit(IngestionStage.COMPLETED, "入库管线已完成")
            print(f"[Ingestion] ✅ Pipeline complete for doc_id={self.doc_id}")

        except Exception as e:
            print(f"[Ingestion] Unexpected error: {e}")
            self.tracker.emit(IngestionStage.FAILED, f"入库异常: {e}")
            self._update_db_status(db, "failed")
        finally:
            db.close()

    # ── 各步骤实现 ──────────────────────────────────────────────────

    def _step_parse_pdf(self):
        """Step 1: PDF → Markdown"""
        self.tracker.emit(IngestionStage.PARSING, "正在解析 PDF...")

        try:
            from src.ingestion.pdf_parser import (
                extract_pdf_with_marker,
            )
            md_text, image_paths, out_metadata = extract_pdf_with_marker(
                filepath=self.pdf_path,
                out_dir=self.marker_out_dir,
            )
            self.tracker.emit(IngestionStage.PARSING,
                              f"PDF 解析完成: {len(md_text)} 字符, {len(image_paths)} 张图片")
            return md_text, image_paths, out_metadata
        except Exception as e:
            print(f"[Ingestion] Marker failed: {e}. Falling back to PyMuPDF.")
            # 降级：PyMuPDF 纯文本
            try:
                import fitz
                doc = fitz.open(self.pdf_path)
                md_text = "\n\n".join(page.get_text() for page in doc)
                self.tracker.emit(IngestionStage.PARSING,
                                  f"PyMuPDF 降级解析: {len(md_text)} 字符")
                return md_text, [], {}
            except Exception as e2:
                print(f"[Ingestion] All extraction failed: {e2}")
                self.tracker.emit(IngestionStage.FAILED, f"PDF 解析失败: {e2}")
                return None, None, None

    def _step_chunk_text(self, md_text: str, out_metadata: dict) -> list:
        """Step 2: 文本分块"""
        self.tracker.emit(IngestionStage.CHUNKING, "正在分块...")

        from src.ingestion.pdf_parser import split_markdown_into_chunk_documents
        text_chunks = split_markdown_into_chunk_documents(
            md_text=md_text,
            out_metadata=out_metadata,
            doc_id=self.doc_id,
            source_pdf_id=self.filename,
        )
        self.tracker.emit(IngestionStage.CHUNKING, f"分块完成: {len(text_chunks)} 个文本块")
        print(f"[Ingestion] Text chunks: {len(text_chunks)}")
        return text_chunks

    def _step_process_figures(self, md_text: str, image_paths: list) -> list:
        """Step 3: 图片处理"""
        if not image_paths:
            return []

        self.tracker.emit(IngestionStage.FIGURES, "正在处理图片...")

        try:
            from src.ingestion.pdf_parser import process_figures
            figure_chunks = process_figures(
                md_text=md_text,
                image_paths=image_paths,
                doc_id=self.doc_id,
                source_pdf_id=self.filename,
                analyze_with_vlm=False,
            )
            self.tracker.emit(IngestionStage.FIGURES, f"图片处理完成: {len(figure_chunks)} 个图片块")
            print(f"[Ingestion] Figure chunks: {len(figure_chunks)}")
            return figure_chunks
        except Exception as e:
            print(f"[Ingestion] Figure processing failed (non-fatal): {e}")
            self.tracker.emit(IngestionStage.FIGURES, f"图片处理失败(非致命): {e}")
            return []

    def _step_index_to_es(self, text_chunks: list, figure_chunks: list) -> bool:
        """Step 4: ES 向量化写入"""
        self.tracker.emit(IngestionStage.INDEXING, "正在向量化索引...")

        from src.ingestion.pdf_parser import enhance_chunks_with_figures
        all_chunks = enhance_chunks_with_figures(text_chunks, figure_chunks)
        print(f"[Ingestion] Total chunks to index: {len(all_chunks)}")

        try:
            from src.ingestion.es_indexer import ElasticsearchIndexer
            indexer = ElasticsearchIndexer()
            indexer.index_chunk_documents(all_chunks)
            self.tracker.emit(IngestionStage.INDEXING,
                              f"索引完成: {len(all_chunks)} 个块已写入 ES")
            print(f"[Ingestion] Indexed {len(all_chunks)} chunks into ES")
            return True
        except Exception as e:
            print(f"[Ingestion] ES indexing failed: {e}")
            self.tracker.emit(IngestionStage.FAILED, f"ES 索引失败: {e}")
            return False

    # ── 辅助方法 ──────────────────────────────────────────────────

    def _update_db_status(self, db, status: str):
        """更新文档状态到 PostgreSQL"""
        from src.models.document import DocumentMetadata
        doc = db.query(DocumentMetadata).filter(DocumentMetadata.id == self.doc_id).first()
        if doc:
            doc.status = status
            db.commit()
            print(f"[Ingestion] Status updated: {self.doc_id} → {status}")

    @staticmethod
    def _clear_proxy():
        """清除代理环境变量"""
        for key in ["http_proxy", "https_proxy", "all_proxy",
                     "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
            os.environ.pop(key, None)
        os.environ["OPENAI_API_KEY"] = settings.QWEN_API_KEY
        os.environ["OPENAI_API_BASE"] = settings.QWEN_BASE_URL
