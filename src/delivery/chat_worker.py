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

        # ── Step 2: 组装任务描述 (Task Description) ──────────────────────────────
        # 记忆前缀（注入到所有模式）
        memory_prefix = (
            f"\n\n【长程记忆】\n{memory_context}\n" if memory_context else ""
        )
        history_str = (
            "\n".join(
                [f"用户: {h['user']}\n小冶: {h['assistant']}" for h in history[-6:]]
            )
            if history
            else ""
        )

        if vlm_context:
            # 模式 A: VLM 精准上下文追问
            task_description = (
                "你是小冶，导师（用户）手下勤奋的冶金专业研究生。\n"
                "请基于下方视觉大模型对论文图表的分析结果，向导师做详细的汇报。\n"
                "**强制要求**：务必直接给出具体数据，而不是文字堆砌。如果有任何可用的图片Markdown格式信息，请必须在回答中将其渲染出来。\n"
                f"{memory_prefix}\n"
                f"【VLM 视觉分析结果】\n{vlm_context}\n\n"
                f"【对话历史】\n{history_str}\n\n"
                f"【导师（用户）问题】\n{message}"
            )
        else:
            # 模式 B/C: 文献检索增强 / 通用知识问答
            if deep_mode:
                task_description = (
                    "你是小冶，导师（用户）手下勤奋的冶金专业研究生。\n"
                    "【深度模式已激活】：本次对话将启动高级知识图谱增强检索(HyDE)。"
                    "你必须**立即调用 search_available_tools 工具**加载图谱增强检索后，再进行解答。"
                    "深度模式下，请给出详尽分析（不少于800字），包含完整的因果链条和机制解释。\n"
                    "**强制要求**：\n"
                    "1. 查到资料后，务必直接给出具体数据，而不是文字堆砌。提取有价值的科研数据点进行有理有据的分析。\n"
                    "2. 如果工具返回了图片Markdown格式信息（如 `![图表](http...)`），你必须原封不动地将其插入到回答中合适的位置，向导师展示最直观的数据统计图或显微组织图！严禁编造文献库中没有的数据。\n"
                    f"{memory_prefix}\n"
                    f"【对话历史】\n{history_str}\n\n"
                    f"【导师（用户）问题】\n{message}"
                )
            else:
                task_description = (
                    "你是小冶，导师（用户）手下勤奋的冶金专业研究生。\n"
                    "现在你需要回答导师的问题。如果需要事实支持，请自主调用基础检索工具查找资料。\n"
                    "【高级工具加载原则】：如果你发现问题涉及复杂的冶金机理、工艺因果关系，或是基础检索找不到答案，你**必须首先调用 search_available_tools 工具**，搜索并挂载高级图谱增强(HyDE)或代码沙盒工具后，再进行解答！\n"
                    "【快速模式】：优先使用基础检索回答。仅在基础检索确实找不到相关资料时，才调用 search_available_tools 加载高级工具。\n"
                    "**强制要求**：\n"
                    "1. 查到资料后，务必直接给出具体数据，而不是文字堆砌。提取有价值的科研数据点进行有理有据的分析。\n"
                    "2. 如果工具返回了图片Markdown格式信息（如 `![图表](http...)`），你必须原封不动地将其插入到回答中合适的位置，向导师展示最直观的数据统计图或显微组织图！严禁编造文献库中没有的数据。\n"
                    f"{memory_prefix}\n"
                    f"【对话历史】\n{history_str}\n\n"
                    f"【导师（用户）问题】\n{message}"
                )

        # ── Step 3: 调用 Reasoning 智能体管线 (取代原硬编码) ────────────────────
        from src.reasoning.graph import run_worker_pipeline

        payload = {"task_description": task_description, "deep_mode": deep_mode}

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
