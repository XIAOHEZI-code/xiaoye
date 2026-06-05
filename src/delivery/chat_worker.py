"""
Chat Worker — 主对话 Agent 流水线
架构说明：
  1. 如果有 VLM 上下文（来自 Fork Agent 的 PDF 区域分析）→ 上下文增强对话
  2. 如果没有 VLM 上下文 → 先调用 search_metallurgy_text 技能检索文献，再综合回答
  3. 结果通过 Redis Pub/Sub → SSE 流式推给前端
  4. 保存完整回复到 Redis，供后续追问使用

遵循 HANDOVER_PROMPT.md 原则：
  - 不使用同步阻塞；异步流式优先
  - 技能调用通过 SkillLoader 而非硬编码
  - 对话历史保留最近 10 轮
"""

import json
import os
import redis.asyncio as redis
from src.core.config import settings
from src.core.logger import setup_logger
from src.delivery.memory import (
    load_preload_context,
    extract_and_save_memory,
    init_global_memory,
)
from src.api.askuser_routes import trigger_ask_user, wait_for_user_reply

logger = setup_logger("xiaoye.chat")


def _clear_proxy():
    """清除代理环境变量，确保直连 Aliyun Dashscope"""
    for key in [
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    ]:
        os.environ.pop(key, None)
    os.environ["OPENAI_API_KEY"] = settings.QWEN_API_KEY
    os.environ["OPENAI_API_BASE"] = settings.QWEN_BASE_URL


def should_use_react_agent(message: str) -> bool:
    """判断提问是否需要调用复杂的 Agent/ReAct 工具循环"""
    keywords = [
        "python", "代码", "运行", "计算", "图谱", "neo4j", "关系", "因果", "影响", "trace", 
        "sandbox", "沙盒", "仿真", "模拟", "绘制", "曲线", "绘图", "画图", "图表", "图像", 
        "图片", "可视化", "plot", "chart", "curve",
        "绘画", "作图", "制图", "折线图", "柱状图", "条形图", "饼图", "散点图", "画个", "画一下", "画出"
    ]
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in keywords)


def is_chitchat(message: str) -> bool:
    """判断提问是否为简单的日常对话/寒暄"""
    keywords = ["你好", "hello", "hi", "是谁", "主子", "名字", "自我介绍", "谢谢", "再见", "再会", "拜拜"]
    msg_lower = message.lower()
    return len(message) < 15 and any(kw in msg_lower for kw in keywords)


async def dispatch_chat_worker(
    task_id: str,
    message: str,
    document_id: str | None,
    history: list,
    deep_mode: bool = False,
):
    """
    主对话 Worker。支持文献检索智能路由 (分流闲聊/直接 RAG/多步 ReAct) 并流式推送回复。

    Args:
        task_id:     会话 ID（用于 Redis key 隔离）
        message:     用户消息
        document_id: 当前关联的文档 ID（可为 None → 全库搜索）
        history:     对话历史列表 [{user: str, assistant: str}]
    """
    _clear_proxy()

    # 确保全局记忆已初始化
    init_global_memory()

    redis_client = redis.from_url(settings.CELERY_BROKER_URL)

    async with redis_client as r:
        from src.delivery.sse_channel import get_sse_channel

        sse = get_sse_channel()

        # ── Step 0: 从硬盘态记忆加载历史上下文 ────────────────────────────────
        memory_context = load_preload_context(task_id, document_id)

        # ── Step 1: 查询 Redis 是否已有 VLM 分析结果 ──────────────────────────
        vlm_key = f"xiaoye:chat:{task_id}"
        raw_vlm = await r.get(vlm_key)
        vlm_context = raw_vlm.decode("utf-8") if raw_vlm else None

        # ── Step 2: 组装任务描述 ─────────────────────────────────────────────
        from src.delivery.context_builder import build_system_prompt, build_and_compact_history
        from langchain_core.messages import HumanMessage

        system_message = build_system_prompt(deep_mode, memory_context, vlm_context)
        
        # 快速模式历史 Token 窗口限制为 2000，深度模式限制为 6000
        history_budget = 6000 if deep_mode else 2000
        history_messages = await build_and_compact_history(history, token_budget=history_budget)
        current_message = HumanMessage(content=message)

        # 组合为完整的初始 Message 队列
        messages_queue = [system_message] + history_messages + [current_message]

        # ── Step 3: 智能路由分发 (分流直连与多步 ReAct) ─────────────────────────
        use_agent = deep_mode or should_use_react_agent(message)

        if use_agent:
            # 走有状态多步 ReAct 循环通路
            from src.reasoning.graph import run_worker_pipeline
            payload = {"messages": messages_queue, "deep_mode": deep_mode}
            
            logger.info(f"[{task_id}][qwen-max][执行: ReAct Agent Pipeline][输入: {message[:50]}...]")
            full_response = await run_worker_pipeline(payload, task_id)
            logger.info(f"[{task_id}][qwen-max][执行: ReAct Agent Pipeline][结果: 长度 {len(full_response)} 字符]")
        else:
            # 走快速直连流式通路
            from langchain_openai import ChatOpenAI
            import asyncio

            if is_chitchat(message):
                logger.info(f"[{task_id}][qwen-turbo][执行: Chitchat 直连][输入: {message[:50]}...]")
            else:
                logger.info(f"[{task_id}][qwen-turbo][执行: Direct RAG 检索][输入: {message[:50]}...]")
                # 异步检索 ES
                from src.tooling.definitions import search_metallurgy_text
                search_result = await asyncio.to_thread(search_metallurgy_text, message)
                if search_result and "No relevant text documents found." not in search_result:
                    # 追加文献段落到系统 prompt
                    context_msg = f"\n\n【搜索召回的参考资料】：\n{search_result}"
                    system_message.content += context_msg

            # 初始化 Qwen 快速生成模型
            llm = ChatOpenAI(
                model="qwen-turbo",
                api_key=settings.QWEN_API_KEY,
                base_url=settings.QWEN_BASE_URL,
                temperature=0.2,
                streaming=True
            )

            # 流式生成并通过 SSE 发送
            full_response_parts = []
            async for chunk in llm.astream(messages_queue):
                content = chunk.content
                if content:
                    full_response_parts.append(content)
                    await sse.async_publish_chat_patch(task_id=task_id, patch=content)
            full_response = "".join(full_response_parts)
            logger.info(f"[{task_id}][qwen-turbo][执行: Direct RAG/Chitchat][结果: 长度 {len(full_response)} 字符]")

        # ── Step 4: 更新对话历史 + 结束信号 ───────────────────────────────────
        history_key = f"xiaoye:chat:{task_id}:history"
        history.append({"user": message, "assistant": full_response})
        if len(history) > 10:
            history = history[-10:]
        await r.set(history_key, json.dumps(history, ensure_ascii=False))

        # ── Step 5: 持久化记忆到硬盘 ──────────────────────────────────────────
        try:
            summary = f"用户问: {message[:200]}\n小冶答: {full_response[:500]}"
            extract_and_save_memory(
                task_id=task_id,
                document_id=document_id,
                conversation_summary=summary,
            )
        except Exception as mem_err:
            print(f"[ChatWorker] Memory save failed (non-fatal): {mem_err}")

        await sse.async_publish_chat_patch(task_id=task_id, patch="\n\n---\n")

        print(f"[ChatWorker] task={task_id} completed via Routing pipeline.")
