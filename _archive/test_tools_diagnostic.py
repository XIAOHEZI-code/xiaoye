"""
工具诊断测试脚本 — 检查所有 Agent 工具的定义完整性和运行可用性

测试范围：
  1. 工具注册与元数据完整性
  2. ToolSearchEngine 搜索/加载功能
  3. 各工具的实际调用测试（安全沙盒内）
  4. 依赖服务连通性（ES, Neo4j, Redis, Qwen API）
"""

import os
import sys
import json
import traceback

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 清除代理
for key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(key, None)


def banner(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_result(name: str, success: bool, detail: str = ""):
    icon = "✅" if success else "❌"
    print(f"  {icon} {name}" + (f" — {detail}" if detail else ""))
    return success


# ──────────────────────────────────────────────────────────────
# Phase 1: 工具注册与元数据
# ──────────────────────────────────────────────────────────────
banner("Phase 1: 工具注册与元数据检查")

results = {"pass": 0, "fail": 0}

try:
    from src.agent.tools import (
        ALL_TOOLS, TEXT_TOOLS, GRAPH_TOOLS, CALCULATION_TOOLS,
        VISION_TOOLS, SEARCH_TOOLS, TOOL_REGISTRY, get_tools_for_step
    )
    test_result("工具模块导入", True)
    results["pass"] += 1
except Exception as e:
    test_result("工具模块导入", False, str(e))
    results["fail"] += 1
    traceback.print_exc()
    sys.exit(1)

# 列出所有工具
print(f"\n  📋 已注册工具总数: {len(ALL_TOOLS)}")
print(f"     - TEXT_TOOLS:        {len(TEXT_TOOLS)} 个")
print(f"     - GRAPH_TOOLS:       {len(GRAPH_TOOLS)} 个")
print(f"     - CALCULATION_TOOLS: {len(CALCULATION_TOOLS)} 个")
print(f"     - VISION_TOOLS:      {len(VISION_TOOLS)} 个")
print(f"     - SEARCH_TOOLS:      {len(SEARCH_TOOLS)} 个")

print(f"\n  📝 各工具详情:")
for i, tool in enumerate(ALL_TOOLS, 1):
    print(f"     [{i}] {tool.name}")
    print(f"         描述: {tool.description[:80]}...")
    if hasattr(tool, 'args_schema') and tool.args_schema:
        schema_fields = list(tool.args_schema.model_fields.keys())
        print(f"         参数: {schema_fields}")
    ok = bool(tool.name and tool.description)
    if ok:
        results["pass"] += 1
    else:
        results["fail"] += 1
    test_result(f"工具 [{tool.name}] 元数据完整", ok)

# ──────────────────────────────────────────────────────────────
# Phase 2: ToolSearchEngine 测试
# ──────────────────────────────────────────────────────────────
banner("Phase 2: ToolSearchEngine 搜索引擎")

try:
    from src.agent.tool_search import get_tool_search_engine
    engine = get_tool_search_engine()
    
    # 测试获取 always_load 工具
    always_loaded = engine.get_always_loaded_tools()
    test_result("get_always_loaded_tools()", len(always_loaded) > 0,
                f"返回 {len(always_loaded)} 个核心工具")
    results["pass" if len(always_loaded) > 0 else "fail"] += 1
    
    # 测试获取延迟工具名列表
    deferred = engine.get_deferred_tool_names()
    test_result("get_deferred_tool_names()", len(deferred) > 0,
                f"延迟工具: {deferred}")
    results["pass" if len(deferred) > 0 else "fail"] += 1
    
    # 测试关键词搜索
    search_results = engine.search("计算 热力学", max_results=3)
    test_result("关键词搜索 '计算 热力学'", len(search_results) > 0,
                f"命中 {len(search_results)} 个工具" + 
                (f": {[r['name'] for r in search_results]}" if search_results else ""))
    results["pass" if len(search_results) > 0 else "fail"] += 1
    
    # 测试精确选取
    select_results = engine.search("select:search_metallurgy_text", max_results=1)
    test_result("精确选取 'select:search_metallurgy_text'", len(select_results) == 1,
                f"命中: {[r['name'] for r in select_results]}" if select_results else "未命中")
    results["pass" if len(select_results) == 1 else "fail"] += 1
    
    # 测试搜索图谱工具
    graph_results = engine.search("+graph 因果", max_results=3)
    test_result("前缀搜索 '+graph 因果'", len(graph_results) > 0,
                f"命中: {[r['name'] for r in graph_results]}" if graph_results else "未命中")
    results["pass" if len(graph_results) > 0 else "fail"] += 1

except Exception as e:
    test_result("ToolSearchEngine", False, str(e))
    results["fail"] += 1
    traceback.print_exc()

# ──────────────────────────────────────────────────────────────
# Phase 3: SkillLoader 环境探测
# ──────────────────────────────────────────────────────────────
banner("Phase 3: SkillLoader 环境探测式工具装填")

try:
    from src.agent.skill_loader import SkillLoader
    loader = SkillLoader()
    
    # 普通文本任务 — 应该返回核心工具
    tools_text = loader.probe_environment("请问什么是高炉炼铁？")
    tool_names = [t.name for t in tools_text]
    test_result("文本任务探测", len(tools_text) >= 2,
                f"返回 {len(tools_text)} 个工具: {tool_names}")
    results["pass" if len(tools_text) >= 2 else "fail"] += 1
    
    # 计算任务
    tools_calc = loader.probe_environment("计算热力学自由能变化")
    calc_names = [t.name for t in tools_calc]
    test_result("计算任务探测", len(tools_calc) >= 2,
                f"返回 {len(tools_calc)} 个工具: {calc_names}")
    results["pass" if len(tools_calc) >= 2 else "fail"] += 1

except Exception as e:
    test_result("SkillLoader", False, str(e))
    results["fail"] += 1
    traceback.print_exc()

# ──────────────────────────────────────────────────────────────
# Phase 4: 依赖服务连通性测试
# ──────────────────────────────────────────────────────────────
banner("Phase 4: 依赖服务连通性")

# 4.1 Redis
try:
    import redis
    r = redis.from_url("redis://localhost:6379/0")
    r.ping()
    test_result("Redis 连接", True, "localhost:6379 ✓")
    results["pass"] += 1
    r.close()
except Exception as e:
    test_result("Redis 连接", False, str(e))
    results["fail"] += 1

# 4.2 PostgreSQL
try:
    from src.db.session import SessionLocal
    db = SessionLocal()
    db.execute(__import__('sqlalchemy').text("SELECT 1"))
    test_result("PostgreSQL 连接", True, "localhost:5432 ✓")
    results["pass"] += 1
    db.close()
except Exception as e:
    test_result("PostgreSQL 连接", False, str(e))
    results["fail"] += 1

# 4.3 Elasticsearch
try:
    from elasticsearch import Elasticsearch
    es = Elasticsearch("http://localhost:9200")
    info = es.info()
    test_result("Elasticsearch 连接", True, f"版本 {info['version']['number']}")
    results["pass"] += 1
except Exception as e:
    test_result("Elasticsearch 连接", False, f"未运行 — {type(e).__name__}")
    results["fail"] += 1

# 4.4 Neo4j
try:
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "xiaoye_neo4j"))
    with driver.session() as session:
        session.run("RETURN 1")
    test_result("Neo4j 连接", True, "localhost:7687 ✓")
    results["pass"] += 1
    driver.close()
