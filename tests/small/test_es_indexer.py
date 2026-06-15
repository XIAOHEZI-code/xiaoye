"""Tests for ElasticsearchIndexer.count_chunks_by_doc()."""

import pytest
from unittest.mock import MagicMock, patch, call


class TestCountChunksByDoc:
    """count_chunks_by_doc() — 查询指定文档在 ES 中的 chunk 数。"""

    @pytest.mark.small
    @patch("src.ingestion.es_indexer.OpenAIEmbeddings")
    @patch("src.ingestion.es_indexer.Elasticsearch")
    def test_returns_count_when_chunks_exist(self, mock_es_class, mock_embeddings):
        """ES 正常返回 chunk 计数。"""
        from src.ingestion.es_indexer import ElasticsearchIndexer

        indexer = ElasticsearchIndexer()
        indexer.es.count.return_value = {"count": 17}

        result = indexer.count_chunks_by_doc("test-doc-id")

        assert result == 17
        indexer.es.indices.refresh.assert_called_once_with(index=indexer.index_name)
        indexer.es.count.assert_called_once()

    @pytest.mark.small
    @patch("src.ingestion.es_indexer.OpenAIEmbeddings")
    @patch("src.ingestion.es_indexer.Elasticsearch")
    def test_returns_zero_when_no_chunks(self, mock_es_class, mock_embeddings):
        """ES 返回 0 — 数据丢失场景。"""
        from src.ingestion.es_indexer import ElasticsearchIndexer

        indexer = ElasticsearchIndexer()
        indexer.es.count.return_value = {"count": 0}

        result = indexer.count_chunks_by_doc("missing-doc-id")

        assert result == 0

    @pytest.mark.small
    @patch("src.ingestion.es_indexer.OpenAIEmbeddings")
    @patch("src.ingestion.es_indexer.Elasticsearch")
    def test_refresh_called_before_count(self, mock_es_class, mock_embeddings):
        """验证 refresh 和 count 都被调用。"""
        from src.ingestion.es_indexer import ElasticsearchIndexer

        indexer = ElasticsearchIndexer()
        indexer.es.count.return_value = {"count": 5}

        indexer.count_chunks_by_doc("doc-id")

        # refresh 必须在 count 之前被调用
        indexer.es.indices.refresh.assert_called_once_with(index=indexer.index_name)
        assert indexer.es.count.call_count == 1

    @pytest.mark.small
    @patch("src.ingestion.es_indexer.OpenAIEmbeddings")
    @patch("src.ingestion.es_indexer.Elasticsearch")
    def test_raises_when_es_unreachable(self, mock_es_class, mock_embeddings):
        """ES 连接失败应该原样抛出异常。"""
        from src.ingestion.es_indexer import ElasticsearchIndexer

        indexer = ElasticsearchIndexer()
        indexer.es.count.side_effect = ConnectionError("ES unavailable")

        with pytest.raises(ConnectionError, match="ES unavailable"):
            indexer.count_chunks_by_doc("any-doc")
