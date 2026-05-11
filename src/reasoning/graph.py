"""
Reasoning Pipeline — Worker ReAct 循环

[M5 迁移] 从 src/agent/graph.py 迁移至 src/reasoning/graph.py

关键重构：
  - 通过 ToolRegistry 接口获取工具，不再直接 import ALL_TOOLS
  - 通过 ToolLoader 接口进行环境探测，不再直接 import skill_loader
  - Reasoning 管线只依赖接口协议，实现与 Tooling 管线的完全解耦
"""

import asyncio
from typing import Literal
from pydantic import BaseModel, Field
import json

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import ToolNode

from src.reasoning.state import AgentState
from src.core.config import settings

# ReAct 循环最大迭代次数 — 防止 Evaluator 陷入死循环无限消耗 Token
MAX_REACT_LOOPS = 8

# ---------------------------------------------------------
# Claude Pattern: Leaf-Node Actor
# The Agent is no longer the omnipotent planner traversing an entire array.
# It is a specialized, one-shot Worker processing a single sub-task description.
# ---------------------------------------------------------

class Evaluation(BaseModel):
    is_satisfied: bool = Field(description="Whether the retrieved information fully answers the current subtask")
    feedback: str = Field(description="Reasoning for the decision, or instructions on what to search differently if False")

