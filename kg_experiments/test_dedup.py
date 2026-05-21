"""
知识图谱去重测试 — Embedding 初筛 + LLM 逐对确认

测试流程：
  1. 从 Neo4j 导出所有节点
  2. 用 Dashscope Embedding 对节点名称向量化
  3. 找出余弦相似度 > THRESHOLD 且同标签的候选合并对
  4. 用 qwen-turbo 逐对确认是否为同一概念
  5. 输出合并报告（不实际修改 Neo4j）
"""

import sys
import os
import json
from itertools import combinations

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# 清除代理
for key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(key, None)

from src.core.config import settings

# ─── 配置 ────────────────────────────────────────────
SIMILARITY_THRESHOLD = 0.85   # Embedding 余弦相似度阈值
DRY_RUN = True                # True = 只输出报告不修改 Neo4j


def step1_export_nodes():
    """从 Neo4j 导出所有节点"""
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    with driver.session() as session:
        result = session.run("""
            MATCH (n)
            RETURN n.name AS name, n.id AS id, labels(n)[0] AS label
            ORDER BY labels(n)[0], n.name
        """)
        nodes = [dict(r) for r in result]
    driver.close()
    print(f"[Step 1] 导出 {len(nodes)} 个节点")
    return nodes


def step2_embed_nodes(nodes):
    """用 Dashscope Embedding 对节点名称向量化"""
    import numpy as np
    from openai import OpenAI

    client = OpenAI(
        api_key=settings.QWEN_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    names = [n["name"] for n in nodes]
    print(f"[Step 2] 对 {len(names)} 个名称做 Embedding...")

    # Dashscope embedding 一次最多 10 个
    BATCH_SIZE = 10
    all_embeddings = []
    for i in range(0, len(names), BATCH_SIZE):
        batch = names[i:i + BATCH_SIZE]
        resp = client.embeddings.create(
            model="text-embedding-v3",
            input=batch,
        )
        batch_embeds = [item.embedding for item in resp.data]
        all_embeddings.extend(batch_embeds)
        print(f"  Batch {i // BATCH_SIZE + 1}: {len(batch)} items embedded")

    embeddings = np.array(all_embeddings)
    # L2 归一化（计算余弦相似度）
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embeddings_norm = embeddings / norms

    print(f"[Step 2] Embedding 完成: shape={embeddings_norm.shape}")
    return embeddings_norm


def step3_find_candidates(nodes, embeddings):
    """找出余弦相似度 > 阈值且同标签的候选合并对"""
    import numpy as np

    # 计算全量余弦相似度矩阵
    sim_matrix = embeddings @ embeddings.T

    candidates = []
    n = len(nodes)
    for i in range(n):
        for j in range(i + 1, n):
            # 条件1：同标签
            if nodes[i]["label"] != nodes[j]["label"]:
                continue
            # 条件2：相似度 > 阈值
            sim = float(sim_matrix[i, j])
            if sim >= SIMILARITY_THRESHOLD:
                # 条件3：排除完全相同的 id（已经合并的）
                if nodes[i]["id"] == nodes[j]["id"]:
                    continue
                candidates.append({
                    "node_a": nodes[i],
                    "node_b": nodes[j],
                    "similarity": sim,
                })

    # 按相似度降序排列
    candidates.sort(key=lambda x: -x["similarity"])
    print(f"[Step 3] 找到 {len(candidates)} 个候选合并对 (阈值={SIMILARITY_THRESHOLD})")
    for c in candidates[:10]:
        print(f"  {c['similarity']:.4f} | [{c['node_a']['label']}] \"{c['node_a']['name']}\" ↔ \"{c['node_b']['name']}\"")
    if len(candidates) > 10:
        print(f"  ... 还有 {len(candidates) - 10} 对")
    return candidates


def step4_llm_verify(candidates):
    """用 qwen-turbo 逐对确认是否为同一概念"""
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage

    if not candidates:
        print("[Step 4] 无候选对，跳过 LLM 验证")
        return []

    llm = ChatOpenAI(
        model="qwen-turbo",
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
        temperature=0.0,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    # 批量验证：一次性把所有候选对发给 LLM
    pairs_text = "\n".join(
        f'{i+1}. [{c["node_a"]["label"]}] "{c["node_a"]["name"]}" vs "{c["node_b"]["name"]}" (相似度:{c["similarity"]:.3f})'
        for i, c in enumerate(candidates)
    )

    prompt = f"""你是一位冶金学领域的知识图谱专家。以下是从图谱中检测到的若干疑似同义实体对。
请逐一判断每对实体在冶金学语境下是否指代同一个概念。

【判断原则 — 宁漏勿错】：
1. 如果两个名称只是同一事物的不同写法/简称（如 "304/45钢复合螺栓" vs "304/45双金属复合螺栓"），判定 YES
2. 如果两个名称虽然相似但指代不同的物理实体（如 "不锈钢覆层" vs "不锈钢覆层板"，一个是涂层一个是板材），判定 NO
3. 如果名称中包含不同的数值/参数（如 "步距1μm" vs "步距4μm"），判定 NO
4. 如果不确定，判定 NO（宁可漏合并也不要错合并）

候选对列表：
{pairs_text}

请输出 JSON 格式：{{"results": [{{"pair_id": 1, "verdict": "YES/NO", "canonical": "保留的规范名称(仅YES时填写)", "reason": "简要理由"}}]}}"""

    print(f"[Step 4] 将 {len(candidates)} 个候选对发送给 qwen-turbo 验证...")
    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        data = json.loads(response.content)
        results = data.get("results", [])
    except Exception as e:
        print(f"  LLM 输出解析失败: {e}")
        print(f"  原始输出: {response.content[:500]}")
        return []

    # 合并验证结果到候选对
    confirmed = []
    for r in results:
        idx = r.get("pair_id", 0) - 1
        if 0 <= idx < len(candidates) and r.get("verdict", "").upper() == "YES":
            merge_entry = {
                **candidates[idx],
                "canonical": r.get("canonical", candidates[idx]["node_a"]["name"]),
                "reason": r.get("reason", ""),
            }
            confirmed.append(merge_entry)

    rejected_count = len(candidates) - len(confirmed)
    print(f"[Step 4] LLM 确认结果: {len(confirmed)} 对合并 / {rejected_count} 对拒绝")
    return confirmed


def step5_report(nodes, candidates, confirmed):
    """输出最终合并报告"""
    print("\n" + "=" * 70)
    print("  知识图谱去重测试报告")
    print("=" * 70)
    print(f"\n基线节点数:          {len(nodes)}")
    print(f"Embedding 候选对:    {len(candidates)} (阈值={SIMILARITY_THRESHOLD})")
    print(f"LLM 确认合并对:      {len(confirmed)}")
    print(f"LLM 拒绝合并对:      {len(candidates) - len(confirmed)}")
    print(f"预计合并后节点数:    ~{len(nodes) - len(confirmed)}")
    print(f"节点减少比例:        {len(confirmed) / len(nodes) * 100:.1f}%")

    if confirmed:
        print(f"\n--- 确认合并的实体对 ({len(confirmed)}) ---")
        for i, c in enumerate(confirmed):
            print(f"  {i+1}. [{c['node_a']['label']}] \"{c['node_a']['name']}\" → \"{c['canonical']}\"")
            print(f"     (原: \"{c['node_b']['name']}\" | 相似度:{c['similarity']:.3f} | {c['reason']})")

    # 找出被拒绝的对（验证防过度合并是否生效）
    confirmed_ids = {(c['node_a']['id'], c['node_b']['id']) for c in confirmed}
    rejected = [c for c in candidates if (c['node_a']['id'], c['node_b']['id']) not in confirmed_ids]
    if rejected:
        print(f"\n--- LLM 拒绝合并的实体对 ({len(rejected)}) ---")
        for i, c in enumerate(rejected[:15]):
            print(f"  {i+1}. [{c['node_a']['label']}] \"{c['node_a']['name']}\" ↔ \"{c['node_b']['name']}\" (sim={c['similarity']:.3f})")

    print("\n" + "=" * 70)
    return confirmed


def main():
    print("=" * 70)
    print("  知识图谱去重测试 — Embedding + LLM 两步验证")
    print("=" * 70)

    # Step 1: 导出节点
    nodes = step1_export_nodes()
    if not nodes:
        print("Neo4j 中无节点，退出")
        return

    # Step 2: Embedding 向量化
    embeddings = step2_embed_nodes(nodes)

    # Step 3: 找候选对
    candidates = step3_find_candidates(nodes, embeddings)

    # Step 4: LLM 验证
    confirmed = step4_llm_verify(candidates)

    # Step 5: 报告
    step5_report(nodes, candidates, confirmed)


if __name__ == "__main__":
    main()
