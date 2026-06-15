import pytest
from unittest.mock import patch, MagicMock
from src.tooling.definitions import search_available_tools

@pytest.mark.small
@patch("src.tooling.definitions.get_tool_search_engine")
def test_search_available_tools_success(mock_get_engine):
    # Mock search engine
    mock_engine = MagicMock()
    mock_engine.search.return_value = [
        {
            "name": "execute_metallurgy_python",
            "category": "calculation",
            "description": "有状态 Python 代码沙盒",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"}
                }
            }
        }
    ]
    mock_get_engine.return_value = mock_engine

    # Run tool
    result = search_available_tools("python")

    # Assert search called and returns schema
    mock_engine.search.assert_called_once_with("python", max_results=5)
    assert "找到 1 个匹配工具：" in result
    assert "工具名: execute_metallurgy_python" in result
    assert "参数 Schema:" in result


@pytest.mark.small
@patch("src.tooling.definitions.get_tool_search_engine")
def test_search_available_tools_not_found(mock_get_engine):
    # Mock search engine
    mock_engine = MagicMock()
    mock_engine.search.return_value = []
    mock_engine.get_deferred_tool_names.return_value = ["execute_metallurgy_python"]
    mock_get_engine.return_value = mock_engine

    # Run tool
    result = search_available_tools("nonexistent_query")

    mock_engine.search.assert_called_once_with("nonexistent_query", max_results=5)
    assert "未找到匹配 'nonexistent_query' 的工具。" in result
    assert "当前可搜索的延迟工具列表：execute_metallurgy_python" in result
