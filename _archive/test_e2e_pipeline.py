"""
小冶 (Xiaoye) 全链路端到端测试
==================================
测试完整工具链：ES 索引/检索 → Neo4j → Python 沙盒 → VLM 视觉分析 → LangGraph Worker
"""

import os
import sys
import json
import time
import asyncio
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 清除代理
for key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(key, None)

from src.core.config import settings
os.environ["OPENAI_API_KEY"] = settings.QWEN_API_KEY or ""
os.environ["OPENAI_API_BASE"] = settings.QWEN_BASE_URL

results = {"pass": 0, "fail": 0, "skip": 0}

def banner(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")

def test_result(name: str, success: bool, detail: str = ""):
    global results
    icon = "✅" if success else "❌"
    print(f"  {icon} {name}" + (f" — {detail}" if detail else ""))
    results["pass" if success else "fail"] += 1
    return success

def skip_result(name: str, detail: str = ""):
    global results
    print(f"  ⏭️  {name}" + (f" — {detail}" if detail else ""))
    results["skip"] += 1


# ================================================================
#  E2E-1: Elasticsearch 索引 + 混合检索
# ================================================================
banner("E2E-1: Elasticsearch 索引 → 混合检索")

try:
    from elasticsearch import Elasticsearch
    from langchain_openai import OpenAIEmbeddings

    es = Elasticsearch(settings.ELASTICSEARCH_URL)
    info = es.info()
    test_result("ES 连接", True, f"版本 {info['version']['number']}")

    # 创建测试索引（如果不存在）
    test_index = "metallurgy_chunks"
    if not es.indices.exists(index=test_index):
        es.indices.create(index=test_index, body={
            "mappings": {
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "doc_id": {"type": "keyword"},
                    "content": {"type": "text", "analyzer": "standard"},
                    "source_type": {"type": "keyword"},
                    "source_pdf_id": {"type": "keyword"},
                    "page_number": {"type": "integer"},
                    "bbox": {"type": "object", "enabled": False},
                    "image_uri": {"type": "keyword"},
                    "chunk_type": {"type": "keyword"},
                    "vector": {
                        "type": "dense_vector",
                        "dims": 1024,
                        "index": True,
                        "similarity": "cosine"
                    }
                }
            }
        })
        test_result("创建 metallurgy_chunks 索引", True, "新建")
    else:
        # 检查有多少文档
        count = es.count(index=test_index)["count"]
        test_result("metallurgy_chunks 索引已存在", True, f"已有 {count} 个文档")

    # 插入一条测试文档
    embeddings = OpenAIEmbeddings(
        model=settings.QWEN_EMBEDDING_MODEL,
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
        check_embedding_ctx_length=False,
    )

    test_text = "高炉炼铁过程中，炉渣碱度（CaO/SiO2 比值）是控制脱硫效率的关键工艺参数。碱度控制在 1.05-1.15 范围内可获得最佳脱硫效果。当碱度过低时，硫容量不足；碱度过高则导致渣流动性变差。"
    test_vector = embeddings.embed_query(test_text)
    test_result("Qwen Embedding 向量生成", len(test_vector) == 1024,
                f"维度: {len(test_vector)}")

    test_doc = {
        "chunk_id": "e2e_test_chunk_001",
        "doc_id": "e2e_test_doc",
        "content": test_text,
        "source_type": "text",
        "source_pdf_id": "test_blast_furnace.pdf",
        "page_number": 5,
        "bbox": {"x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.4},
        "image_uri": "",
        "chunk_type": "text_chunk",
        "vector": test_vector,
    }

    es.index(index=test_index, id="e2e_test_001", document=test_doc, refresh=True)
    test_result("测试文档写入 ES", True, "e2e_test_001")

    # 使用 search_metallurgy_text 工具进行检索
    from src.agent.tools import search_metallurgy_text
    search_result = search_metallurgy_text("高炉脱硫碱度控制", top_k=3)
    found = "碱度" in search_result or "脱硫" in search_result
    test_result("search_metallurgy_text 混合检索", found,
                f"结果片段: {search_result[:120]}...")

except Exception as e:
    test_result("E2E-1 ES Pipeline", False, f"{type(e).__name__}: {str(e)[:100]}")
    traceback.print_exc()

# ================================================================
#  E2E-2: Neo4j 知识图谱 — 写入三元组 + 查询
# ================================================================
banner("E2E-2: Neo4j 知识图谱 — 写入三元组 + 查询")

try:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )

    # 写入测试三元组
    with driver.session() as session:
        # 清理旧测试数据
        session.run("MATCH (n:Entity {id: 'e2e_test_碱度'}) DETACH DELETE n")
        session.run("MATCH (n:Entity {id: 'e2e_test_脱硫效率'}) DETACH DELETE n")
        session.run("MATCH (n:Entity {id: 'e2e_test_渣流动性'}) DETACH DELETE n")

        # 创建实体和关系
        session.run("""
            MERGE (a:Entity {id: 'e2e_test_碱度', name: '炉渣碱度'})
            MERGE (b:Entity {id: 'e2e_test_脱硫效率', name: '脱硫效率'})
            MERGE (c:Entity {id: 'e2e_test_渣流动性', name: '渣流动性'})
            MERGE (a)-[:RELATION {type: '正相关影响', source_doc: 'test_doc'}]->(b)
            MERGE (a)-[:RELATION {type: '负相关影响（过高时）', source_doc: 'test_doc'}]->(c)
        """)
        test_result("写入三元组到 Neo4j", True, "碱度→脱硫效率, 碱度→渣流动性")

        # 查询关系
        result = session.run("""
            MATCH (a:Entity {id: 'e2e_test_碱度'})-[r:RELATION]->(b:Entity)
            RETURN a.name AS subject, r.type AS relation, b.name AS object
        """)
        records = list(result)
        test_result("Neo4j 关系查询", len(records) == 2,
                    f"查到 {len(records)} 条关系: {[(r['subject'], r['relation'], r['object']) for r in records]}")

        # 通过 graph tool 查询
        from src.agent.tools import search_metallurgy_graph_relations
        graph_result = search_metallurgy_graph_relations("e2e_test_碱度")
        found_graph = "脱硫" in graph_result or "流动性" in graph_result
        test_result("search_metallurgy_graph_relations 工具", found_graph,
                    f"结果: {graph_result[:150]}")

        # 通过 trace_impact_path 查询
        from src.agent.tools import trace_metallurgy_impact_path
        path_result = trace_metallurgy_impact_path("e2e_test_碱度")
        found_path = "脱硫" in path_result or "path" in path_result.lower()
        test_result("trace_metallurgy_impact_path 工具", found_path,
                    f"结果: {path_result[:150]}")

    driver.close()

