import pytest
from elasticsearch import Elasticsearch
import uuid

@pytest.mark.integration
def test_elasticsearch_connectivity():
    """
    测试本地 Elasticsearch 是否可用。
    作为 Medium Test，允许连接本地 Docker，但如果服务未启动，用例将优雅失败。
    """
    es = Elasticsearch('http://localhost:9200')
    
    try:
        is_connected = es.ping()
        if not is_connected:
            pytest.skip("Elasticsearch 未在 localhost:9200 运行，跳过该集成测试。")
            
        test_index = "test_metallurgy_chunks_" + uuid.uuid4().hex[:6]
        
        # 简单验证 exists API 不会报错
        exists = es.indices.exists(index=test_index)
        assert exists is False, "新生成的随机索引不应该存在"
        
    except Exception as e:
        pytest.skip(f"无法连接到本地 Elasticsearch，跳过测试。详细错误: {e}")
