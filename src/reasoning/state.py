from typing import TypedDict, Annotated, Sequence, List
import operator
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    """
    State structure for the Adaptive Self-RAG (Plan-and-Execute) Agent.
    """
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # The overarching plan formulated to answer the user query
    plan: List[str]
    
    # State tracking: what step in the plan are we currently executing?
    current_step_index: int
    
    # Outcomes of previously executed steps
    past_steps: Annotated[List[dict], operator.add]
    
    # Evaluator's determination: is the current step satisfied?
    step_satisfied: bool
    
    # Have we collected enough data to answer the final question?
    ready_to_synthesize: bool
    
    # ReAct 循环计数器 — 防止 Evaluator 陷入死循环无限消耗 Token
    loop_count: int
    
    # ---------------------------------------------------------
    # Claude Pattern: Thinking Chain (长链思考)
    # 新增：存储推理过程记录
    # ---------------------------------------------------------
    # Reasoning chain for thought process visualization
    reasoning: Annotated[List[str], operator.add]
    
    # Thinking configuration: {"type": "disabled"} or {"type": "adaptive", "budget": 32000}
    thinking_config: dict