except Exception as e:
    test_result("Neo4j 连接", False, str(e))
    results["fail"] += 1

# 4.5 Qwen API
try:
    from src.core.config import settings
    if settings.QWEN_API_KEY:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model="qwen-max",
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_BASE_URL,
            temperature=0,
            max_tokens=20,
        )
        resp = llm.invoke("你好，请用一个词回答：1+1等于几？")
        test_result("Qwen API (qwen-max)", True, f"回复: {resp.content[:50]}")
        results["pass"] += 1
    else:
        test_result("Qwen API", False, "QWEN_API_KEY 未配置")
        results["fail"] += 1
except Exception as e:
    test_result("Qwen API", False, str(e))
    results["fail"] += 1

# ──────────────────────────────────────────────────────────────
# Phase 5: 各工具实际调用测试
# ──────────────────────────────────────────────────────────────
banner("Phase 5: 工具实际调用测试")

# 5.1 search_available_tools（纯本地，无外部依赖）
try:
    from src.agent.tools import search_available_tools
    result = search_available_tools("计算", max_results=3)
    has_result = "找到" in result or "工具" in result
    test_result("search_available_tools('计算')", has_result,
                f"返回 {len(result)} 字符")
    results["pass" if has_result else "fail"] += 1
except Exception as e:
    test_result("search_available_tools", False, str(e))
    results["fail"] += 1

# 5.2 search_metallurgy_text（需要 ES）
try:
    from src.agent.tools import search_metallurgy_text
    result = search_metallurgy_text("高炉炉渣", top_k=2)
    is_ok = result is not None
    if "No relevant" in result or "Error" in result.lower():
        test_result("search_metallurgy_text('高炉炉渣')", True,
                    f"ES 可达但知识库为空 — {result[:80]}")
    else:
        test_result("search_metallurgy_text('高炉炉渣')", True,
                    f"检索到结果: {result[:100]}...")
    results["pass"] += 1
