import pytest
from unittest.mock import patch, MagicMock
import json
from src.retrieval.hyde_searcher import HyDESearcher

@patch('src.retrieval.hyde_searcher.ChatOpenAI.invoke')
@patch('src.retrieval.hyde_searcher.GraphLogicTool.find_direct_relations')
@patch('src.retrieval.hyde_searcher.SemanticSearchTool.search')
def test_hyde_search_pipeline(mock_semantic_search, mock_graph_search, mock_llm_invoke):
    """
    测试 KG-Anchored HyDE 检索管线。
    中型测试：Mock 掉真实大模型以及底层数据库查询，验证组装与协同逻辑。
    """
    # 1. 模拟实体提取 (json_llm) 返回
    mock_entity_response = MagicMock()
    mock_entity_response.content = json.dumps({"entities": ["转炉", "终点碳含量"]})
    
    # 2. 模拟 HyDE 假设性文档生成 (llm) 返回
    mock_hyde_response = MagicMock()
    mock_hyde_response.content = "转炉终点碳含量的关键因素在于吹炼时间和氧枪高度..."
    
    # 设置 side_effect 分别对应实体提取和文档生成
    mock_llm_invoke.side_effect = [mock_entity_response, mock_hyde_response]
    
    # 3. 模拟图谱查询返回
    mock_graph_search.return_value = [
        {"subject": "转炉", "relation": "uses_equipment", "object": "顶吹工艺", "mechanism": "氧化反应", "context": ""}
    ]
    
    # 4. 模拟最终语义检索返回
    mock_result_chunk = MagicMock()
    mock_result_chunk.chunk_id = "chunk-123"
    mock_result_chunk.score = 0.95
    mock_semantic_search.return_value = [mock_result_chunk]
    
    # 执行测试
    searcher = HyDESearcher(fast_mode=True)
    results = searcher.search("影响转炉终点碳含量的关键因素是什么？", top_k=2)
    
    # 验证返回结果
    assert len(results) == 1
    assert results[0].chunk_id == "chunk-123"
    
    # 验证大模型调用次数 (1次提取实体, 1次生成文档)
    assert mock_llm_invoke.call_count == 2
    
    # 验证语义检索时，确实把原问题和生成的HyDE文档融合在一起了
    semantic_call_args = mock_semantic_search.call_args[0]
    fused_query = semantic_call_args[0]
    assert "影响转炉终点碳含量的关键因素" in fused_query
    assert "转炉终点碳含量的关键因素在于吹炼时间" in fused_query