except Exception as e:
    test_result("E2E-2 Neo4j Pipeline", False, f"{type(e).__name__}: {str(e)[:100]}")
    traceback.print_exc()

# ================================================================
#  E2E-3: Python 沙盒 — 有状态计算 + 图表生成
# ================================================================
banner("E2E-3: Python 沙盒 — 有状态计算 + 图表生成")

try:
    from src.agent.tools import execute_metallurgy_python

    # 3a: 基础计算
    r1 = execute_metallurgy_python("import numpy as np; x = np.linspace(0, 10, 100); print(f'x shape: {x.shape}, mean: {x.mean():.2f}')")
    test_result("沙盒 NumPy 计算", "shape" in r1 and "mean" in r1, f"输出: {r1.strip()}")

    # 3b: 跨轮次有状态 — 上一轮的 x 变量应该还在
    r2 = execute_metallurgy_python("print(f'x still alive: {x.shape}, max: {x.max():.1f}')")
    test_result("沙盒跨轮次状态保持", "still alive" in r2, f"输出: {r2.strip()}")

    # 3c: 冶金热力学计算示例
    code_thermo = """
import numpy as np

# Gibbs 自由能计算：FeO + C → Fe + CO
# ΔG = ΔH - T*ΔS (简化模型)
T = np.arange(800, 1800, 100)  # 温度范围 800-1700K
delta_H = 152800  # J/mol (吸热反应)
delta_S = 151.5   # J/(mol·K)
delta_G = delta_H - T * delta_S

# 找到 ΔG=0 的平衡温度
T_eq = delta_H / delta_S
print(f"FeO + C → Fe + CO 反应:")
print(f"平衡温度: {T_eq:.0f} K ({T_eq-273:.0f} °C)")
print(f"1200K 时 ΔG = {delta_H - 1200*delta_S:.0f} J/mol ({'自发' if delta_H - 1200*delta_S < 0 else '非自发'})")
print(f"1100K 时 ΔG = {delta_H - 1100*delta_S:.0f} J/mol ({'自发' if delta_H - 1100*delta_S < 0 else '非自发'})")
"""
    r3 = execute_metallurgy_python(code_thermo)
    test_result("冶金热力学 Gibbs 计算", "平衡温度" in r3 and "自发" in r3,
                f"输出: {r3.strip()[:200]}")

    # 3d: Matplotlib 图表生成
    code_plot = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

