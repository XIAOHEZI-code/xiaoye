"""
Ingestion Pipeline — 统一入库管线编排器 (重构后作为 Extraction 和 Storage Routing 的中介层)

数据流：
  PDF Bytes → 抽取引擎 (Knowledge Extraction) → DocumentResult → 存储分发 (Storage Dispatcher) → ES/Neo4j/PG 写入
"""

import os
import base64
from typing import Optional
from src.core.config import settings
from src.core.logger import setup_logger
from src.ingestion.status_tracker import StatusTracker, IngestionStage
from src.models.document import DocumentMetadata

logger = setup_logger("xiaoye.ingestion")


class IngestionPipeline:
    """PDF 入库管线编排器 (中介者)"""

    def __init__(
        self,
        doc_id: str,
        pdf_path: str,
        filename: str,
        marker_out_dir: str = "data/marker_output",
        workspace_id: Optional[str] = None,
    ):
        self.doc_id = doc_id
        self.pdf_path = pdf_path
        self.filename = filename
        self.marker_out_dir = marker_out_dir
        self.workspace_id = workspace_id
        self.tracker = StatusTracker(doc_id)

        os.makedirs(self.marker_out_dir, exist_ok=True)

    def run(self):
        """同步执行完整入库管线。"""
        from src.db.session import SessionLocal
        from src.ingestion.extraction_engine import DocumentKnowledgeExtractionEngine
        from src.ingestion.models import ExtractionError

        self.tracker.emit(IngestionStage.STARTED, "入库管线已启动")
        logger.info(f"Starting pipeline coordinator for doc_id={self.doc_id}, file={self.filename}")

        db = SessionLocal()
        try:
            # 1. 读入原始文件二进制流
            if not os.path.exists(self.pdf_path):
                raise ExtractionError(f"源文件不存在: {self.pdf_path}")
            
            with open(self.pdf_path, "rb") as f:
                file_bytes = f.read()

            # 2. 调用文档知识抽取引擎 (只负责数据提取转化，不对接数据库)
            self._update_db_status(db, "parsing")
            
            engine = DocumentKnowledgeExtractionEngine()
            result = engine.extract_knowledge(
                file_stream=file_bytes,
                file_type="pdf",
                on_progress=self._on_progress_callback
            )

            # 3. 将结果进行本地分发与存储路由写入 (Storage Routing)
            self._update_db_status(db, "indexing")
            from src.ingestion.pdf_parser import split_markdown_into_chunk_documents
            
            # 分块：一次分块，同时供 ES 索引和引擎上下文使用
            text_chunks = split_markdown_into_chunk_documents(
                md_text=result.markdown_text,
                out_metadata={},
                doc_id=self.doc_id,
                source_pdf_id=self.filename,
            )
            self._dispatch_to_storage_routing(db, result, text_chunks)

            # 4. 数据一致性验证 (ES/Neo4j/PG)
            self._update_db_status(db, "verifying")
            try:
                self._step_verify_storage(db, self.doc_id, self.filename)
            except Exception as e:
                self.tracker.emit(
                    IngestionStage.VERIFY_FAILED,
                    f"⚠️ 入库管线异常：数据一致性验证失败，原因: {e}。已保留当前状态供排查",
                )
                self._update_db_status(db, "verify_failed")
                logger.error(f"[{self.doc_id[:8]}] ❌ 验证失败，原因: {e}，管线中止")
                return

            # 5. 更新状态为 ready
            self._update_db_status(db, "ready")
            self.tracker.emit(IngestionStage.COMPLETED, "入库管线已完成")
            logger.info(f"✅ Pipeline complete for doc_id={self.doc_id}")

        except ExtractionError as ee:
            logger.error(f"Extraction fatal error: {ee}", exc_info=True)
            self.tracker.emit(IngestionStage.FAILED, f"入库异常: {ee}")
            self._update_db_status(db, "failed")
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            self.tracker.emit(IngestionStage.FAILED, f"系统异常: {e}")
            self._update_db_status(db, "failed")
        finally:
            db.close()

    def _on_progress_callback(self, stage_name: str, status_msg: str):
        """状态回调函数，映射至管线事件阶段"""
        mapping = {
            "parsing": IngestionStage.PARSING,
            "chunking": IngestionStage.CHUNKING,
            "figures": IngestionStage.FIGURES,
            "indexing": IngestionStage.INDEXING,
            "graphing": IngestionStage.GRAPHING,
            "verifying": IngestionStage.VERIFYING,
        }
        stage = mapping.get(stage_name, IngestionStage.PARSING)
        self.tracker.emit(stage, status_msg)

    def _dispatch_to_storage_routing(self, db, result, text_chunks=None):
        """持久化存储路由分发实现 (已使用 Storage Routing Module 进行分发路由)"""
        # 1. 恢复提取的图片到本地磁盘，并同步写入 PostgreSQL 资产元数据
        from src.db.storage_router import save_raw_assets, save_knowledge_graph
        
        save_raw_assets(result.media_assets, doc_id=self.doc_id, filename=self.filename)

        # 2. ES 写入（使用调用方预分块的 text_chunks）
        basename = os.path.splitext(os.path.basename(self.filename))[0]
        target_img_dir = os.path.join(self.marker_out_dir, basename)
        
        from src.models.chunk_document import make_image_chunk
        from src.ingestion.es_indexer import ElasticsearchIndexer
        from src.ingestion.pdf_parser import enhance_chunks_with_figures

        chunks_to_index = text_chunks if text_chunks is not None else []
        
        # 图片切块
        figure_chunks = []
        for asset in result.media_assets:
            img_path = os.path.join(target_img_dir, asset.image_filename)
            figure_chunks.append(
                make_image_chunk(
                    description=asset.description if asset.description else asset.caption,
                    doc_id=self.doc_id,
                    source_pdf_id=self.filename,
                    image_uri=img_path,
                    chunk_type="figure",
                )
            )

        all_chunks = enhance_chunks_with_figures(chunks_to_index, figure_chunks)
        indexer = ElasticsearchIndexer()
        indexer.index_chunk_documents(all_chunks)
        self.tracker.emit(
            IngestionStage.INDEXING, f"索引完成: {len(all_chunks)} 个块已写入 ES"
        )

        # 3. 知识图谱三元组写入 Neo4j (调用 Storage Routing 统一接口)
        if result.triplet_list:
            save_knowledge_graph(result.triplet_list, doc_id=self.doc_id)
            self.tracker.emit(
                IngestionStage.GRAPHING,
                f"图谱构建完成: 成功向 Neo4j 注入 {len(result.triplet_list)} 个关系",
            )

        # 4. 冶金物理/工艺参数写入 PostgreSQL
        if self.workspace_id and result.extracted_parameters:
            from src.models.workspace import WorkspaceParameter
            from datetime import datetime, timezone

            for param in result.extracted_parameters:
                try:
                    existing = (
                        db.query(WorkspaceParameter)
                        .filter(
                            WorkspaceParameter.workspace_id == self.workspace_id,
                            WorkspaceParameter.key == param.key,
                        )
                        .first()
                    )
                    if existing:
                        existing.value = param.value
                        existing.source_doc_id = self.doc_id
                        existing.updated_at = datetime.now(timezone.utc)
                    else:
                        db_param = WorkspaceParameter(
                            workspace_id=self.workspace_id,
                            key=param.key,
                            value=param.value,
                            source_doc_id=self.doc_id,
                        )
                        db.add(db_param)
                    db.commit()
                except Exception as ex:
                    db.rollback()
                    logger.warning(f"Error upserting parameter '{param.key}', retrying: {ex}")
                    # Retry: query existing again, update/insert, and commit
                    existing = (
                        db.query(WorkspaceParameter)
                        .filter(
                            WorkspaceParameter.workspace_id == self.workspace_id,
                            WorkspaceParameter.key == param.key,
                        )
                        .first()
                    )
                    if existing:
                        existing.value = param.value
                        existing.source_doc_id = self.doc_id
                        existing.updated_at = datetime.now(timezone.utc)
                    else:
                        db_param = WorkspaceParameter(
                            workspace_id=self.workspace_id,
                            key=param.key,
                            value=param.value,
                            source_doc_id=self.doc_id,
                        )
                        db.add(db_param)
                    try:
                        db.commit()
                    except Exception as final_ex:
                        db.rollback()
                        logger.error(f"Failed to upsert parameter '{param.key}' on retry: {final_ex}")

    def _step_verify_storage(self, db, doc_id: str, filename: str):
        """验证 ES/Neo4j/PG 数据完整性"""
        self.tracker.emit(IngestionStage.VERIFYING, "正在验证数据一致性...")
        from src.ingestion.es_indexer import ElasticsearchIndexer

        # 1. 验证 ES
        indexer = ElasticsearchIndexer()
        es_count = indexer.count_chunks_by_doc(doc_id)
        if es_count == 0:
            raise RuntimeError(f"ES 验证失败: 预期 chunk 数 > 0，实际 = {es_count}")

        # 2. 验证 Neo4j（0条关系是合法的，仅检查连通性）
        try:
            from src.retrieval.graph_search import GraphLogicTool

            graph_tool = GraphLogicTool()
            neo4j_count = graph_tool.count_relations_by_doc(doc_id)
        except Exception as e:
            logger.warning(f"[{doc_id[:8]}] ⚠️ Neo4j 验证异常（非致命）: {e}")
            neo4j_count = -1

        # 3. 验证 PG
        doc = db.query(DocumentMetadata).filter(DocumentMetadata.id == doc_id).first()
        if not doc:
            raise RuntimeError(f"PG 验证失败: 找不到 doc_id={doc_id} 的记录")

        # 成功
        detail = f"ES: {es_count} chunks, Neo4j: {neo4j_count} relations"
        self.tracker.emit(
            IngestionStage.VERIFYING,
            f"✅ 数据一致性验证通过 — {detail}",
        )
        logger.info(f"[{doc_id[:8]}] ✅ 验证通过: {detail}")

    def _update_db_status(self, db, status: str):
        """更新文档状态到 PostgreSQL"""
        doc = (
            db.query(DocumentMetadata)
            .filter(DocumentMetadata.id == self.doc_id)
            .first()
        )
        if doc:
            doc.status = status
            db.commit()
            logger.info(f"Status updated: {self.doc_id} → {status}")

    def _step_extract_metallurgical_parameters(self, text_chunks: list, workspace_id: str):
        """Deprecated compatibility method to extract and persist parameters, used by tests."""
        from src.ingestion.extraction_engine import DocumentKnowledgeExtractionEngine
        from src.ingestion.models import DocumentResult
        from src.db.session import SessionLocal

        engine = DocumentKnowledgeExtractionEngine()
        extracted_parameters = engine._extract_metallurgical_parameters(text_chunks)
        result = DocumentResult(
            markdown_text="",
            triplet_list=[],
            media_assets=[],
            extracted_parameters=extracted_parameters
        )
        db = SessionLocal()
        try:
            self._dispatch_to_storage_routing(db, result)
        finally:
            db.close()
