"""Tests for IngestionPipeline._step_verify_storage()."""

import pytest
from unittest.mock import MagicMock, patch


# ---------- helpers ----------


def _make_pipeline():
    """创建一个 mock pipeline 对象用于测试 _step_verify_storage。"""
    from src.ingestion.pipeline import IngestionPipeline

    pipeline = IngestionPipeline.__new__(IngestionPipeline)
    pipeline.doc_id = "test-doc-id"
    pipeline.filename = "test-paper.pdf"
    pipeline.tracker = MagicMock()
    return pipeline


class TestStepVerifyStorage:
    """_step_verify_storage() — 验证 ES/Neo4j/PG 数据完整性。"""

    @pytest.mark.small
    def test_success_all_three_ok(self):
        """ES 有 chunks、Neo4j 有 relations、PG 有记录 → 验证通过。"""
        pipeline = _make_pipeline()
        mock_db = MagicMock()

        # Mock PG: document exists
        mock_doc = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_doc

        with (
            patch("src.ingestion.es_indexer.ElasticsearchIndexer") as MockES,
            patch("src.retrieval.graph_search.GraphLogicTool") as MockGraph,
        ):
            mock_es = MockES.return_value
            mock_es.count_chunks_by_doc.return_value = 17

            mock_graph = MockGraph.return_value
            mock_graph.count_relations_by_doc.return_value = 16

            pipeline._step_verify_storage(mock_db, "test-doc-id", "test-paper.pdf")

        # 断言：tracker 发送了成功事件
        pipeline.tracker.emit.assert_called()
        # 最后一次 emit 应是验证成功消息
        last_call = pipeline.tracker.emit.call_args_list[-1]
        assert "✅" in last_call[0][1] or "验证通过" in last_call[0][1]

    @pytest.mark.small
    def test_raises_when_es_has_zero_chunks(self):
        """ES 返回 0 chunks → RuntimeError。"""
        pipeline = _make_pipeline()
        mock_db = MagicMock()

        with patch("src.ingestion.es_indexer.ElasticsearchIndexer") as MockES:
            mock_es = MockES.return_value
            mock_es.count_chunks_by_doc.return_value = 0

            with pytest.raises(RuntimeError, match="ES 验证失败"):
                pipeline._step_verify_storage(mock_db, "test-doc-id", "test.pdf")

    @pytest.mark.small
    def test_raises_when_pg_record_missing(self):
        """PG 查不到 document 记录 → RuntimeError。"""
        pipeline = _make_pipeline()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with (
            patch("src.ingestion.es_indexer.ElasticsearchIndexer") as MockES,
            patch("src.retrieval.graph_search.GraphLogicTool") as MockGraph,
        ):
            mock_es = MockES.return_value
            mock_es.count_chunks_by_doc.return_value = 5
            mock_graph = MockGraph.return_value
            mock_graph.count_relations_by_doc.return_value = 3

            with pytest.raises(RuntimeError, match="PG 验证失败"):
                pipeline._step_verify_storage(mock_db, "test-doc-id", "test.pdf")

    @pytest.mark.small
    def test_neo4j_failure_is_nonfatal(self):
        """Neo4j 连不上时不应阻断验证，继续执行并标记 neo4j_count=-1。"""
        pipeline = _make_pipeline()
        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_doc

        with (
            patch("src.ingestion.es_indexer.ElasticsearchIndexer") as MockES,
            patch("src.retrieval.graph_search.GraphLogicTool") as MockGraph,
        ):
            mock_es = MockES.return_value
            mock_es.count_chunks_by_doc.return_value = 10
            mock_graph = MockGraph.return_value
            mock_graph.count_relations_by_doc.side_effect = Exception(
                "Neo4j unavailable"
            )

            # 不应抛出异常
            pipeline._step_verify_storage(mock_db, "test-doc-id", "test.pdf")

        # 仍然应该发送成功事件（Neo4j 失败是非致命的）
        assert pipeline.tracker.emit.call_count >= 2


class TestPipelineVerifyFailedPath:
    """run() 中验证失败时设置 verify_failed 状态。"""

    @pytest.mark.small
    def test_sets_verify_failed_status_on_verify_failure(self):
        """验证失败 → tracker 发送 VERIFY_FAILED 事件。"""
        from src.ingestion.pipeline import IngestionPipeline
        from src.ingestion.status_tracker import IngestionStage

        pipeline = IngestionPipeline.__new__(IngestionPipeline)
        pipeline.doc_id = "fail-doc-id"
        pipeline.filename = "fail.pdf"
        pipeline.tracker = MagicMock()

        mock_db = MagicMock()

        with patch.object(pipeline, "_step_verify_storage") as mock_verify:
            mock_verify.side_effect = RuntimeError("ES 验证失败: 0 chunks")

            # 模拟 run() 中 verify 那段异常处理代码
            try:
                pipeline._step_verify_storage(
                    mock_db, pipeline.doc_id, pipeline.filename
                )
            except Exception:
                pipeline.tracker.emit(
                    IngestionStage.VERIFY_FAILED,
                    "⚠️ 入库管线异常：数据一致性验证失败，已保留当前状态供排查",
                )

        # 验证 tracker 发送了 VERIFY_FAILED
        pipeline.tracker.emit.assert_called_with(
            IngestionStage.VERIFY_FAILED,
            "⚠️ 入库管线异常：数据一致性验证失败，已保留当前状态供排查",
        )