T = np.arange(800, 1800, 10)
delta_G = 152800 - T * 151.5

fig, ax = plt.subplots(figsize=(8, 5))
ax.plot(T, delta_G/1000, 'b-', linewidth=2)
ax.axhline(y=0, color='r', linestyle='--', alpha=0.7)
ax.set_xlabel('Temperature (K)', fontsize=12)
ax.set_ylabel('ΔG (kJ/mol)', fontsize=12)
ax.set_title('FeO + C → Fe + CO: Gibbs Free Energy vs Temperature', fontsize=14)
ax.grid(True, alpha=0.3)
ax.fill_between(T, delta_G/1000, 0, where=delta_G<0, alpha=0.15, color='green', label='Spontaneous')
ax.fill_between(T, delta_G/1000, 0, where=delta_G>=0, alpha=0.15, color='red', label='Non-spontaneous')
ax.legend()
plt.tight_layout()
plt.show()
print("Chart generated successfully")
"""
    r4 = execute_metallurgy_python(code_plot)
    has_chart = "Image" in r4 or "Chart generated" in r4
    test_result("Matplotlib 图表生成 + Base64 拦截", has_chart,
                f"输出片段: {r4[:150]}")

except Exception as e:
    test_result("E2E-3 Python 沙盒", False, f"{type(e).__name__}: {str(e)[:100]}")
    traceback.print_exc()

# ================================================================
#  E2E-4: VLM 视觉大模型分析 (Qwen3-VL)
# ================================================================
banner("E2E-4: Qwen3-VL 视觉大模型分析")

try:
    # 生成一个冶金相关的测试图片（matplotlib 绘制一张相图风格的图）
    code_gen_img = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import base64
import io

# 绘制一张简化的 Fe-C 相图局部
fig, ax = plt.subplots(figsize=(8, 6))

# 液相线
T_liq = [1538, 1493, 1400, 1300, 1200, 1148]
C_liq = [0, 0.09, 0.3, 0.6, 0.9, 1.2]
ax.plot(C_liq, T_liq, 'r-', linewidth=2, label='Liquidus')

# 固相线
T_sol = [1538, 1493, 1480, 1470, 1460, 1148]
C_sol = [0, 0.09, 0.15, 0.2, 0.25, 0.5]
ax.plot(C_sol, T_sol, 'b-', linewidth=2, label='Solidus')

# 共晶线
ax.axhline(y=1148, color='green', linestyle='--', alpha=0.7, label='Eutectic (1148°C)')

# 标注
ax.annotate('δ-Fe', xy=(0.02, 1520), fontsize=14, fontweight='bold')
ax.annotate('γ-Fe\\n(Austenite)', xy=(0.1, 1300), fontsize=12)
ax.annotate('L (Liquid)', xy=(0.5, 1400), fontsize=12, color='red')
ax.annotate('γ + L', xy=(0.35, 1250), fontsize=11, style='italic')

ax.set_xlabel('Carbon Content (wt%)', fontsize=13)
ax.set_ylabel('Temperature (°C)', fontsize=13)
ax.set_title('Fe-C Phase Diagram (Simplified)', fontsize=15, fontweight='bold')
ax.set_xlim(0, 1.5)
ax.set_ylim(1100, 1560)
ax.legend(loc='upper right')
ax.grid(True, alpha=0.3)
plt.tight_layout()

# 转为 Base64
buf = io.BytesIO()
fig.savefig(buf, format='png', dpi=150)
buf.seek(0)
img_b64 = base64.b64encode(buf.read()).decode('utf-8')
plt.close(fig)

print(f"IMG_BASE64_START:{img_b64}:IMG_BASE64_END")
"""
    r_img = execute_metallurgy_python(code_gen_img)
    
    # 提取 Base64
    if "IMG_BASE64_START:" in r_img and ":IMG_BASE64_END" in r_img:
        img_b64 = r_img.split("IMG_BASE64_START:")[1].split(":IMG_BASE64_END")[0]
        test_result("生成冶金测试图片", len(img_b64) > 1000,
                    f"Base64 长度: {len(img_b64)} chars")
        
        # 调用 VLM 分析
        from src.agent.tools import analyze_metallurgy_image
        print("\n  ⏳ 正在调用 Qwen3-VL 分析冶金图片（约 5-15 秒）...")
        vlm_result = analyze_metallurgy_image(
            image_base64=img_b64,
            caption="图1: 简化 Fe-C 相图（局部）",
            context_above="在高炉炼铁和转炉炼钢过程中，铁碳相图是理解凝固和相变的基础。",
            context_below="从相图可以看出，共晶温度约为 1148°C，对应碳含量约 4.3%。"
        )
        
        vlm_data = json.loads(vlm_result)
        has_category = vlm_data.get("category", "") != ""
        has_desc = len(vlm_data.get("description", "")) > 30
        test_result("Qwen3-VL 图像分析", has_category and has_desc,
                    f"分类: {vlm_data.get('category', 'N/A')}")
        test_result("VLM 子分类", bool(vlm_data.get("sub_category")),
                    f"子分类: {vlm_data.get('sub_category', 'N/A')}")
        test_result("VLM 描述质量", has_desc,
                    f"描述: {vlm_data.get('description', '')[:100]}...")
        test_result("VLM 关键指标提取", isinstance(vlm_data.get("key_metrics"), list),
                    f"指标: {vlm_data.get('key_metrics', [])}")
    else:
        test_result("生成冶金测试图片", False, f"未能提取 Base64: {r_img[:100]}")

