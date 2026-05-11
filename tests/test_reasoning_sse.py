import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_run_worker_pipeline_streaming():
    """
    测试 run_worker_pipeline 是否能正确调用 graph.astream_events 并将结果推送到 SSE 频道。
    """
    from src.reasoning.graph import run_worker_pipeline

    # 模拟 get_sse_channel
    mock_sse = AsyncMock()
    
    # 构建一个假的 event 生成器
    async def mock_events_generator(*args, **kwargs):
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Hello ")}}
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="World!")}}
        yield {"event": "on_tool_start", "name": "search_metallurgy_text"}
        yield {"event": "on_chain_end", "name": "evaluator", "data": {
            "output": {
                "messages": [MagicMock(content="EVALUATOR_FEEDBACK: Needs more data")]
            }
        }}

    mock_graph = MagicMock()
    mock_graph.astream_events = mock_events_generator

    with patch("src.reasoning.graph.create_worker_graph", return_value=mock_graph), \
         patch("src.delivery.sse_channel.get_sse_channel", return_value=mock_sse):
        
        payload = {"task_description": "Test Task"}
        task_id = "test-123"
        
        # 运行
        result = await run_worker_pipeline(payload, task_id)
        
        # 验证结果收集
        assert result == "Hello World!"
        
        # 验证 SSE 推送调用
        # chunk.content: Hello , World!
        # tool_start: search_metallurgy_text
        # evaluator feedback: Needs more data
        assert mock_sse.async_publish_chat_patch.call_count == 4
        
        calls = mock_sse.async_publish_chat_patch.call_args_list
        # chunk 1
        assert calls[0][0][0] == task_id
        assert calls[0][0][1] == "Hello "
        # chunk 2
        assert calls[1][0][0] == task_id
        assert calls[1][0][1] == "World!"
        # tool_start
        assert calls[2][0][0] == task_id
        assert "search_metallurgy_text" in calls[2][0][1]
        assert "正在调用工具检索" in calls[2][0][1]
        # evaluator
        assert calls[3][0][0] == task_id
        assert "数据不够充分" in calls[3][0][1]
        assert "Needs more data" in calls[3][0][1]
