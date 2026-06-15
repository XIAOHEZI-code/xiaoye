"""大型端到端测试 (Large E2E)：验证混合文献检索与知识图谱关系追踪的协同推理能力。

测试目标：
1. 验证 ReAct Agent 能够根据任务意图，主动且正确地调度两类异构检索工具：
   - 混合文献检索工具 (search_metallurgy_text)
   - 知识图谱单跳/多跳追踪工具 (search_metallurgy_graph_relations / trace_metallurgy_impact_path)
2. 验证智能体能够融合知识图谱的结构化关系链与文献库的非结构化数据点，生成高质量的学术答复。

⚠️ 此测试会消耗真实 LLM Token，默认跳过。
   如需运行，请设置环境变量: RUN_E2E=true
"""

import os
import pytest
import asyncio
from langchain_core.messages import HumanMessage
from src.reasoning.graph import run_worker_pipeline


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.skipif(
    os.getenv("RUN_E2E", "").lower() != "true",
    reason="E2E tests consume real LLM tokens. Set RUN_E2E=true to enable.",
)
async def test_e2e_hybrid_and_graph_search_flow():
    # 1. 构建综合检索任务：要求结合工艺路径（图谱关系）和具体疲劳性能数值（文献）进行因果分析
    task_id = "test_e2e_hybrid_graph_flow_123"
    query = (
        "请分析 304/45钢复合螺栓 的生产工艺对其疲劳性能的影响。"
        "请先使用知识图谱工具追踪工艺-性能之间的因果关联路径，"
        "并结合文献检索工具查明具体的拉伸疲劳试验数据点进行定量支撑。"
    )

    payload = {
        "messages": [HumanMessage(content=query)],
        "deep_mode": True  # 启用深度思考模式 (qwen-max + thinking) 以确保多工具决策与规划精度
    }

    # 2. 模拟前端流式调用，拦截图的事件以监控工具调用情况
    from src.reasoning.graph import create_worker_graph
    graph = create_worker_graph(deep_mode=True)

    state = {
        "messages": [HumanMessage(content=query)],
        "step_satisfied": False,
        "past_steps": [],
        "ready_to_synthesize": False,
        "loop_count": 0,
        "reasoning": [],
        "thinking_config": {"type": "adaptive", "budget": 32000},
        "task_id": task_id,
    }

    called_tools = set()
    final_answer = ""

    try:
        # 追踪 LangGraph 事件流
        async for event in graph.astream_events(
            state, version="v2", config={"recursion_limit": 15}
        ):
            kind = event["event"]
            if kind == "on_tool_start":
                tool_name = event["name"]
                print(f"[Test E2E] Intercepted tool call: {tool_name}")
                called_tools.add(tool_name)
            elif kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if hasattr(chunk, "content") and chunk.content:
                    final_answer += chunk.content
    except Exception as err:
        pytest.fail(f"Graph execution crashed: {err}")

    # 3. 断言验证
    # 验证要求 1: 必须调用了混合文本检索工具
    assert "search_metallurgy_text" in called_tools, (
        f"Agent 没有调用文本混合检索工具。已调用工具集: {called_tools}"
    )

    # 验证要求 2: 必须调用了图谱关系查询工具中的至少一种
    graph_tools = {"search_metallurgy_graph_relations", "trace_metallurgy_impact_path"}
    assert called_tools.intersection(graph_tools), (
        f"Agent 没有调用任何知识图谱工具。已调用工具集: {called_tools}"
    )

    # 验证要求 3: 最终答复中应包含文献里的真实拉伸试验数据（578 MPa 或 593 MPa）
    assert "578" in final_answer or "593" in final_answer, (
        f"最终答复中未能提取并融合文献库中的具体定量数据。答复内容：{final_answer}"
    )

    # 验证要求 4: 最终答复中应包含图谱关系相关的节点或工艺词汇
    assert "滚丝" in final_answer or "热轧" in final_answer, (
        f"最终答复中未能融合知识图谱中的工艺实体节点信息。答复内容：{final_answer}"
    )

    print("[Test E2E] Hybrid & Knowledge Graph Search E2E Flow successfully verified!")