except Exception as e:
    test_result("E2E-4 VLM Pipeline", False, f"{type(e).__name__}: {str(e)[:100]}")
    traceback.print_exc()

# ================================================================
#  E2E-5: ToolSearchEngine — 渐进式工具加载模拟
# ================================================================
banner("E2E-5: 渐进式工具加载 (LLM 视角模拟)")

try:
    from src.agent.tools import search_available_tools

    # 模拟 LLM 第一步：用户问了计算相关的问题，LLM 先搜索工具
    r_search = search_available_tools("计算 热力学 python", max_results=3)
    test_result("LLM 搜索工具 '计算 热力学'", "execute_metallurgy_python" in r_search,
                f"结果: {r_search[:150]}...")

    # 模拟 LLM 第二步：精确选取
    r_select = search_available_tools("select:execute_metallurgy_python,crop_pdf_region", max_results=5)
    has_both = "execute_metallurgy_python" in r_select and "crop_pdf_region" in r_select
    test_result("LLM 精确选取多工具", has_both,
                f"结果: {r_select[:150]}...")

    # 模拟 LLM 第三步：搜索图谱工具
    r_graph = search_available_tools("+graph 关系", max_results=3)
    test_result("LLM 搜索图谱工具", "graph" in r_graph.lower(),
                f"结果: {r_graph[:150]}...")

except Exception as e:
    test_result("E2E-5 工具搜索", False, f"{type(e).__name__}: {str(e)[:100]}")

# ================================================================
#  E2E-6: LangGraph Worker 图 — 端到端 Agent 推理
# ================================================================
banner("E2E-6: LangGraph Worker 端到端推理")

