# 上下文构建器单元测试（small tests）
import pytest

# ==========================================
# S1: estimate_tokens 测试
# ==========================================


@pytest.mark.small
def test_estimate_tokens_empty_string():
    """空字符串应返回 0 Token"""
    from src.delivery.context_builder import estimate_tokens

    assert estimate_tokens("") == 0


@pytest.mark.small
def test_estimate_tokens_english():
    """英文文本应正确计数 Token (cl100k_base)"""
    from src.delivery.context_builder import estimate_tokens

    # "Hello world" -> cl100k_base 编码为 2 tokens
    tokens = estimate_tokens("Hello world")
    assert tokens >= 1, f"英文文本 Token 计数异常: {tokens}"


@pytest.mark.small
def test_estimate_tokens_chinese():
    """中文文本 Token 计数应合理（中文单字约 1.5-2 tokens/cl100k）"""
    from src.delivery.context_builder import estimate_tokens

    tokens = estimate_tokens("这是一段中文测试文本")
    assert tokens >= 3, f"中文文本 Token 计数异常: {tokens}"


@pytest.mark.small
def test_estimate_tokens_long_text():
    """长文本 Token 应随字符数线性增长"""
    from src.delivery.context_builder import estimate_tokens

    short = estimate_tokens("hello")
    long = estimate_tokens("hello " * 100)
    assert long > short * 10, "长文本 Token 应该明显多于短文本"


# ==========================================
# S2: build_and_compact_history 测试
# ==========================================


@pytest.mark.asyncio
@pytest.mark.small
async def test_build_and_compact_history_empty():
    """空历史列表应返回空 Message 列表"""
    from src.delivery.context_builder import build_and_compact_history

    result = await build_and_compact_history([])
    assert result == []


@pytest.mark.asyncio
@pytest.mark.small
async def test_build_and_compact_history_within_budget():
    """历史在 Token 预算内，应全部保留"""
    from src.delivery.context_builder import build_and_compact_history
    from langchain_core.messages import HumanMessage, AIMessage

    history = [
        {"user": "什么是304不锈钢？", "assistant": "304不锈钢是一种奥氏体不锈钢..."},
        {
            "user": "它的耐腐蚀性如何？",
            "assistant": "304不锈钢在氧化性酸中具有良好的耐腐蚀性...",
        },
    ]
    result = await build_and_compact_history(history, token_budget=6000)

    # 2 轮历史 → 2 HumanMessage + 2 AIMessage = 4 messages
    assert len(result) == 4
    assert isinstance(result[0], HumanMessage)
    assert isinstance(result[1], AIMessage)
    assert "304不锈钢" in result[0].content


@pytest.mark.asyncio
@pytest.mark.small
async def test_build_and_compact_history_exceeds_budget():
    """Token 预算不足时，应截断旧历史并注入摘要"""
    from src.delivery.context_builder import build_and_compact_history
    from langchain_core.messages import SystemMessage

    # 构造大量历史，确保超出预算
    history = []
    for i in range(50):
        history.append(
            {
                "user": f"第{i}个问题：" + "冶金工艺参数如何优化？" * 10,
                "assistant": f"第{i}个回答："
                + "根据文献记载，冶金工艺参数需要综合考虑..." * 10,
            }
        )

    result = await build_and_compact_history(history, token_budget=500)

    # 应该被截断，第一条应为摘要 SystemMessage
    assert len(result) > 0, "不应返回空列表"
    assert isinstance(result[0], SystemMessage), "超出预算时首条应为系统摘要"
    assert "已被折叠" in result[0].content, "摘要应包含折叠提示"


@pytest.mark.asyncio
@pytest.mark.small
async def test_build_and_compact_history_preserves_order():
    """保留的历史应维持原始时间顺序 (先发生的在前)"""
    from src.delivery.context_builder import build_and_compact_history

    history = [
        {"user": "第一个问题", "assistant": "第一个回答"},
        {"user": "第二个问题", "assistant": "第二个回答"},
    ]
    result = await build_and_compact_history(history, token_budget=6000)

    messages = result  # [Human, AI, Human, AI]
    assert "第一个问题" in messages[0].content
    assert "第二个回答" in messages[3].content


# ==========================================
# S3: build_system_prompt 测试
# ==========================================


@pytest.mark.small
def test_build_system_prompt_fast_mode():
    """测试快速模式下的系统设定组装"""
    from src.delivery.context_builder import build_system_prompt

    msg = build_system_prompt(
        deep_mode=False, 
        memory_context=None, 
        vlm_context=None
    )
    content = msg.content
    assert "优先使用基础检索回答" in content
    assert "【深度模式已激活】" not in content


@pytest.mark.small
def test_build_system_prompt_deep_mode():
    """测试深度模式下的系统设定组装"""
    from src.delivery.context_builder import build_system_prompt

    msg = build_system_prompt(
        deep_mode=True, 
        memory_context=None, 
        vlm_context=None
    )
    content = msg.content
    assert "【深度模式已激活】" in content
    assert "优先使用基础检索回答" not in content


@pytest.mark.small
def test_build_system_prompt_with_memory_and_vlm():
    """测试带有长程记忆和视觉分析结果的设定组装"""
    from src.delivery.context_builder import build_system_prompt

    msg = build_system_prompt(
        deep_mode=False,
        memory_context="用户上次提问了关于转炉的问题。",
        vlm_context="图片显示了一个包含马氏体的显微组织图。"
    )
    content = msg.content
    assert "【长程记忆】\n用户上次提问了关于转炉的问题。" in content
    assert "【VLM 视觉分析结果】" in content
    assert "图片显示了一个包含马氏体的显微组织图。" in content
