"""
Test suite for M5 Pipeline Decoupling.
This verifies that the four pipelines (Ingestion, Tooling, Reasoning, Delivery)
can be imported and initialized without circular dependency errors or runtime crashes.
"""

import pytest
import os
import json
from unittest.mock import patch, MagicMock

# ====================================================================
#  1. Tooling Pipeline Tests (P2)
# ====================================================================
def test_tooling_registry_initialization():
    """验证 ToolRegistry 单例机制与渐进式披露是否正常"""
    from src.tooling.registry import get_tool_registry, DefaultToolRegistry
    
    registry = get_tool_registry()
    assert isinstance(registry, DefaultToolRegistry)
    
    # 获取全量工具 (应该触发 lazy import)
    all_tools = registry.get_all_tools()
    assert all_tools is not None
    assert len(all_tools) > 0
    
    # 验证 always_loaded_tools 是否能获取
    always_loaded = registry.get_always_loaded_tools()
    assert always_loaded is not None
    
    # 验证是否包含核心的搜索工具
    tool_names = [t.name for t in always_loaded]
    assert "search_metallurgy_text" in tool_names
    assert "search_available_tools" in tool_names

def test_tool_loader():
    """验证 ToolLoader 探测接口"""
    from src.tooling.loader import ToolLoader
    
    loader = ToolLoader()
    tools = loader.probe_environment("我需要进行热力学相图计算")
    assert tools is not None
    assert len(tools) > 0


# ====================================================================
#  2. Reasoning Pipeline Tests (P3)
# ====================================================================
def test_reasoning_graph_compilation():
    """验证 Worker Graph 能否成功 Compile（不抛出 import 或依赖错误）"""
    from src.reasoning.graph import create_worker_graph
    
    # 设置 Mock 防止实际连接 Qwen API 报错
    with patch("src.reasoning.graph.ChatOpenAI"):
        graph = create_worker_graph()
        assert graph is not None
        # 验证 graph 具有基础的 nodes
        nodes = graph.nodes
        assert "researcher" in nodes
        assert "tools" in nodes
        assert "compactor" in nodes
        assert "evaluator" in nodes

def test_swarm_coordinator_initialization():
    """验证 Swarm Coordinator 调度器初始化"""
    from src.reasoning.coordinator import SwarmCoordinator
    
    # 假冒 Redis 连接避免网络报错
    with patch("src.reasoning.task_board.redis.from_url"):
        coordinator = SwarmCoordinator(session_id="test_m5_session")
        assert coordinator.board.team_name == "test_m5_session"


# ====================================================================
#  3. Delivery Pipeline Tests (P4)
# ====================================================================
def test_sse_channel():
    """验证 SSEChannel 统一推送层"""
    from src.delivery.sse_channel import get_sse_channel
    
    channel = get_sse_channel()
    assert channel.channel_name == "xiaoye_sse"
    
    # 测试发布方法不会抛错 (mock Redis)
    with patch("redis.from_url") as mock_redis:
        mock_client = MagicMock()
        mock_redis.return_value = mock_client
        
        channel.publish("test_event", {"msg": "hello"})
        
        # 验证是否以 JSON 格式 publish
        mock_client.publish.assert_called_once()
        args = mock_client.publish.call_args[0]
        assert args[0] == "xiaoye_sse"
        payload = json.loads(args[1])
        assert payload["type"] == "test_event"
        assert payload["msg"] == "hello"

def test_session_manager():
    """验证 SessionManager 基本配置"""
    from src.delivery.session import SessionManager
    
    sm = SessionManager()
    assert sm.redis_url is not None


# ====================================================================
#  4. Ingestion Pipeline Tests (P1)
# ====================================================================
def test_dedup_checker():
    """验证 Dedup Checker 纯净哈希函数"""
    from src.ingestion.dedup import DedupChecker
    
    test_bytes = b"hello world metallurgy"
    file_hash = DedupChecker.compute_hash(test_bytes)
    assert file_hash == "28f68854f9c6876cfed4e7017b68180d0c6ea7a8333ad0ace3c59df16059ef75"