def create_worker_graph():
    # Base LLM
    # Claude Pattern: 启用 thinking（自动决定）
    llm = ChatOpenAI(
        model="qwen-max",
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
        temperature=0.2,
        extra_body={
            "thinking": {"type": "auto", "budget": 32000}
        }
    )

    # [M5] 通过 ToolRegistry 获取工具，而非直接 import
    from src.tooling.registry import get_tool_registry
    from src.tooling.loader import ToolLoader

    registry = get_tool_registry()
    tool_loader = ToolLoader()
    
    # 1. Researcher Node
    def researcher_node(state: AgentState):
        """Single-task Executor."""
        from langchain_core.messages import AIMessage
        
        # Getting task directly from state messages[0] which contains task_description
        task_description = state["messages"][0].content
        
        feedback = ""
        if len(state["messages"]) > 1 and hasattr(state["messages"][-1], "content"):
            last_content = state["messages"][-1].content
            if "EVALUATOR_FEEDBACK" in last_content:
                feedback = last_content
                
        sys_prompt = "你是一名底层的检索探测 Worker。不要向用户对话，直接调用工具。"
        user_prompt = f"任务指令: '{task_description}'\n{feedback}\n请立即调用合适的工具查证所需事实。\n注意：在使用检索工具获得带有来源标注的内容时，你的最终总结必须带上来源坐标，例如 `[来源: xxx.pdf, p.12]`，用于前端富媒体跳链。"

        # [M5] 通过 ToolLoader 获取工具（它内部使用 ToolRegistry）
        relevant_tools = tool_loader.probe_environment(task_description)
        dynamic_llm = llm.bind_tools(relevant_tools)
        
        from langchain_core.messages import SystemMessage, HumanMessage
        # 确保以 HumanMessage 结尾，避免大模型 API 报错
        msgs_to_send = [SystemMessage(content=sys_prompt)] + state["messages"][1:] + [HumanMessage(content=user_prompt)]
        
        # 使用非流式调用以确保 tool_calls 参数正确传递
        response = dynamic_llm.invoke(msgs_to_send)
        
        # 提取 response 和 tool_calls
        response_text = response.content if hasattr(response, 'content') else str(response)
        tool_calls = response.tool_calls if hasattr(response, 'tool_calls') else []
                
        # Claude Pattern: 记录推理过程到 state
        reasoning_record = f"**Thought**: 分析任务 '{task_description}'\n"
        if tool_calls:
            for tc in tool_calls:
                reasoning_record += f"**Action**: 调用工具 `{tc['name']}`\n"
        else:
            reasoning_record += f"**Final**: 直接生成回答\n"
        
        # 返回消息时包含 tool_calls + 推理记录
        return {
            "messages": [AIMessage(content=response_text, tool_calls=tool_calls)],
            "reasoning": [reasoning_record]
        }

    # 2. Compactor Node
    def compactor_node(state: AgentState):
        """Claude Pattern: Prevent context overflow"""
        messages = list(state["messages"])
        if not messages:
            return {}
            
        last_msg = messages[-1]
        from langchain_core.messages import ToolMessage
        if isinstance(last_msg, ToolMessage):
            content = str(last_msg.content)
            MAX_CHARS = 3000
            if len(content) > MAX_CHARS:
                trimmed_content = content[:MAX_CHARS] + f"...\n\n[System Note: Content truncated. Original chars: {len(content)}]"
                last_msg.content = trimmed_content

        return {"messages": []}

    # 3. Evaluator Node
    def evaluator_node(state: AgentState):
        """Reflects on the Tool Output against the single sub-task."""
        from langchain_core.messages import ToolMessage
        
        current_loop = state.get("loop_count", 0) + 1
        
        observations = [m.content for m in state["messages"] if isinstance(m, ToolMessage)]
        recent_obs = observations[-1] if observations else "No observation."
        task_description = state["messages"][0].content
        
        # 如果没有任何工具调用，说明不需要检索，直接认为满足
        has_tool_calls = any(
            hasattr(m, "tool_calls") and m.tool_calls 
            for m in state["messages"] 
            if hasattr(m, "tool_calls")
        )
        
        if not has_tool_calls and not observations:
            return {"step_satisfied": True, "loop_count": current_loop}
        
        # 循环兜底
        if current_loop >= MAX_REACT_LOOPS:
            print(f"[Evaluator] ⚠️ Max iterations ({MAX_REACT_LOOPS}) reached, forcing completion.")
            return {"step_satisfied": True, "loop_count": current_loop}
        
        prompt = f"""
        请评估以下事实数据是否足够解答给定的小任务块。
        子任务: {task_description}
        检索资料: {recent_obs}
        """
        
        eval_llm = llm.with_structured_output(Evaluation, method="function_calling")
        eval_obj = eval_llm.invoke([HumanMessage(content=prompt)])
        
        updates = {"step_satisfied": eval_obj.is_satisfied, "loop_count": current_loop}
        
        if not eval_obj.is_satisfied:
            from langchain_core.messages import HumanMessage
            updates["messages"] = [HumanMessage(content=f"EVALUATOR_FEEDBACK (loop {current_loop}/{MAX_REACT_LOOPS}): {eval_obj.feedback}")]
            
        return updates

    # 4. Routing
    def route_research_or_eval(state: AgentState) -> Literal["tools", "evaluator"]:
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "evaluator"
        
    def route_evaluator_loop(state: AgentState) -> Literal["researcher", "__end__"]:
        if state["step_satisfied"]:
            return "__end__"
        return "researcher"

    # [M5] 通过 ToolRegistry 获取全量工具，ToolNode 需要
    all_tools = registry.get_all_tools()
    tool_node = ToolNode(all_tools)

    workflow = StateGraph(AgentState)
    workflow.add_node("researcher", researcher_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("compactor", compactor_node)
    workflow.add_node("evaluator", evaluator_node)
    
    workflow.set_entry_point("researcher")
    workflow.add_conditional_edges("researcher", route_research_or_eval)
    workflow.add_edge("tools", "compactor")
    workflow.add_edge("compactor", "evaluator")
    workflow.add_conditional_edges("evaluator", route_evaluator_loop)
    
    return workflow.compile()

async def run_worker_pipeline(payload: dict) -> str:
    """Async entry wrapper specifically for the SwarmCoordinator.
    
    接通真实 LLM 调用，通过 LangGraph ainvoke 驱动完整的
    Researcher → ToolNode → Compactor → Evaluator ReAct 循环。
    """
    graph = create_worker_graph()
    state = {
        "messages": [SystemMessage(content=payload["task_description"])],
        "step_satisfied": False,
        "past_steps": [],
        "ready_to_synthesize": False,
        "loop_count": 0,
        # Claude Pattern: Thinking Chain
        "reasoning": [],
        "thinking_config": {"type": "disabled"}
    }
    
    try:
        result = await graph.ainvoke(state)
        # 从最终 messages 中提取 AI 的最后回答
        ai_messages = [
            m for m in result["messages"]
            if isinstance(m, AIMessage) and m.content and not m.content.startswith("EVALUATOR_FEEDBACK")
        ]
        if ai_messages:
            return ai_messages[-1].content
        return "Worker completed but produced no textual output."
    except Exception as e:
        print(f"[Worker Pipeline] ❌ Execution failed: {e}")
        return f"[Worker Error] {e}"
