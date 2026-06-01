import pytest
import numpy as np

def find_candidates(nodes, embeddings, threshold):
    """
    找出余弦相似度 > 阈值且同标签的候选合并对。
    (注：此算法提取自原 legacy_dedup.py，未来可迁移至 src/kg/deduplicator.py)
    """
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
            if sim >= threshold:
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
    return candidates

def test_find_candidates_logic():
    """测试基于余弦相似度矩阵的实体合并候选对筛选算法"""
    
    nodes = [
        {"id": "n1", "name": "304不锈钢", "label": "Material"},
        {"id": "n2", "name": "304钢", "label": "Material"},     # 相似且同标签 -> 应该被选中
        {"id": "n3", "name": "高炉", "label": "Equipment"},      # 不相似
        {"id": "n4", "name": "304不锈钢", "label": "Process"},   # 相似但标签不同 -> 应该被跳过
        {"id": "n1", "name": "304不锈钢", "label": "Material"},  # ID 完全相同 (模拟自己和自己) -> 应该被跳过
    ]
    
    # 构造归一化的假 Embeddings (L2 Norm = 1)
    vec_a = np.array([1.0, 0.0, 0.0]) # 304相关
    vec_b = np.array([0.0, 1.0, 0.0]) # 高炉相关
    
    embeddings = np.array([
        vec_a,  # n1
        vec_a,  # n2 (完美相似)
        vec_b,  # n3
        vec_a,  # n4 (语义相同，但属于 Process)
        vec_a,  # n1 (重复ID)
    ])
    
    # 执行筛选算法
    candidates = find_candidates(nodes, embeddings, threshold=0.9)
    
    # 预期结果：(n1 和 n2) 以及 (n2 和 末尾的n1) 符合所有条件，共有2对
    assert len(candidates) == 2, "应该匹配出两对候选 (n1-n2, n2-n1)"
    
    match = candidates[0]
    # 验证选出的节点
    assert (match["node_a"]["id"] == "n1" and match["node_b"]["id"] == "n2") or (match["node_a"]["id"] == "n2" and match["node_b"]["id"] == "n1")
    
    # 验证相似度 (浮点数精度)
    assert match["similarity"] > 0.99
