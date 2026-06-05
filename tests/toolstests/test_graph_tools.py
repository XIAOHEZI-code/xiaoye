import pytest
from unittest.mock import patch, MagicMock
from src.tooling.definitions import search_metallurgy_graph_relations, trace_metallurgy_impact_path

@pytest.mark.small
@patch("src.tooling.definitions.graph_searcher.find_direct_relations")
def test_search_metallurgy_graph_relations_success(mock_relations):
    # Mock graph relationships
    mock_relations.return_value = [
        {
            "subject": "304不锈钢",
            "relation": "发生",
            "object": "敏化现象",
            "source_doc": "sensitization_study.pdf",
            "mechanism": "奥氏体不锈钢在450~850℃加热时碳化铬在晶界析出",
            "context": "敏化会导致晶间腐蚀"
        }
    ]

    result = search_metallurgy_graph_relations("304不锈钢")

    mock_relations.assert_called_once_with("304不锈钢")
    assert "Found 1 relations:" in result
    assert "(304不锈钢) -[发生]-> (敏化现象) [Source: sensitization_study.pdf]" in result


@pytest.mark.small
@patch("src.tooling.definitions.graph_searcher.trace_impact_path")
def test_trace_metallurgy_impact_path_success(mock_trace):
    # Mock impact paths
    mock_trace.return_value = [
        {
            "nodes": ["调质处理", "板条马氏体", "抗剪切强度提升"]
        }
    ]

    result = trace_metallurgy_impact_path("调质处理")

    mock_trace.assert_called_once_with("调质处理")
    assert "Found 1 impact paths:" in result
    assert "Path 1: 调质处理 -> 板条马氏体 -> 抗剪切强度提升" in result
