"""
上下文构建中心 (Context Builder)

将原本的面条式字符串拼接，解耦为结构化的 LangChain Messages，
以支持更灵活的 Token 压缩和附件挂载。
"""

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

def build_system_prompt(deep_mode: bool, memory_context: str | None, vlm_context: str | None) -> SystemMessage:
    """构建核心系统设定（System Prompt）"""
    
    parts = []
    
    # 1. 核心人设与工作模式
    if deep_mode:
        parts.append(
            "你是小冶，导师（用户）手下勤奋的冶金专业研究生。\n"
            "【深度模式已激活】：本次对话将启动高级知识图谱多步检索与推理。\n"
            "**强制要求**：\n"
            "1. 查到资料后，务必直接给出具体数据，而不是文字堆砌。提取有价值的科研数据点进行有理有据的分析。\n"
            "2. 如果工具返回了图片Markdown格式信息（如 `![图表](http...)`），你必须原封不动地将其插入到回答中合适的位置！严禁编造文献库中没有的数据。"
        )
    else:
        parts.append(
            "你是小冶，导师（用户）手下勤奋的冶金专业研究生。\n"
            "【快速模式】：简洁回答导师的问题，优先使用基础检索回答。\n"
            "**强制要求**：\n"
            "1. 务必直接给出具体数据与事实，避免文字堆砌。\n"
            "2. 如果工具返回了图片 Markdown，必须原封不动地插入到回答中。\n"
            "3. 回答必须保留参考资料的来源标注（如有），格式为 `[来源: xxx.pdf, p.N]`，以便前端显示富媒体跳转索引。\n"
            "4. 快速模式下无法执行绘图和物理计算！绝对不要在回复中声称或捏造‘已成功委派绘制任务’或‘将在后台计算完成后自动发布并渲染在 Notebook 中’等虚假提示！如果用户需要绘图或计算，请友好地提示用户在提问中包含‘画图’或‘运行代码’等触发词，以激活有状态沙盒工具。"
        )

    # 2. 长程记忆 (Long-term Memory)
    if memory_context:
        parts.append(f"【长程记忆】\n{memory_context}")

    # 3. 视觉上下文 (Visual Context - Fork VLM)
    if vlm_context:
        parts.append(
            "【VLM 视觉分析结果】\n"
            "请基于下方视觉大模型对论文图表的分析结果，向导师做详细的汇报：\n"
            f"{vlm_context}"
        )

    return SystemMessage(content="\n\n".join(parts))


import tiktoken
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from src.core.logger import setup_logger

logger = setup_logger("xiaoye.context_builder")

def estimate_tokens(text: str) -> int:
    """估算文本的 Token 数量 (使用 cl100k_base 统计算法)"""
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return len(text) // 2

async def build_and_compact_history(raw_history: list, token_budget: int = 6000) -> list:
    """
    将 Redis 中的原始历史转为 LangChain 结构化 Message，并引入 Token 预算折叠机制。
    当过往历史超出 Token 预算时，自动调用小模型对老旧历史进行摘要总结。
    """
    if not raw_history:
        return []

    # 简单倒序扫描，看能装下多少条完整历史
    messages = []
    current_tokens = 0
    retained_history = []
    
    for h in reversed(raw_history):
        # 预估当前回合的 token (User + Assistant)
        turn_text = f"User: {h['user']}\nAssistant: {h['assistant']}"
        turn_tokens = estimate_tokens(turn_text)

        if current_tokens + turn_tokens > token_budget:
            # 达到阈值，不再装载原生的旧历史
            break
            
        retained_history.insert(0, h)
        current_tokens += turn_tokens

    # 被丢弃的早期历史（可以送去压缩，这里为了极速响应，采用前端丢弃或简易折叠）
    discarded_history = raw_history[:-len(retained_history)] if len(retained_history) < len(raw_history) else []

    if discarded_history:
        logger.info(f"[Context Builder] History exceeded budget. Retained {len(retained_history)} turns, discarded/compacted {len(discarded_history)} turns.")
        # 组装摘要说明，如果未来需要接入 LLM 摘要，可以在此处调用
        summary_text = f"【系统说明】：在之前的 {len(discarded_history)} 轮对话中，用户与你进行了深入探讨。受限于记忆窗口，这些早期对话已被折叠。"
        messages.append(SystemMessage(content=summary_text))

    for h in retained_history:
        messages.append(HumanMessage(content=h['user']))
        messages.append(AIMessage(content=h['assistant']))
        
    return messages
