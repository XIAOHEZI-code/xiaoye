"""
知识图谱去重路由 — Embedding 初筛 + LLM 逐对确认

提供两个端点：
  POST /api/v1/graph/dedup/scan    — 扫描候选合并对（只读，不修改图谱）
  POST /api/v1/graph/dedup/apply   — 执行合并（修改 Neo4j）
"""

import json
import os
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

from src.core.config import settings
from src.core.logger import setup_logger

logger = setup_logger("xiaoye.graph_dedup")

router = APIRouter()

# ─── 配置 ────────────────────────────────────────────
SIMILARITY_THRESHOLD = 0.85


def _clear_proxy():
    for key in ["http_proxy", "https_proxy", "all_proxy",
                 "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
        os.environ.pop(key, None)


def _export_nodes():
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
    return nodes


def _embed_names(names: list[str]) -> "np.ndarray":
    """用 Dashscope Embedding 对名称列表向量化"""
    import numpy as np
    from openai import OpenAI

    client = OpenAI(
        api_key=settings.QWEN_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    BATCH_SIZE = 10
    all_embeddings = []
    for i in range(0, len(names), BATCH_SIZE):
        batch = names[i:i + BATCH_SIZE]
        resp = client.embeddings.create(model="text-embedding-v3", input=batch)
        all_embeddings.extend([item.embedding for item in resp.data])

    embeddings = np.array(all_embeddings)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return embeddings / norms


def _find_candidates(nodes, embeddings):
    """找出余弦相似度 > 阈值且同标签的候选对"""
    import numpy as np

    sim_matrix = embeddings @ embeddings.T
    candidates = []
    n = len(nodes)
    for i in range(n):
        for j in range(i + 1, n):
            if nodes[i]["label"] != nodes[j]["label"]:
                continue
            sim = float(sim_matrix[i, j])
            if sim >= SIMILARITY_THRESHOLD and nodes[i]["id"] != nodes[j]["id"]:
                candidates.append({
                    "node_a": nodes[i],
                    "node_b": nodes[j],
                    "similarity": round(sim, 4),
                })
    candidates.sort(key=lambda x: -x["similarity"])
    return candidates


def _llm_verify(candidates):
    """用 qwen-turbo 逐对确认是否为同一概念"""
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage

    if not candidates:
        return []

    llm = ChatOpenAI(
        model="qwen-turbo",
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
        temperature=0.0,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    pairs_text = "\n".join(
        f'{i+1}. [{c["node_a"]["label"]}] "{c["node_a"]["name"]}" vs "{c["node_b"]["name"]}" (相似度:{c["similarity"]})'
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

    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        data = json.loads(response.content)
        results = data.get("results", [])
    except Exception as e:
        logger.error(f"LLM output parse failed: {e}")
        return []

    confirmed = []
    for r in results:
        idx = r.get("pair_id", 0) - 1
        if 0 <= idx < len(candidates) and r.get("verdict", "").upper() == "YES":
            confirmed.append({
                **candidates[idx],
                "canonical": r.get("canonical", candidates[idx]["node_a"]["name"]),
                "reason": r.get("reason", ""),
            })

    return confirmed


def _apply_merges(confirmed):
    """在 Neo4j 中执行合并：把 node_b 的关系迁移到 node_a，然后删除 node_b"""
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    merged_count = 0
    with driver.session() as session:
        for entry in confirmed:
            canonical_id = entry["node_a"]["id"]
            duplicate_id = entry["node_b"]["id"]
            label = entry["node_a"]["label"]
            canonical_name = entry["canonical"]

            # 迁移入边：把指向 duplicate 的关系改为指向 canonical
            session.run(f"""
                MATCH (dup:{label} {{id: $dup_id}})<-[r]-(src)
                MATCH (canon:{label} {{id: $canon_id}})
                WHERE src <> canon
                CREATE (src)-[r2:MERGED_FROM]->(canon)
                SET r2 = properties(r)
                DELETE r
            """, dup_id=duplicate_id, canon_id=canonical_id)

            # 迁移出边：把从 duplicate 出发的关系改为从 canonical 出发
            session.run(f"""
                MATCH (dup:{label} {{id: $dup_id}})-[r]->(tgt)
                MATCH (canon:{label} {{id: $canon_id}})
                WHERE tgt <> canon
                CREATE (canon)-[r2:MERGED_FROM]->(tgt)
                SET r2 = properties(r)
                DELETE r
            """, dup_id=duplicate_id, canon_id=canonical_id)

            # 删除 duplicate 节点
            session.run(f"""
                MATCH (dup:{label} {{id: $dup_id}})
                DETACH DELETE dup
            """, dup_id=duplicate_id)

            # 更新 canonical 节点的名称
            session.run(f"""
                MATCH (n:{label} {{id: $canon_id}})
                SET n.name = $name
            """, canon_id=canonical_id, name=canonical_name)

            merged_count += 1
            logger.info(f"[Dedup] Merged: \"{entry['node_b']['name']}\" → \"{canonical_name}\"")

    driver.close()
    return merged_count


# ===================================================================
# API Endpoints
# ===================================================================


@router.post("/graph/dedup/scan")
async def scan_duplicates():
    """
    扫描知识图谱中的疑似重复实体（只读，不修改图谱）。

    流程：Embedding 初筛 → LLM 逐对确认 → 返回报告
    """
    _clear_proxy()

    nodes = _export_nodes()
    if not nodes:
        return {"status": "empty", "total_nodes": 0, "candidates": 0, "confirmed": []}

    names = [n["name"] for n in nodes]
    embeddings = _embed_names(names)
    candidates = _find_candidates(nodes, embeddings)
    confirmed = _llm_verify(candidates)

    return {
        "status": "ok",
        "total_nodes": len(nodes),
        "candidates_found": len(candidates),
        "confirmed_merges": len(confirmed),
        "rejected": len(candidates) - len(confirmed),
        "estimated_after": len(nodes) - len(confirmed),
        "merges": [
            {
                "from": c["node_b"]["name"],
                "to": c["canonical"],
                "label": c["node_a"]["label"],
                "similarity": c["similarity"],
                "reason": c["reason"],
            }
            for c in confirmed
        ],
    }


@router.post("/graph/dedup/apply")
async def apply_dedup():
    """
    执行知识图谱去重：扫描 + 合并（修改 Neo4j）。

    1. Embedding 初筛候选对
    2. LLM 逐对确认
    3. 在 Neo4j 中执行合并（迁移关系 + 删除冗余节点）
    """
    _clear_proxy()

    nodes = _export_nodes()
    if not nodes:
        return {"status": "empty", "merged": 0}

    names = [n["name"] for n in nodes]
    embeddings = _embed_names(names)
    candidates = _find_candidates(nodes, embeddings)
    confirmed = _llm_verify(candidates)

    if not confirmed:
        return {
            "status": "clean",
            "message": "图谱无需去重",
            "total_nodes": len(nodes),
            "candidates_scanned": len(candidates),
            "merged": 0,
        }

    merged_count = _apply_merges(confirmed)

    # 查询合并后的节点数
    after_nodes = _export_nodes()

    return {
        "status": "merged",
        "total_before": len(nodes),
        "total_after": len(after_nodes),
        "candidates_scanned": len(candidates),
        "merged": merged_count,
        "details": [
            {
                "from": c["node_b"]["name"],
                "to": c["canonical"],
                "label": c["node_a"]["label"],
                "reason": c["reason"],
            }
            for c in confirmed
        ],
    }
