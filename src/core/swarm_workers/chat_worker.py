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
from src.core.memory_engine import load_preload_context, extract_and_save_memory, init_global_memory
from src.api.askuser_routes import trigger_ask_user, wait_for_user_reply


def _clear_proxy():
    """清除代理环境变量，确保直连 Aliyun Dashscope"""
    for key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
        os.environ.pop(key, None)
    os.environ["OPENAI_API_KEY"] = settings.QWEN_API_KEY
    os.environ["OPENAI_API_BASE"] = settings.QWEN_BASE_URL


async def dispatch_chat_worker(
    task_id: str,
    message: str,
    document_id: str | None,
    history: list,
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

        # ── Step 0: 从硬盘态记忆加载历史上下文 ────────────────────────────────
        memory_context = load_preload_context(task_id, document_id)

        # ── Step 1: 查询 Redis 是否已有 VLM 分析结果 ──────────────────────────
        vlm_key = f"xiaoye:chat:{task_id}"
        raw_vlm = await r.get(vlm_key)
        vlm_context = raw_vlm.decode("utf-8") if raw_vlm else None

        # ── Step 2: 文献检索（无 VLM 上下文时启用）────────────────────────────
        retrieved_context = ""
        if not vlm_context:
            # ── Step 2a: 写操作安全阀门（Human-In-The-Loop）──────────────────
            write_keywords = ["删除", "修改", "更新", "插入", "写入", "执行", "drop", "delete", "update", "insert", "execute"]
            if any(kw in message.lower() for kw in write_keywords):
                try:
                    ask_id = await trigger_ask_user(
                        task_id=task_id,
                        question=f"您的指令可能涉及数据修改操作：\n\n> {message[:200]}\n\n确认继续执行？",
                        ask_type="confirm",
                    )
                    reply = await wait_for_user_reply(ask_id, timeout=120)
                    if reply != "yes":
                        await r.publish(
                            "xiaoye_sse",
                            json.dumps({
                                "task_id": task_id,
                                "patch": "\n> ⛔ **用户已取消操作。**\n\n---\n",
                            }),
                        )
                        return
                    await r.publish(
                        "xiaoye_sse",
                        json.dumps({
                            "task_id": task_id,
                            "patch": "\n> ✅ **用户已确认，继续执行...**\n\n",
                        }),
                    )
                except Exception as ask_err:
                    print(f"[ChatWorker] AskUser safety gate failed (non-fatal): {ask_err}")

            # ── Step 2b: 文献检索 ────────────────────────────────────────────
            await r.publish(
                "xiaoye_sse",
                json.dumps({
                    "task_id": task_id,
                    "patch": "\n> 🔍 **正在检索知识库...**（`search_metallurgy_text`）\n",
                }),
            )
            try:
                from src.agent.tools import search_metallurgy_text
                results_str = search_metallurgy_text(message, top_k=3)
                if results_str and "No relevant" not in results_str:
                    retrieved_context = results_str
                    # 通知前端检索到了内容
                    await r.publish(
                        "xiaoye_sse",
                        json.dumps({
                            "task_id": task_id,
                            "patch": "> ✅ **找到相关文献片段，正在综合分析...**\n\n",
                        }),
                    )
                else:
                    await r.publish(
                        "xiaoye_sse",
                        json.dumps({
                            "task_id": task_id,
                            "patch": "> ℹ️ **知识库暂无相关文献，使用通用冶金知识回答**\n\n",
                        }),
                    )
            except Exception as e:
                # 检索失败不阻断流程，降级为通用回答
                await r.publish(
                    "xiaoye_sse",
                    json.dumps({
                        "task_id": task_id,
                        "patch": f"> ⚠️ 检索服务暂时不可用（{type(e).__name__}），使用通用知识回答\n\n",
                    }),
                )

        # ── Step 3: 构建 Prompt ────────────────────────────────────────────────
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        history_str = (
            "\n".join([
                f"用户: {h['user']}\n小冶: {h['assistant']}"
                for h in history[-6:]  # 最近 6 轮上下文
            ])
            if history
            else ""
        )

        # 记忆前缀（注入到所有模式）
        memory_prefix = f"\n\n【长程记忆】\n{memory_context}\n" if memory_context else ""

        if vlm_context:
            # 模式 A: VLM 精准上下文追问
            system_prompt = (
                "你是小冶，一个专业的冶金工程 AI 助手。"
                "请基于下方 VLM 对 PDF 区域的视觉分析结果，精准回答用户的追问。"
                "回答要专业、准确，引用具体数据时标明来源。请用中文回答。"
            )
            user_content = (
                f"{memory_prefix}"
                f"【VLM 视觉分析结果】\n{vlm_context}\n\n"
                f"【对话历史】\n{history_str}\n\n"
                f"【用户追问】\n{message}"
            )
        elif retrieved_context:
            # 模式 B: 文献检索增强回答
            system_prompt = (
                "你是小冶，一个专业的冶金工程 AI 助手，专注于冶金工程领域。"
                "请基于下方从知识库检索到的文献片段，回答用户的问题。"
                "如果文献片段包含来源坐标信息（如 [来源: xxx.pdf, p.12]），请在回答中引用。"
                "回答要专业、具体、有实践意义。请用中文回答。"
            )
            user_content = (
                f"{memory_prefix}"
                f"【检索到的相关文献片段】\n{retrieved_context}\n\n"
                f"【对话历史】\n{history_str}\n\n"
                f"【用户问题】\n{message}"
            )
        else:
            # 模式 C: 通用冶金知识问答（降级）
            system_prompt = (
                "你是小冶，一个专业的冶金工程 AI 助手，熟悉高炉炼铁、转炉炼钢、"
                "连铸连轧、热处理工艺、金属材料性能、化学成分分析、工业炉窑控制等冶金全流程知识。"
                "请用中文回答，回答要专业、具体、有实践意义。"
            )
            user_content = (
                f"{memory_prefix}"
                f"【对话历史】\n{history_str}\n\n"
                f"【用户问题】\n{message}"
            ) if history_str else f"{memory_prefix}{message}" if memory_prefix else message

        # ── Step 4: 流式调用 LLM ──────────────────────────────────────────────
        llm = ChatOpenAI(
            model="qwen-max",
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_BASE_URL,
            temperature=0.3,
            streaming=True,
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]

        full_response = ""
        try:
            async for chunk in llm.astream(messages):
                if chunk.content:
                    full_response += chunk.content
                    await r.publish(
                        "xiaoye_sse",
                        json.dumps({
                            "task_id": task_id,
                            "patch": chunk.content,
                        }),
                    )
        except Exception as e:
            await r.publish(
                "xiaoye_sse",
                json.dumps({
                    "task_id": task_id,
                    "patch": f"\n\n**[LLM 错误]** {type(e).__name__}: {str(e)}\n",
                }),
            )
            return

        # ── Step 5: 更新对话历史 + 结束信号 ───────────────────────────────────
        history_key = f"xiaoye:chat:{task_id}:history"
        history.append({"user": message, "assistant": full_response})
        if len(history) > 10:
            history = history[-10:]
        await r.set(history_key, json.dumps(history, ensure_ascii=False))

        # ── Step 6: 持久化记忆到硬盘 ──────────────────────────────────────────
        try:
            # 会话摘要：保留最近的问答对
            summary = f"用户问: {message[:200]}\n小冶答: {full_response[:500]}"
            extract_and_save_memory(
                task_id=task_id,
                document_id=document_id,
                conversation_summary=summary,
            )
        except Exception as mem_err:
            print(f"[ChatWorker] Memory save failed (non-fatal): {mem_err}")

        await r.publish(
            "xiaoye_sse",
            json.dumps({"task_id": task_id, "patch": "\n\n---\n"}),
        )

        print(f"[ChatWorker] task={task_id} completed. mode={'vlm' if vlm_context else 'rag' if retrieved_context else 'general'}")