try:
    from src.agent.graph import create_worker_graph
    from langchain_core.messages import HumanMessage

    graph = create_worker_graph()

    # 构建输入状态
    test_query = "高炉炼铁中炉渣碱度如何影响脱硫效率？请结合知识库检索回答。"
    initial_state = {
        "messages": [HumanMessage(content=test_query)],
        "step_description": test_query,
    }

    print(f"\n  ⏳ LangGraph Worker 正在推理（约 10-30 秒）...")
    print(f"     输入: {test_query}")

    # 运行 Worker Graph
    config = {"recursion_limit": 16}
    final_state = graph.invoke(initial_state, config=config)

    # 检查输出
    messages = final_state.get("messages", [])
    last_msg = messages[-1] if messages else None

    if last_msg:
        content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
        has_answer = len(content) > 50
        test_result("LangGraph 推理完成", has_answer,
                    f"回答长度: {len(content)} 字符")
        test_result("回答包含领域知识", "碱度" in content or "脱硫" in content,
                    f"回答片段: {content[:150]}...")

        # 检查工具调用链
        tool_calls = [m for m in messages if hasattr(m, 'type') and m.type == 'tool']
        test_result("Agent 调用了工具", len(tool_calls) >= 1,
                    f"工具调用次数: {len(tool_calls)}")
    else:
        test_result("LangGraph 推理", False, "无输出消息")

except Exception as e:
    test_result("E2E-6 LangGraph Worker", False, f"{type(e).__name__}: {str(e)[:100]}")
    traceback.print_exc()

# ================================================================
#  E2E-7: SSE 事件推送验证 (Redis PubSub)
# ================================================================
banner("E2E-7: SSE 事件推送验证")

try:
    import redis as sync_redis
    import threading

    rc = sync_redis.from_url(settings.CELERY_BROKER_URL)
    pubsub = rc.pubsub()
    pubsub.subscribe("xiaoye_sse")

    received = []

    def listener():
        for msg in pubsub.listen():
            if msg["type"] == "message":
                received.append(json.loads(msg["data"]))
                if len(received) >= 2:
                    break

    t = threading.Thread(target=listener, daemon=True)
    t.start()

    # 发布测试事件
    time.sleep(0.3)
    rc.publish("xiaoye_sse", json.dumps({
        "task_id": "e2e_test",
        "patch": "Hello from E2E test!",
    }))
    rc.publish("xiaoye_sse", json.dumps({
        "task_id": "e2e_test",
        "type": "reasoning",
        "thinking": "Testing SSE pipeline...",
    }))

    t.join(timeout=3)
    pubsub.unsubscribe()
    rc.close()

    test_result("Redis PubSub SSE 推送", len(received) >= 2,
                f"收到 {len(received)} 条事件")
    if received:
        test_result("SSE 事件格式正确", "task_id" in received[0],
                    f"事件: {received[0]}")

except Exception as e:
    test_result("E2E-7 SSE", False, f"{type(e).__name__}: {str(e)[:100]}")

# ================================================================
#  清理测试数据
# ================================================================
banner("清理测试数据")

try:
    # 清理 ES 测试数据
    es = Elasticsearch(settings.ELASTICSEARCH_URL)
    es.delete(index="metallurgy_chunks", id="e2e_test_001", ignore=[404])
    print("  🧹 已清理 ES 测试文档")

    # 清理 Neo4j 测试数据
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    with driver.session() as session:
        session.run("MATCH (n:Entity) WHERE n.id STARTS WITH 'e2e_test_' DETACH DELETE n")
    driver.close()
    print("  🧹 已清理 Neo4j 测试三元组")
except Exception as e:
    print(f"  ⚠️ 清理失败 (非致命): {e}")

# ================================================================
#  汇总
# ================================================================
banner("📊 全链路测试汇总")
total = results["pass"] + results["fail"]
print(f"\n  总计: {total} 项测试 (跳过 {results['skip']} 项)")
print(f"  ✅ 通过: {results['pass']} 项")
print(f"  ❌ 失败: {results['fail']} 项")
rate = results['pass'] / total * 100 if total > 0 else 0
print(f"  通过率: {rate:.0f}%")

if rate == 100:
    print("\n  🎉 全部测试通过！系统可以上线演示。")
elif rate >= 80:
    print("\n  👍 核心功能正常，少量边缘场景待修复。")
elif rate >= 50:
    print("\n  ⚠️  主要功能有问题，需要排查修复。")
else:
    print("\n  🚨 系统存在严重问题，请检查基础设施。")
print()
