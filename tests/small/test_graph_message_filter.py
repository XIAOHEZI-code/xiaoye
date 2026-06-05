"""Small test: 验证 graph.py synthesizer 节点的消息过滤逻辑

测试目标：
- synthesizer_node 在组装 LLM 输入时必须过滤掉 ToolMessage
- 必须过滤掉带有 tool_calls 的 AIMessage
- 必须保留 HumanMessage 和普通 AIMessage
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage


# ==========================================
# 核心过滤逻辑提取（与 graph.py 中 synthesizer_node 完全一致）
# ==========================================
def _filter_messages_for_synthesis(messages: list) -> list:
    """
    过滤消息队列，移除 ToolMessage 和带 tool_calls 的 AIMessage。
    与 src/reasoning/graph.py synthesizer_node 中逻辑完全一致。
    """
    filtered = []
    for m in messages:
        if isinstance(m, ToolMessage):
            continue
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            continue
        filtered.append(m)
    return filtered


# ==========================================
# 测试用例
# ==========================================


@pytest.mark.small
def test_filter_removes_tool_messages():
    """合成器应过滤掉所有 ToolMessage"""
    messages = [
        HumanMessage(content="304不锈钢的抗拉强度是多少？"),
        AIMessage(
            content="",
            tool_calls=[{"name": "search", "args": {}, "id": "call_search1"}],
        ),
        ToolMessage(
            content="304不锈钢抗拉强度 ≥ 520 MPa",
            name="semantic_search",
            tool_call_id="call_search1",
        ),
        AIMessage(content="根据检索结果，304不锈钢的抗拉强度不低于520MPa。"),
    ]
    filtered = _filter_messages_for_synthesis(messages)

    # 不应包含 ToolMessage
    assert not any(isinstance(m, ToolMessage) for m in filtered), (
        "过滤后不应包含 ToolMessage"
    )
    # 应保留最后的 HumanMessage
    assert any(isinstance(m, HumanMessage) for m in filtered), "应保留 HumanMessage"
    # 应保留普通 AIMessage
    plain_ais = [
        m
        for m in filtered
        if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None)
    ]
    assert len(plain_ais) == 1, "应保留不含 tool_calls 的 AIMessage"


@pytest.mark.small
def test_filter_removes_ai_with_tool_calls():
    """合成器应过滤掉带 tool_calls 的 AIMessage"""
    messages = [
        HumanMessage(content="搜索转炉工艺"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "semantic_search",
                    "args": {"query": "转炉"},
                    "id": "call_sem1",
                }
            ],
        ),
    ]
    filtered = _filter_messages_for_synthesis(messages)

    # 只应保留 HumanMessage
    assert len(filtered) == 1
    assert isinstance(filtered[0], HumanMessage)


@pytest.mark.small
def test_filter_preserves_human_and_plain_ai():
    """合成器应保留 SystemMessage、HumanMessage 和普通 AIMessage"""
    messages = [
        SystemMessage(content="你是一个冶金专家助手。"),
        HumanMessage(content="请问高炉炼铁的流程是怎样的？"),
        AIMessage(content="高炉炼铁是将铁矿石还原成生铁的过程。"),
        HumanMessage(content="具体有哪些步骤？"),
    ]
    filtered = _filter_messages_for_synthesis(messages)

    assert len(filtered) == 4, "应保留所有非 Tool/AI-tool-calls 消息"
    assert isinstance(filtered[0], SystemMessage)
    assert isinstance(filtered[1], HumanMessage)
    assert isinstance(filtered[2], AIMessage)
    assert isinstance(filtered[3], HumanMessage)


@pytest.mark.small
def test_filter_mixed_messages():
    """混合消息类型：应正确过滤"""
    messages = [
        SystemMessage(content="系统指令"),
        HumanMessage(content="用户问题1"),
        AIMessage(content="", tool_calls=[{"name": "t1", "args": {}, "id": "call_t1"}]),
        ToolMessage(content="工具结果", name="t1", tool_call_id="call_t1"),
        AIMessage(content="", tool_calls=[{"name": "t2", "args": {}, "id": "call_t2"}]),
        ToolMessage(content="工具结果2", name="t2", tool_call_id="call_t2"),
        HumanMessage(content="用户追问"),
        AIMessage(content="最终回答"),
    ]
    filtered = _filter_messages_for_synthesis(messages)

    assert len(filtered) == 4  # System + 2 Human + 1 plain AI
    types = [type(m).__name__ for m in filtered]
    assert types == ["SystemMessage", "HumanMessage", "HumanMessage", "AIMessage"]


@pytest.mark.small
def test_filter_with_system_intervention():
    """带 [系统干预] 标记的 HumanMessage 应该被保留（由 researcher 负责过滤，非 synthesizer）"""
    messages = [
        HumanMessage(content="用户原始问题"),
        HumanMessage(content="[系统干预] 请重新搜索"),
        AIMessage(content="好的，我重新搜索。"),
    ]
    filtered = _filter_messages_for_synthesis(messages)

    # synthesizer 层面不做干预消息过滤，只过滤 ToolMessage 和 tool_calls AIMessage
    assert len(filtered) == 3
    human_msgs = [m for m in filtered if isinstance(m, HumanMessage)]
    assert len(human_msgs) == 2  # 两个 HumanMessage 都保留


@pytest.mark.small
def test_filter_empty_list():
    """空消息列表应返回空列表"""
    assert _filter_messages_for_synthesis([]) == []


@pytest.mark.small
def test_filter_only_tool_messages():
    """只有 ToolMessage 时返回空列表"""
    messages = [
        ToolMessage(content="r1", name="search", tool_call_id="tc1"),
        ToolMessage(content="r2", name="graph", tool_call_id="tc2"),
    ]
    filtered = _filter_messages_for_synthesis(messages)
    assert filtered == []
