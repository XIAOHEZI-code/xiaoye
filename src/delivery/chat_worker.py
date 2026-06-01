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
from src.delivery.memory import (
    load_preload_context,
    extract_and_save_memory,
    init_global_memory,
)
from src.api.askuser_routes import trigger_ask_user, wait_for_user_reply


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


async def dispatch_chat_worker(
    task_id: str,
    message: str,
    document_id: str | None,
    history: list,
    deep_mode: bool = False,
):
    """
    主对话 Worker。接入文献检索技能 (search_metallurgy_text) 并流式推送回复。

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

        # ── Step 2: 组装任务描述 (Context Componentization) ──────────────────────────────
        from src.delivery.context_builder import build_system_prompt, build_and_compact_history
        from langchain_core.messages import HumanMessage

        system_message = build_system_prompt(deep_mode, memory_context, vlm_context)
        history_messages = await build_and_compact_history(history)
        current_message = HumanMessage(content=message)

        # 组合为完整的初始 Message 队列
        messages_queue = [system_message] + history_messages + [current_message]

        # ── Step 3: 调用 Reasoning 智能体管线 (取代原硬编码) ────────────────────
        from src.reasoning.graph import run_worker_pipeline

        payload = {"messages": messages_queue, "deep_mode": deep_mode}

        # 运行图并自动获取 SSE 推送
        full_response = await run_worker_pipeline(payload, task_id)

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

        print(f"[ChatWorker] task={task_id} completed via Reasoning pipeline.")
