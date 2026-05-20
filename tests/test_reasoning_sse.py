import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_run_worker_pipeline_streaming():
    """
    测试 run_worker_pipeline 是否能正确调用 graph.astream_events 并将结果推送到 SSE 频道。

    [M6] 更新：evaluator 节点已被移除，graph 路由逻辑简化为：
      Researcher → Tools → Compactor → Researcher (循环)，直至 Researcher 不再产生 tool_calls。

    本测试通过 mock create_worker_graph 来模拟以下流程：
      Researcher stream + tool_call → Tools → Synthesizer → END
    """
    from src.reasoning.graph import run_worker_pipeline

    # 模拟 get_sse_channel
    mock_sse = AsyncMock()

    # 构建一个假的 event 生成器，反映新的 graph 路由
    async def mock_events_generator(*args, **kwargs):
        # Phase 1: Researcher 流式输出文本并调用工具
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": MagicMock(content="Hello ")},
        }
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": MagicMock(content="World!")},
        }

        # Researcher 产生了 tool_calls → graph 路由到 tools
        yield {"event": "on_tool_start", "name": "search_metallurgy_text"}

        # Researcher 不再产生 tool_calls → graph 路由到 synthesizer
        # Synthesizer 节点生成最终回答后 graph 结束（synthesizer → END）
        # 注：synthesizer 的 chain_end 事件会被 run_worker_pipeline 忽略
        yield {
            "event": "on_chain_end",
            "name": "synthesizer",
            "data": {
                "output": {
                    "messages": [
                        MagicMock(
                            content="Final synthesized answer from collected data"
                        )
                    ]
                }
            },
        }

    mock_graph = MagicMock()
    mock_graph.astream_events = mock_events_generator

    with (
        patch("src.reasoning.graph.create_worker_graph", return_value=mock_graph),
        patch("src.delivery.sse_channel.get_sse_channel", return_value=mock_sse),
    ):
        payload = {"task_description": "Test Task"}
        task_id = "test-123"

        # 运行
        result = await run_worker_pipeline(payload, task_id)

        # 验证结果收集（仅来自 on_chat_model_stream 事件）
        assert result == "Hello World!"

        # 验证 SSE 推送调用（3 次：2 chunks + 1 tool_start）
        # 注意：synthesizer 的 chain_end 不会触发 SSE 推送
        assert mock_sse.async_publish_chat_patch.call_count == 3

        calls = mock_sse.async_publish_chat_patch.call_args_list
        # chunk 1: Researcher 流式输出
        assert calls[0][0][0] == task_id
        assert calls[0][0][1] == "Hello "
        # chunk 2: Researcher 流式输出
        assert calls[1][0][0] == task_id
        assert calls[1][0][1] == "World!"
        # tool_start: 工具调用通知
        assert calls[2][0][0] == task_id
        assert "search_metallurgy_text" in calls[2][0][1]
        assert "正在调用工具检索" in calls[2][0][1]
