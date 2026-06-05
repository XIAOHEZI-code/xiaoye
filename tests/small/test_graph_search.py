"""Tests for GraphLogicTool.count_relations_by_doc()."""

import pytest
from unittest.mock import MagicMock, patch


class TestCountRelationsByDoc:
    """count_relations_by_doc() — 查询指定文档在 Neo4j 中的关系数量。"""

    @pytest.mark.small
    @patch("src.retrieval.graph_search.GraphDatabase")
    def test_returns_count_when_relations_exist(self, mock_graph_db):
        """Neo4j 正常返回关系数。"""
        from src.retrieval.graph_search import GraphLogicTool

        mock_record = MagicMock()
        mock_record.__getitem__.return_value = 16
        mock_result = MagicMock()
        mock_result.single.return_value = mock_record
        mock_session = MagicMock()
        mock_session.run.return_value = mock_result

        tool = GraphLogicTool()
        tool.driver.session.return_value.__enter__.return_value = mock_session

        result = tool.count_relations_by_doc("test-doc-id")

        assert result == 16
        mock_session.run.assert_called_once()
        # Verify Cypher query uses doc_id parameter
        call_kwargs = mock_session.run.call_args
        assert call_kwargs[1]["doc_id"] == "test-doc-id"
        assert "MATCH ()-[r {doc_id: $doc_id}]->()" in call_kwargs[0][0]

    @pytest.mark.small
    @patch("src.retrieval.graph_search.GraphDatabase")
    def test_returns_zero_when_no_relations(self, mock_graph_db):
        """无关系是合法的（该论文未被抽取或确实无三元组）。"""
        from src.retrieval.graph_search import GraphLogicTool

        mock_record = MagicMock()
        mock_record.__getitem__.return_value = 0
        mock_result = MagicMock()
        mock_result.single.return_value = mock_record
        mock_session = MagicMock()
        mock_session.run.return_value = mock_result

        tool = GraphLogicTool()
        tool.driver.session.return_value.__enter__.return_value = mock_session

        result = tool.count_relations_by_doc("doc-without-triplets")

        assert result == 0

    @pytest.mark.small
    @patch("src.retrieval.graph_search.GraphDatabase")
    def test_returns_zero_when_single_is_none(self, mock_graph_db):
        """single() 返回 None 时应该返回 0（防御性编程）。"""
        from src.retrieval.graph_search import GraphLogicTool

        mock_result = MagicMock()
        mock_result.single.return_value = None
        mock_session = MagicMock()
        mock_session.run.return_value = mock_result

        tool = GraphLogicTool()
        tool.driver.session.return_value.__enter__.return_value = mock_session

        result = tool.count_relations_by_doc("any-doc")

        assert result == 0
