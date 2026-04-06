import asyncio
from typing import Literal
from pydantic import BaseModel, Field
import json

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import ToolNode

from src.agent.state import AgentState
from src.agent.skill_loader import SkillLoader
from src.core.config import settings

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
    llm = ChatOpenAI(
        model="qwen-max",
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
        temperature=0.2
    )

    skill_loader = SkillLoader()
    
    # 1. Researcher Node
    def researcher_node(state: AgentState):
        """Single-task Executor."""
        # Getting task directly from state messages[0] which contains task_description
        task_description = state["messages"][0].content
        
        feedback = ""
        if len(state["messages"]) > 1 and hasattr(state["messages"][-1], "content"):
            last_content = state["messages"][-1].content
            if "EVALUATOR_FEEDBACK" in last_content:
                feedback = last_content
                
        prompt = f"""
        你是一名底层的检索探测 Worker。你的唯一任务是解决以下特定子任务块。
        任务指令: '{task_description}'
        {feedback}
        请立即调用合适的工具查证所需事实。不要向用户对话，直接调用工具。
        """

        # Claude Pattern: Environmental Heuristic Skill Loading
        relevant_tools = skill_loader.probe_environment(task_description)
        dynamic_llm = llm.bind_tools(relevant_tools)
        
        response = dynamic_llm.invoke([SystemMessage(content=prompt)] + state["messages"][1:])
        return {"messages": [response]}

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
        
        observations = [m.content for m in state["messages"] if isinstance(m, ToolMessage)]
        recent_obs = observations[-1] if observations else "No observation."
        task_description = state["messages"][0].content
        
        prompt = f"""
        请评估以下事实数据是否足够解答给定的小任务块。
        子任务: {task_description}
        检索资料: {recent_obs}
        """
        
        eval_llm = llm.with_structured_output(Evaluation, method="function_calling")
        eval_obj = eval_llm.invoke([HumanMessage(content=prompt)])
        
        updates = {"step_satisfied": eval_obj.is_satisfied}
        
        if not eval_obj.is_satisfied:
            updates["messages"] = [AIMessage(content=f"EVALUATOR_FEEDBACK: {eval_obj.feedback}")]
            
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

    # Worker relies on a super-set of all loaded tools node (LangGraph requirement)
    from src.agent.tools import TOOL_REGISTRY
    all_tools = TOOL_REGISTRY["general"] # We fallback all to registry for node compilation
    # But researcher only binds what is needed!
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
    """Async entry wrapper specifically for the SwarmCoordinator"""
    graph = create_worker_graph()
    state = {
        "messages": [SystemMessage(content=payload["task_description"])],
        "step_satisfied": False,
        "past_steps": [],
        "ready_to_synthesize": False
    }
    
    # In a real environment, we'd wait for LangGraph's aninvoke
    # For prototype compilation without full keys, we stub return
    # result = await graph.ainvoke(state)
    await asyncio.sleep(0.5) # Fake latency
    return "Mocked result from isolated RAG Worker"
