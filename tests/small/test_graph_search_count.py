"""Edge case tests for GraphLogicTool.count_relations_by_doc().

Follows the established @patch pattern from test_graph_search.py to avoid
real Neo4j connections during small tests.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestCountRelationsByDocEdgeCases:
    """count_relations_by_doc() — 特殊 doc_id 边界情况。"""

    @pytest.mark.small
    @patch("src.retrieval.graph_search.GraphDatabase")
    def test_doc_id_with_special_characters(self, mock_graph_db):
        """doc_id 包含特殊字符（斜杠、引号、反斜杠）时应正确参数化。"""
        from src.retrieval.graph_search import GraphLogicTool

        mock_record = MagicMock()
        mock_record.__getitem__.return_value = 5
        mock_result = MagicMock()
        mock_result.single.return_value = mock_record
        mock_session = MagicMock()
        mock_session.run.return_value = mock_result

        tool = GraphLogicTool()
        tool.driver.session.return_value.__enter__.return_value = mock_session

        doc_id = "test-doc/with\\special'chars\""
        result = tool.count_relations_by_doc(doc_id)

        assert result == 5
        # Verify the doc_id was passed as a parameter (not string interpolation)
        call_kwargs = mock_session.run.call_args
        assert call_kwargs[1]["doc_id"] == doc_id

    @pytest.mark.small
    @patch("src.retrieval.graph_search.GraphDatabase")
    def test_long_doc_id(self, mock_graph_db):
        """长 UUID 风格的 doc_id 应正确处理。"""
        from src.retrieval.graph_search import GraphLogicTool

        mock_record = MagicMock()
        mock_record.__getitem__.return_value = 3
        mock_result = MagicMock()
        mock_result.single.return_value = mock_record
        mock_session = MagicMock()
        mock_session.run.return_value = mock_result

        tool = GraphLogicTool()
        tool.driver.session.return_value.__enter__.return_value = mock_session

        long_id = "a" * 64 + "-" + "b" * 32
        result = tool.count_relations_by_doc(long_id)

        assert result == 3

    @pytest.mark.small
    @patch("src.retrieval.graph_search.GraphDatabase")
    def test_doc_id_with_unicode_chinese(self, mock_graph_db):
        """中文 doc_id（论文标题）应正确处理。"""
        from src.retrieval.graph_search import GraphLogicTool

        mock_record = MagicMock()
        mock_record.__getitem__.return_value = 7
        mock_result = MagicMock()
        mock_result.single.return_value = mock_record
        mock_session = MagicMock()
        mock_session.run.return_value = mock_result

        tool = GraphLogicTool()
        tool.driver.session.return_value.__enter__.return_value = mock_session

        doc_id = "Ti-6Al-4V合金的高温拉伸性能研究"
        result = tool.count_relations_by_doc(doc_id)

        assert result == 7
        call_kwargs = mock_session.run.call_args
        assert call_kwargs[1]["doc_id"] == doc_id
