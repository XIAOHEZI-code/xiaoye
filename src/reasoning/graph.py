"""
Reasoning Pipeline — Worker ReAct 循环 (Claude Code-inspired simplification)

Key changes from M5:
  - Removed Evaluator node (eliminated LLM-as-judge overhead)
  - Direct loop: tools→compactor→researcher (no intermediary evaluator)
  - Diminishing returns detection in compactor (character-level Jaccard)
  - Model tiering: FAST (qwen-turbo) vs DEEP (qwen-max+thinking)
  - Max turns raised from 4 to 12
  - Researcher embodies Claude Code "don't gold-plate" philosophy
"""

import asyncio
from typing import Literal
from pydantic import BaseModel, Field
import json

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.prebuilt import ToolNode

from src.reasoning.state import AgentState
from src.core.config import settings
from src.core.logger import setup_logger

logger = setup_logger("xiaoye.reasoning")

# ReAct 循环最大迭代次数 — 防止死循环无限消耗 Token
MAX_REACT_LOOPS = 12


def create_worker_graph(deep_mode: bool = False):
    """Create the Worker ReAct graph with model tiering.

    Args:
        deep_mode: If True, use qwen-max with thinking budget for deep research.
                   If False, use qwen-turbo for speed.
    """
    model_name = "qwen-max" if deep_mode else "qwen-turbo"
    extra = {"thinking": {"type": "auto", "budget": 32000}} if deep_mode else {}

    logger.info(
        "[Graph] Creating worker graph in %s mode",
        "DEEP (qwen-max+thinking)" if deep_mode else "FAST (qwen-turbo)",
    )

    llm = ChatOpenAI(
        model=model_name,
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
        temperature=0.2,
        extra_body=extra,
    )

    llm_without_tools = ChatOpenAI(
        model=model_name,
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
        temperature=0.2,
        extra_body=extra,
    )

    # [M5] Tool loading via registry and loader
    from src.tooling.registry import get_tool_registry
    from src.tooling.loader import ToolLoader

    registry = get_tool_registry()
    tool_loader = ToolLoader()

    # ------------------------------------------------------------------
    # 1. Researcher Node — Claude Code "don't gold-plate" philosophy
    # ------------------------------------------------------------------
    async def researcher_node(state: AgentState):
        """Single-task executor. Stop searching when you have enough — don't gold-plate."""
        # 提取真实的原始任务内容以备打印/记录和工具加载 (排除系统干预消息)
        user_prompt_msg = next((m for m in reversed(state["messages"]) if isinstance(m, HumanMessage) and "[系统干预]" not in str(m.content)), None)
        task_description = str(user_prompt_msg.content) if user_prompt_msg else "Unknown task"
        logger.info("[Researcher] Executing task: %s...", task_description[:50])

        # Extract injected system intervention from compactor, if any
        feedback = ""
        messages = list(state["messages"])
        if len(messages) > 1:
            last = messages[-1]
            if isinstance(last, HumanMessage) and "[系统干预]" in str(last.content):
                feedback = last.content

        sys_prompt = (
            "你是一名底层的检索探测 Worker。不要向用户对话，直接调用工具。\n"
            "【自主决策原则】：你就是决定何时停止检索的人。如果已有足够资料回答，立即停止调用工具，直接给出答案。"
            "宁可给出有据可查的不完整回答，也不要为了'完美匹配'反复搜索。"
            "当资料库中没有直接答案时，坦诚说明，给出已知的最相关数据即可。"
            "不要 Gold-Plate：一次检索命中主题相关内容即可，不需要穷举所有可能的搜索词。\n\n"
            "【检索纪律】\n"
            "1. 在使用检索工具获得带有来源标注的内容时，你的最终总结必须带上来源坐标，例如 `[来源: xxx.pdf, p.12]`，用于前端富媒体跳链。\n"
            "2. 如果你发现上一次检索没有查到结果，**绝对不要**使用相同的关键词再次检索！请尝试更改为同义词、上位概念。\n"
            "3. 同一工具不要连续调用超过 2 次。如果两次检索返回相似内容，立即停止搜索并给出答案。"
        )

        if feedback:
            sys_prompt += f"\n\n{feedback}"

        # [M5] Probe environment to load only relevant tools
        relevant_tools = tool_loader.probe_environment(task_description)
        dynamic_llm = llm.bind_tools(relevant_tools)

        # 把 researcher 特有指令插在 messages 队列的最前面
        msgs_to_send = [SystemMessage(content=sys_prompt)] + list(state["messages"])

        response = await dynamic_llm.ainvoke(msgs_to_send)

        response_text = (
            response.content if hasattr(response, "content") else str(response)
        )
        tool_calls = response.tool_calls if hasattr(response, "tool_calls") else []

        reasoning_record = f"**Thought**: 分析任务 '{task_description}'\n"
        if tool_calls:
            for tc in tool_calls:
                reasoning_record += f"**Action**: 调用工具 `{tc['name']}`\n"
        else:
            reasoning_record += "**Final**: 直接生成回答\n"

        return {
            "messages": [AIMessage(content=response_text, tool_calls=tool_calls)],
            "reasoning": [reasoning_record],
        }

    # ------------------------------------------------------------------
    # 2. Compactor Node — trim outputs + detect diminishing returns
    # ------------------------------------------------------------------
    async def compactor_node(state: AgentState):
        """Trim oversized tool outputs and detect diminishing returns.

        Injects a system intervention message if consecutive searches overlap
        significantly, telling the researcher to stop searching.
        """
        messages = list(state["messages"])
        if not messages:
            return {}

        current_loop = state.get("loop_count", 0) + 1
        updates: dict = {"loop_count": current_loop}

        last_msg = messages[-1]
        if isinstance(last_msg, ToolMessage):
            content = str(last_msg.content)
            tool_name = last_msg.name

            # ----- Detailed tool result logging -----
            logger.info(
                "[Compactor] Tool: `%s` | Result length: %d chars",
                tool_name,
                len(content),
            )
            preview = content[:200]
            if len(content) > 200:
                preview += "..."
            logger.info("[Compactor] Preview (first 200 chars): %s", preview)

            content_lower = content.lower().strip()
            if len(content.strip()) == 0:
                logger.warning(
                    "[Compactor] ⚠️ Tool `%s` returned EMPTY result!", tool_name
                )
            elif any(
                keyword in content_lower
                for keyword in [
                    "no results",
                    "未找到",
                    "没有找到",
                    "无结果",
                    "no documents",
                    "empty",
                ]
            ):
                logger.warning(
                    "[Compactor] ⚠️ Tool `%s` indicates 'no results found' or empty data!",
                    tool_name,
                )

            # Trim oversized content
            MAX_CHARS = 3000
            if len(content) > MAX_CHARS:
                last_msg.content = (
                    content[:MAX_CHARS]
                    + f"...\n\n[System Note: Content truncated. Original chars: {len(content)}]"
                )

            # ----- Diminishing returns detection -----
            tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
            if len(tool_messages) >= 2:
                last_text = str(tool_messages[-1].content)[:400]
                prev_text = str(tool_messages[-2].content)[:400]
                set_last = set(last_text)
                set_prev = set(prev_text)
                if set_last and set_prev:
                    overlap = len(set_last & set_prev) / len(set_last | set_prev)
                    if overlap > 0.5:
                        logger.info(
                            "[Compactor] ⚠️ Diminishing returns detected (overlap=%.2f). Injecting stop signal.",
                            overlap,
                        )
                        updates["messages"] = [
                            HumanMessage(
                                content=(
                                    "[系统干预] 最近两次检索返回了高度相似的内容（重叠度{:.0%}）。"
                                    "这表明进一步搜索不会带来新信息。"
                                    "请在下一轮直接基于已有资料给出回答，不要再调用任何检索工具。"
                                ).format(overlap)
                            )
                        ]
                        updates["past_steps"] = [
                            "diminishing_returns_at_{:.2f}".format(overlap)
                        ]

        # Max loops guard — force stop regardless
        if current_loop >= MAX_REACT_LOOPS:
            logger.warning(
                "[Compactor] ⚠️ Max iterations (%d) reached, forcing completion.",
                MAX_REACT_LOOPS,
            )
            updates["messages"] = [
                HumanMessage(
                    content=(
                        "[系统干预] 已达最大检索次数({})。"
                        "请立即停止检索，直接根据你目前掌握的信息回答用户问题，不要再调用任何工具！"
                    ).format(MAX_REACT_LOOPS)
                )
            ]
            updates["past_steps"] = updates.get("past_steps", []) + [
                "max_loops_reached_at_{}".format(MAX_REACT_LOOPS)
            ]

        return updates

    # ------------------------------------------------------------------
    # 3. Synthesizer Node — final answer generation (unchanged)
    # ------------------------------------------------------------------
    async def synthesizer_node(state: AgentState):
        """Generate the final comprehensive answer using all collected tool outputs, WITHOUT any tool calls."""
        # 从历史消息中提取原始提问作为任务描述，避免取到中间产生的 ToolMessage
        user_prompt_msg = next((m for m in reversed(state["messages"]) if isinstance(m, HumanMessage) and "[系统干预]" not in str(m.content)), None)
        task_description = str(user_prompt_msg.content) if user_prompt_msg else "Unknown task"

        # Collect all tool outputs from the message history
        tool_outputs = []
        for m in state["messages"]:
            if isinstance(m, ToolMessage):
                tool_outputs.append("[工具: {}]\n{}".format(m.name, str(m.content)))

        collected = "\n\n---\n\n".join(tool_outputs) if tool_outputs else "无检索资料"

        system_prompt = (
            "你是一名冶金领域的研究生。请结合之前的对话历史和刚才检索到的资料，生成最终的综合回答。绝对不要调用任何工具。\n"
            "【强制要求】你的回答中必须标注信息来源，格式为：[来源: 文件名, p.页码]。"
            "引用具体数据时必须注明来源出处。\n"
            "【长度要求】请生成详尽完整的回答（不少于500字），包含具体数据、分析逻辑、因果解释和来源标注。"
            "对于涉及机理分析的问题，请展开说明完整的因果链条。"
        )
        
        # 将收集的工具资料作为最后一条 HumanMessage 给到合成器
        synthesis_prompt = (
            "以下是从资料库中检索到的相关资料:\n{}\n\n"
            "请基于以上资料生成综合回答。如果资料不足以回答，请明确指出缺失的信息。\n"
            "【重要提醒】务必在引用数据时标注来源（如：根据[来源: test.pdf, p.4]的数据显示...）"
        ).format(collected)

        logger.info(
            "[Synthesizer] Generating final answer from %d tool outputs for task: %s...",
            len(tool_outputs),
            task_description[:50],
        )

        # 过滤掉 state["messages"] 中的 ToolMessage 以及包含 tool_calls 的 AIMessage
        # 避免文献资料被重复拼接灌入，导致 Token 翻倍和击穿窗口
        filtered_messages = []
        for m in state["messages"]:
            if isinstance(m, ToolMessage):
                continue
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                continue
            filtered_messages.append(m)

        msgs = [SystemMessage(content=system_prompt)] + filtered_messages + [HumanMessage(content=synthesis_prompt)]
        response = await llm_without_tools.ainvoke(msgs)

        return {
            "messages": [
                AIMessage(
                    content=response.content
                    if hasattr(response, "content")
                    else str(response)
                )
            ],
            "ready_to_synthesize": True,
            "step_satisfied": True,
        }

    # ------------------------------------------------------------------
    # 4. Routing Functions
    # ------------------------------------------------------------------
    def route_research_or_eval(state: AgentState) -> Literal["tools", "synthesizer"]:
        """Route researcher output: tool_calls → tools, otherwise → synthesizer."""
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "synthesizer"

    def route_after_compactor(state: AgentState) -> Literal["researcher"]:
        """Always route back to researcher after compaction — no evaluator intermediary."""
        return "researcher"

    # ------------------------------------------------------------------
    # 5. Build graph: 4 nodes, no evaluator
    # ------------------------------------------------------------------
    all_tools = registry.get_all_tools()
    tool_node = ToolNode(all_tools)

    workflow = StateGraph(AgentState)
    workflow.add_node("researcher", researcher_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("compactor", compactor_node)
    workflow.add_node("synthesizer", synthesizer_node)

    workflow.set_entry_point("researcher")
    workflow.add_conditional_edges("researcher", route_research_or_eval)
    workflow.add_edge("tools", "compactor")
    workflow.add_conditional_edges("compactor", route_after_compactor)
    workflow.add_edge("synthesizer", END)

    return workflow.compile()


async def run_worker_pipeline(payload: dict, task_id: str) -> str:
    """Async entry wrapper for the SwarmCoordinator or ChatWorker.

    Drives the simplified ReAct loop (researcher → tools → compactor → researcher)
    via LangGraph astream_events, pushing streaming events to SSE.
    """
    from src.delivery.sse_channel import get_sse_channel

    sse = get_sse_channel()

    deep_mode = payload.get("deep_mode", False)
    graph = create_worker_graph(deep_mode=deep_mode)
    state = {
        "messages": payload["messages"],
        "step_satisfied": False,
        "past_steps": [],
        "ready_to_synthesize": False,
        "loop_count": 0,
        "reasoning": [],
        "thinking_config": {"type": "adaptive", "budget": 32000},
        "task_id": task_id,
    }
    final_output = ""
    logger.info(
        "Starting Worker Pipeline for task_id: %s (deep_mode=%s)", task_id, deep_mode
    )

    try:
        async for event in graph.astream_events(
            state, version="v2", config={"recursion_limit": 50}
        ):
            kind = event["event"]

            # Stream LLM token output
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]

                # ── 分离思维链 (thinking) 与正文 (content) ──
                # qwen-max 在 deep_mode 下会返回 chunk.thinking 字段
                if hasattr(chunk, "thinking") and chunk.thinking:
                    await sse.async_publish("reasoning", {
                        "task_id": task_id,
                        "type": "reasoning",
                        "thinking": chunk.thinking,
                    })

                if hasattr(chunk, "content") and chunk.content:
                    final_output += chunk.content
                    await sse.async_publish_chat_patch(task_id, chunk.content)

            # Tool invocation notification
            elif kind == "on_tool_start":
                tool_name = event["name"]
                logger.info(
                    "[Worker Pipeline] 🛠️ Tool Invoked: %s with inputs: %s",
                    tool_name,
                    event.get("data", {}).get("input"),
                )
                await sse.async_publish_chat_patch(
                    task_id,
                    "\n\n> 🛠️ **正在调用工具检索...** (`{}`)\n".format(tool_name),
                )

        if not final_output:
            logger.warning(
                "[Worker Pipeline] Completed but produced no textual output for task %s",
                task_id,
            )
            return "Worker completed but produced no textual output."

        logger.info("[Worker Pipeline] Successfully completed task %s", task_id)
        return final_output

    except Exception as e:
        logger.error("[Worker Pipeline] ❌ Execution failed: %s", e, exc_info=True)
        await sse.async_publish_chat_patch(
            task_id, "\n\n> ❌ **管线执行异常**: {}\n".format(e)
        )
        return "[Worker Error] {}".format(e)
