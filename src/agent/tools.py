from langchain_core.tools import tool
from src.retrieval.semantic_search import SemanticSearchTool
from src.retrieval.graph_search import GraphLogicTool
from src.tools.sandbox import get_sandbox
import json

semantic_searcher = SemanticSearchTool()
graph_searcher = GraphLogicTool()

@tool
def execute_metallurgy_python(code: str) -> str:
    """
    一个带有持久化状态的 Python 代码沙盒执行舱。
    使用场景：进行极高精度的热力学计算、流体模拟、Numpy数值推演，或是画图与相图(PyCalphad)计算等。
    重要提示：环境中的变量具有生命周期，在第一轮定义的变量可以在以后的调用中继续使用！如果生成图表，会自动拦截并返回Base64。
    """
    sandbox = get_sandbox()
    return sandbox.run_code(code)

@tool
def search_metallurgy_text(query: str, top_k: int = 3) -> str:
    """
    Search for chunked texts, standards, and image descriptions in the overarching metallurgy database.
    Use this when you need standard definitions, abstract concepts, or to look up physical properties.
    """
    results = semantic_searcher.search(query, top_k=top_k)
    if not results:
        return "No relevant text documents found."
    
    # Format results for the Agent
    formatted = []
    for r in results:
        formatted.append(f"Doc: {r['doc_id']} (Type: {r['source_type']})\nContent: {r['content']}")
        
    return "\n\n---\n\n".join(formatted)

@tool
def search_metallurgy_graph_relations(entity: str) -> str:
    """
    Search the Knowledge Graph to find direct relationships (1-hop) connected to a specific Metallurgy Entity.
    Use this when you want to know what impacts a property, or what process a material goes through.
    """
    results = graph_searcher.find_direct_relations(entity)
    if not results:
        return f"No graph relations found for entity: {entity}"
        
    formatted = [f"Found {len(results)} relations:"]
    for r in results:
        formatted.append(f"({r['subject']}) -[{r['relation']}]-> ({r['object']}) [Source: {r['source_doc']}]")
        
    return "\n".join(formatted)

@tool
def trace_metallurgy_impact_path(entity: str) -> str:
    """
    Trace the multi-hop causal impact path of a specific Metallurgy Entity (up to 3 hops).
    Use this to see ripple effects, e.g., how a specific defect or process cascades into final properties.
    """
    results = graph_searcher.trace_impact_path(entity)
    if not results:
        return f"No impact paths found starting from: {entity}"
        
    formatted = [f"Found {len(results)} impact paths:"]
    for idx, r in enumerate(results):
        nodes = " -> ".join(r['nodes'])
        formatted.append(f"Path {idx+1}: {nodes}")
        
    return "\n".join(formatted)

# Dynamically grouped tools for Context saving
TEXT_TOOLS = [search_metallurgy_text]
GRAPH_TOOLS = [search_metallurgy_graph_relations, trace_metallurgy_impact_path]
CALCULATION_TOOLS = [execute_metallurgy_python]

# Dictionary to dynamically map domain hints
TOOL_REGISTRY = {
    "text": TEXT_TOOLS,
    "graph": GRAPH_TOOLS,
    "calculation": CALCULATION_TOOLS,
    "general": TEXT_TOOLS + GRAPH_TOOLS + CALCULATION_TOOLS
}

def get_tools_for_step(step_description: str) -> list:
    """Claude Pattern: Dynamic Tool Loading based on contextual hints"""
    step_lower = step_description.lower()
    selected = set()
    
    if any(k in step_lower for k in ["关系", "影响", "关系图", "节点", "传播"]):
        selected.update(GRAPH_TOOLS)
    if any(k in step_lower for k in ["文献", "标准", "文本", "概念", "定义"]):
        selected.update(TEXT_TOOLS)
    if any(k in step_lower for k in ["计算", "预测", "数值", "相图", "热力学"]):
        selected.update(CALCULATION_TOOLS)
        
    # Fallback to general if no specific hint is found
    if not selected:
        return TOOL_REGISTRY["general"]
        
    return list(selected)
