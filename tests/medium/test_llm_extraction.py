import pytest
from unittest.mock import patch, MagicMock
import json
from src.ingestion.graph_extractor import Neo4jGraphExtractor, Triplet

@patch('src.ingestion.graph_extractor.GraphDatabase.driver')
@patch('src.ingestion.graph_extractor.ChatOpenAI.invoke')
def test_extract_triplets_from_text(mock_llm_invoke, mock_neo4j_driver):
    """
    测试大模型三元组抽取与规范化。
    中型测试 (Medium Test) 准则：必须 Mock 掉对真实大模型 API 的 HTTP 调用。
    此处同时 Mock 了 Neo4j 的连接，使得该测试可以在无 Docker 环境下快速跑通。
    """
    
    # 1. 模拟第一遍抽取 (Extraction) 的模型返回
    mock_extract_response = MagicMock()
    mock_extract_response.content = json.dumps({
        "triplets": [
            {
                "subject": "Q345钢",
                "subject_type": "Material",
                "relation": "has_property",
                "object": "抗拉强度",
                "object_type": "Property",
                "mechanism": "固溶强化",
                "context": "冷轧状态下"
            }
        ]
    })
    
    # 2. 模拟第二遍归一化 (Normalization) 的模型返回
    mock_normalize_response = MagicMock()
    mock_normalize_response.content = json.dumps({
        "triplets": [
            {
                "subject": "Q345",  # 假设模型将其规范化去掉了“钢”
                "subject_type": "Material",
                "relation": "has_property",
                "object": "抗拉强度",
                "object_type": "Property",
                "mechanism": "固溶强化",
                "context": "冷轧状态下"
            }
        ]
    })
    
    # 设置 side_effect 使其在连续调用时按顺序返回不同的结果
    mock_llm_invoke.side_effect = [mock_extract_response, mock_normalize_response]
    
    # 初始化 Extractor (底层依赖已被 patch)
    extractor = Neo4jGraphExtractor()
    
    sample_text = "冷轧状态下的Q345钢因为固溶强化作用，具有极高的抗拉强度。"
    triplets = extractor.extract_triplets_from_text(sample_text)
    
    # 验证核心抽取逻辑与 Pydantic 解析是否正常
    assert len(triplets) == 1, "应该成功抽取出一个三元组"
    
    t = triplets[0]
    assert t.subject == "Q345", "应体现第二遍归一化后的修改"
    assert t.subject_type == "Material"
    assert t.relation == "has_property"
    assert t.object_ == "抗拉强度"
    assert t.mechanism == "固溶强化"
    assert t.context == "冷轧状态下"
    
    # 验证 LLM 被成功调用了 2 次
    assert mock_llm_invoke.call_count == 2
