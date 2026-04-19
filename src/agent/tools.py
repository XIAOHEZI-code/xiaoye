# Agent 工具注册表 — 带渐进式披露 (Progressive Tool Disclosure)
# 单一职责：定义所有 LangChain Tool + 注册到 ToolSearchEngine + 提供动态装载接口
# 修复：使用 BaseTool 替代 @tool 装饰器，解决 LangGraph 1.x 兼容性

from pydantic import BaseModel, Field
from src.retrieval.semantic_search import SemanticSearchTool
from src.retrieval.graph_search import GraphLogicTool
from src.tools.sandbox import get_sandbox
from src.agent.tool_search import ToolMetadata, get_tool_search_engine
import json

semantic_searcher = SemanticSearchTool()
graph_searcher = GraphLogicTool()


# =============================================================
#  0. Pydantic 输入模型 (用于 BaseTool 包装)
# =============================================================

class SearchTextInput(BaseModel):
    query: str = Field(description="Search query text for metallurgy documents")
    top_k: int = Field(default=3, description="Number of results to return")


class GraphRelationsInput(BaseModel):
    entity: str = Field(description="Metallurgy entity name to search relations")


class ImpactPathInput(BaseModel):
    entity: str = Field(description="Entity name to trace impact path")


class PythonCodeInput(BaseModel):
    code: str = Field(description="Python code to execute in sandbox")


class SearchToolsInput(BaseModel):
    query: str = Field(description="Tool search query")
    max_results: int = Field(default=5, description="Max number of results")


# =============================================================
#  1. 定义原子工具 (Atomic Tools) - 纯函数定义
# =============================================================

def execute_metallurgy_python(code: str) -> str:
    """
    一个带有持久化状态的 Python 代码沙盒执行舱。
    使用场景：进行极高精度的热力学计算、流体模拟、Numpy数值推演，或是画图与相图(PyCalphad)计算等。
    重要提示：环境中的变量具有生命周期，在第一轮定义的变量可以在以后的调用中继续使用！如果生成图表，会自动拦截并返回Base64。
    """
    sandbox = get_sandbox()
    return sandbox.run_code(code)


def search_metallurgy_text(query: str, top_k: int = 3) -> str:
    """
    Search for chunked texts, standards, and image descriptions in the overarching metallurgy database.
    Use this when you need standard definitions, abstract concepts, or to look up physical properties.
    """
    results = semantic_searcher.search(query, top_k=top_k)
    if not results:
        return "No relevant text documents found."
    
    formatted = []
    for r in results:
        citation = r.to_citation_str()
        formatted.append(f"Doc: {r.doc_id} {citation} (Type: {r.source_type})\nContent: {r.text_content}")
        
    return "\n\n---\n\n".join(formatted)


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


# =============================================================
#  2. 创建 search_available_tools — LLM 主动拉取工具的入口
#     (Claude Code ToolSearchTool 的 Python 移植)
# =============================================================

def search_available_tools(query: str, max_results: int = 5) -> str:
    """
    搜索并加载可用工具的完整定义。这是你获取专用工具能力的唯一方式。

    你初始只知道工具的名称。当你需要调用某个工具时，必须先通过本工具搜索并加载它的参数定义。

    查询方式：
    - "select:search_metallurgy_text,execute_metallurgy_python" — 精确选取指定工具
    - "计算 热力学" — 按关键词搜索匹配的工具
    - "+graph 因果" — 名称中必须包含 "graph"，同时按 "因果" 排序

    返回格式：每个匹配工具的完整 JSON Schema 定义，加载后即可直接调用。
    """
    engine = get_tool_search_engine()
    results = engine.search(query, max_results=max_results)

    if not results:
        deferred_names = engine.get_deferred_tool_names()
        return (
            f"未找到匹配 '{query}' 的工具。\n"
            f"当前可搜索的延迟工具列表：{', '.join(deferred_names)}"
        )

    # 格式化为 LLM 可消费的结构
    output_lines = [f"找到 {len(results)} 个匹配工具：\n"]
    for r in results:
        output_lines.append(
            f"工具名: {r['name']}\n"
            f"分类: {r['category']}\n"
            f"描述: {r['description']}\n"
            f"参数 Schema: {json.dumps(r['parameters'], ensure_ascii=False, indent=2)}\n"
            f"---"
        )

    return "\n".join(output_lines)


# =============================================================
#  3. 注册所有工具到 ToolSearchEngine
# =============================================================

