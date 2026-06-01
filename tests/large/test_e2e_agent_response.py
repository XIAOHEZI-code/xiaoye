"""大型端到端测试 (Large E2E)：验证 LangGraph 全状态机流转。

⚠️ 此测试会消耗真实 LLM Token，默认跳过。
   如需运行，请设置环境变量: RUN_E2E=true
"""

import os
import pytest
from langchain_core.messages import HumanMessage
from src.reasoning.graph import create_worker_graph


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.skipif(
    os.getenv("RUN_E2E", "").lower() != "true",
    reason="E2E tests consume real LLM tokens. Set RUN_E2E=true to enable.",
)
async def test_agent_response_pipeline():
    """
    大型端到端测试 (Large E2E Test)：
    真实调用 LLM 和 Agent 工具链，验证整个 LangGraph 状态机的流转是否通畅。
    【注意】：
    1. 会消耗真实的 Token 和执行时间。
    2. 使用了极简的 Prompt，避免过度消耗资源。
    """
    graph = create_worker_graph()

    # 遵循我们之前的 Bugfix：用户的原始输入应当被识别为 HumanMessage
    query = "你好，请用不超过20个字简要说明一下什么是304不锈钢。"

    state = {
        "messages": [HumanMessage(content=query)],
        "step_satisfied": False,
        "past_steps": [],
        "ready_to_synthesize": False,
        "loop_count": 0,
        "reasoning": [],
        "thinking_config": {"type": "disabled"},
        "task_id": "test_agent_e2e_123",
    }

    final_answer = ""
    tool_called = False

    # 模拟真实前端的流式调用
    try:
        async for event in graph.astream_events(
            state, version="v2", config={"recursion_limit": 10}
        ):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if hasattr(chunk, "content") and chunk.content:
                    final_answer += chunk.content
            elif kind == "on_tool_start":
                tool_called = True
    except Exception as e:
        pytest.fail(f"Agent 图流转中途崩溃抛出异常: {e}")

    # 断言：必须成功跑完并给出回答
    assert len(final_answer) > 5, f"Agent 回答过短或未作答: {final_answer}"

    # 由于该问题极其简单，通常不需要调用工具，但如果有也不算错
    # 此处重点验证 Graph 能够安全地从 start -> researcher -> ... -> end