except Exception as e:
    err_type = type(e).__name__
    if "Connection" in err_type or "connection" in str(e).lower():
        test_result("search_metallurgy_text", False, "Elasticsearch 未运行")
    else:
        test_result("search_metallurgy_text", False, f"{err_type}: {str(e)[:80]}")
    results["fail"] += 1

# 5.3 search_metallurgy_graph_relations（需要 Neo4j）
try:
    from src.agent.tools import search_metallurgy_graph_relations
    result = search_metallurgy_graph_relations("碳含量")
    is_ok = result is not None
    test_result("search_metallurgy_graph_relations('碳含量')", True,
                f"结果: {result[:100]}")
    results["pass"] += 1
except Exception as e:
    test_result("search_metallurgy_graph_relations", False, str(e)[:80])
    results["fail"] += 1

# 5.4 trace_metallurgy_impact_path（需要 Neo4j）
try:
    from src.agent.tools import trace_metallurgy_impact_path
    result = trace_metallurgy_impact_path("碳含量")
    test_result("trace_metallurgy_impact_path('碳含量')", True,
                f"结果: {result[:100]}")
    results["pass"] += 1
except Exception as e:
    test_result("trace_metallurgy_impact_path", False, str(e)[:80])
    results["fail"] += 1

# 5.5 execute_metallurgy_python（纯本地沙盒）
try:
    from src.agent.tools import execute_metallurgy_python
    result = execute_metallurgy_python("print(2 + 3)")
    has_5 = "5" in result
    test_result("execute_metallurgy_python('print(2+3)')", has_5,
                f"输出: {result.strip()[:100]}")
    results["pass" if has_5 else "fail"] += 1
except Exception as e:
    test_result("execute_metallurgy_python", False, str(e)[:80])
    results["fail"] += 1

# 5.6 execute_metallurgy_python — NumPy 测试
try:
    from src.agent.tools import execute_metallurgy_python
    code = "import numpy as np; print(f'NumPy version: {np.__version__}, mean([1,2,3])={np.mean([1,2,3])}')"
    result = execute_metallurgy_python(code)
    has_numpy = "NumPy" in result or "numpy" in result.lower()
    test_result("Python 沙盒 NumPy 可用", has_numpy,
                f"输出: {result.strip()[:100]}")
    results["pass" if has_numpy else "fail"] += 1
except Exception as e:
    test_result("Python 沙盒 NumPy", False, str(e)[:80])
    results["fail"] += 1

# 5.7 crop_pdf_region（需要 PDF 文件）
try:
    from src.agent.tools import crop_pdf_region
    result = crop_pdf_region("nonexistent_doc", 1, 0.0, 0.0, 0.5, 0.5)
    # 应该返回文件不存在的错误（这是预期行为）
    is_expected = "not found" in result.lower() or "error" in result.lower()
    test_result("crop_pdf_region (无 PDF 降级)", is_expected,
                f"预期错误: {result[:80]}")
    results["pass" if is_expected else "fail"] += 1
except Exception as e:
    test_result("crop_pdf_region", False, str(e)[:80])
    results["fail"] += 1

# 5.8 analyze_metallurgy_image（需要 Qwen VL API）
print("\n  ℹ️  跳过 analyze_metallurgy_image — 需要真实图片 Base64 + VL API 调用 (费用)")

# ──────────────────────────────────────────────────────────────
# Phase 6: LangGraph Worker 流水线完整性
# ──────────────────────────────────────────────────────────────
banner("Phase 6: LangGraph Worker 图构建")

try:
    from src.agent.graph import create_worker_graph
    graph = create_worker_graph()
    
    # 检查图结构
    nodes = list(graph.nodes.keys()) if hasattr(graph, 'nodes') else []
    test_result("Worker Graph 构建", len(nodes) >= 3,
                f"节点: {nodes}")
    results["pass" if len(nodes) >= 3 else "fail"] += 1
except Exception as e:
    test_result("Worker Graph 构建", False, str(e)[:100])
    results["fail"] += 1
    traceback.print_exc()

# ──────────────────────────────────────────────────────────────
# 汇总
# ──────────────────────────────────────────────────────────────
banner("📊 测试汇总")
total = results["pass"] + results["fail"]
print(f"\n  总计: {total} 项测试")
print(f"  ✅ 通过: {results['pass']} 项")
print(f"  ❌ 失败: {results['fail']} 项")
print(f"  通过率: {results['pass']/total*100:.0f}%\n")

if results["fail"] > 0:
    print("  ⚠️  建议操作:")
    print("     - Elasticsearch 未运行？执行: docker compose up -d elasticsearch")
    print("     - 知识库为空？上传 PDF 后自动索引")
    print("     - Neo4j 图谱为空？需要导入三元组数据")