def _register_all_tools():
    """将所有原子工具注册到全局搜索引擎，携带元数据。"""
    engine = get_tool_search_engine()

    # 文本检索 — 核心工具，始终暴露
    engine.register(search_metallurgy_text, ToolMetadata(
        name="search_metallurgy_text",
        description="混合检索冶金文献/标准/图片描述（BM25+向量+RRF融合），返回带PDF坐标的溯源结果",
        category="text",
        search_hint="文献 标准 概念 定义 检索 查询 搜索 PDF",
        should_defer=False,   # 核心检索工具不隐藏
        always_load=True
    ))

    # 图谱单跳查询 — 延迟加载
    engine.register(search_metallurgy_graph_relations, ToolMetadata(
        name="search_metallurgy_graph_relations",
        description="查询冶金知识图谱中某实体的直接关联关系（单跳），获取工艺-性能因果链",
        category="graph",
        search_hint="关系 影响 因果 图谱 实体 节点 知识图谱 neo4j",
        should_defer=True
    ))

    # 图谱多跳追踪 — 延迟加载
    engine.register(trace_metallurgy_impact_path, ToolMetadata(
        name="trace_metallurgy_impact_path",
        description="追踪冶金实体的多跳因果传播路径（最深3跳），分析缺陷/工艺的级联影响",
        category="graph",
        search_hint="传播 级联 多跳 路径 缺陷 影响链 追踪",
        should_defer=True
    ))

    # Python 计算沙盒 — 延迟加载
    engine.register(execute_metallurgy_python, ToolMetadata(
        name="execute_metallurgy_python",
        description="有状态 Python 代码沙盒，支持 Numpy/Scipy/Matplotlib/PyCalphad 进行热力学计算、流体模拟等",
        category="calculation",
        search_hint="计算 数值 公式 方程 动力学 热力学 相图 模拟 代码 python numpy",
        should_defer=True
    ))

    # search_available_tools 自身 — 永不隐藏（LLM 需要它来找其他工具）
    engine.register(search_available_tools, ToolMetadata(
        name="search_available_tools",
        description="搜索和加载可用工具的完整定义，这是获取专用工具能力的唯一入口",
        category="system",
        search_hint="",
        should_defer=False,
        always_load=True
    ))


# 模块加载时自动注册
_register_all_tools()


# =============================================================
#  4. 对外暴露的工具装载接口 (StructuredTool 包装)
# =============================================================

from langchain_core.tools import StructuredTool

# 使用 StructuredTool.from_function 包装纯函数
TEXT_TOOLS = [
    StructuredTool.from_function(
        func=search_metallurgy_text,
        name="search_metallurgy_text",
        description="Search for chunked texts, standards, and image descriptions in the metallurgy database.",
        args_schema=SearchTextInput
    )
]

GRAPH_TOOLS = [
    StructuredTool.from_function(
        func=search_metallurgy_graph_relations,
        name="search_metallurgy_graph_relations",
        description="Search the Knowledge Graph to find direct relationships (1-hop) connected to a Metallurgy Entity.",
        args_schema=GraphRelationsInput
    ),
    StructuredTool.from_function(
        func=trace_metallurgy_impact_path,
        name="trace_metallurgy_impact_path",
        description="Trace the multi-hop causal impact path of a Metallurgy Entity (up to 3 hops).",
        args_schema=ImpactPathInput
    )
]

CALCULATION_TOOLS = [
    StructuredTool.from_function(
        func=execute_metallurgy_python,
        name="execute_metallurgy_python",
        description="Execute Python code in a sandbox for thermodynamics calculation or simulation.",
        args_schema=PythonCodeInput
    )
]

SEARCH_TOOLS = [
    StructuredTool.from_function(
        func=search_available_tools,
        name="search_available_tools",
        description="Search and load the complete definition of available tools.",
        args_schema=SearchToolsInput
    )
]

# ToolNode 需要的全量工具列表（包含 search_available_tools）
ALL_TOOLS = TEXT_TOOLS + GRAPH_TOOLS + CALCULATION_TOOLS + SEARCH_TOOLS

TOOL_REGISTRY = {
    "text": TEXT_TOOLS,
    "graph": GRAPH_TOOLS,
    "calculation": CALCULATION_TOOLS,
    "general": TEXT_TOOLS + GRAPH_TOOLS + CALCULATION_TOOLS + SEARCH_TOOLS
}


def get_tools_for_step(step_description: str) -> list:
    """渐进式工具装载：始终提供核心工具 + ToolSearch，让 LLM 自行按需拉取。

    与旧版关键词匹配不同，这里只提供：
    1. always_load=True 的核心工具（如文本检索）
    2. search_available_tools 工具（让 LLM 自己搜索更多工具）

    LLM 在 ReAct 循环中如果发现需要图谱/计算等能力，
    会主动调用 search_available_tools 来拉取完整定义。

    Args:
        step_description: 子任务描述（保留参数以兼容旧调用方）

    Returns:
        初始暴露给 LLM 的最小工具集
    """
    engine = get_tool_search_engine()
    return engine.get_always_loaded_tools()
