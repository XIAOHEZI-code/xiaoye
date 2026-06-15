#!/usr/bin/env python3
"""
Retrieval Recall Evaluation Script for Xiaoye metallurgy RAG.
Compares:
  1. BM25 (Lexical Search)
  2. Dense Vector (Semantic Search)
  3. Hybrid Search (BM25 + Dense + RRF)
  4. KG-Anchored HyDE Search (Neo4j + HyDE + Hybrid Search)

Measures:
  - Recall@5 (Keyword information recall)
  - MRR@5 (Mean Reciprocal Rank of first relevant chunk)
  - Latency (ms)
"""

import sys
import os
import time
from typing import List, Dict, Any
from pathlib import Path

# Resolve project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from elasticsearch import Elasticsearch
from langchain_openai import OpenAIEmbeddings
from src.core.config import settings
from src.retrieval.semantic_search import SemanticSearchTool
from src.retrieval.graph_search import GraphLogicTool
from ragflow_sandbox.core_components.nlp.query_builder import QueryBuilder
from ragflow_sandbox.core_components.search.hybrid_scorer import HybridScorer

# Test cases taken from fullchain_benchmark.py
TEST_CASES = [
    {
        "id": "Q1",
        "query": "304/45双金属复合螺栓在冷加工态和调质态下的疲劳极限分别是多少？请引用具体数值和来源页码。",
        "expect_keywords": ["240", "85", "MPa", "疲劳极限"],
        "graph_entities": ["304不锈钢螺栓", "45钢", "疲劳性能"],
    },
    {
        "id": "Q2",
        "query": "调质处理对304/45双金属复合螺栓的耐腐蚀性能产生了什么影响？请结合电化学数据和盐雾试验结果具体说明。",
        "expect_keywords": ["腐蚀电位", "盐雾", "碳化物", "耐腐蚀"],
        "graph_entities": ["调质处理", "304不锈钢螺栓", "耐蚀性能"],
    },
    {
        "id": "Q3",
        "query": "敏化现象是如何通过微观组织变化导致304不锈钢耐腐蚀性下降的？请追踪完整的因果链条。",
        "expect_keywords": ["敏化", "碳化物", "晶间", "铬", "耐腐蚀"],
        "graph_entities": ["调质处理", "碳化物颗粒", "碳化铬颗粒", "304不锈钢螺栓"],
    },
    {
        "id": "Q4",
        "query": "304/45双金属复合螺栓从原材料到成品经过了哪些制造工艺？每种工艺分别改变了什么微观组织、影响了什么性能？",
        "expect_keywords": ["热轧", "拉拔", "冷加工", "调质", "组织", "性能"],
        "graph_entities": ["热轧", "冷加工", "调质处理", "304不锈钢螺栓", "45钢"],
    },
    {
        "id": "Q5",
        "query": "根据论文中的S-N曲线（图5），冷加工态和调质态螺栓的疲劳断裂模式有什么不同？请结合疲劳断口形貌特征来解释。",
        "expect_keywords": ["S-N", "疲劳", "断口", "裂纹"],
        "graph_entities": ["疲劳性能", "S-N曲线", "瞬断区"],
    },
]

class RetrievalEvaluator:
    def __init__(self):
        self.es = Elasticsearch(settings.ELASTICSEARCH_URL)
        self.embeddings = OpenAIEmbeddings(
            model=settings.QWEN_EMBEDDING_MODEL,
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_BASE_URL,
            check_embedding_ctx_length=False,
        )
        self.index_name = "metallurgy_chunks"
        self.query_builder = QueryBuilder()
        self.hybrid_scorer = HybridScorer()
        self.semantic_tool = SemanticSearchTool()
        self.graph_tool = GraphLogicTool()

    def run_bm25(self, query: str, top_k: int = 5) -> List[str]:
        es_dsl, _ = self.query_builder.build_es_query(query)
        try:
            res = self.es.search(
                index=self.index_name,
                query=es_dsl,
                _source=["content"],
                size=top_k
            )
            return [hit["_source"]["content"] for hit in res["hits"]["hits"]]
        except Exception as e:
            print(f"BM25 Error: {e}")
            return []

    def run_dense(self, query: str, top_k: int = 5) -> List[str]:
        try:
            query_vector = self.embeddings.embed_query(query)
            knn_query = {
                "field": "vector",
                "query_vector": query_vector,
                "k": top_k,
                "num_candidates": top_k * 5
            }
            res = self.es.search(
                index=self.index_name,
                knn=knn_query,
                _source=["content"],
                size=top_k
            )
            return [hit["_source"]["content"] for hit in res["hits"]["hits"]]
        except Exception as e:
            print(f"Dense Error: {e}")
            return []

    def run_hybrid(self, query: str, top_k: int = 5) -> List[str]:
        try:
            chunks = self.semantic_tool.search(query, top_k=top_k)
            return [getattr(c, "text_content", "") for c in chunks]
        except Exception as e:
            print(f"Hybrid Error: {e}")
            return []

    def run_agent_multihop(self, query: str, graph_entities: List[str], top_k: int = 5) -> List[str]:
        try:
            # 1. 模拟 Agent 首先调用 search_metallurgy_graph_relations 获取图谱三元组
            relations = []
            for entity in graph_entities:
                res = self.graph_tool.find_direct_relations(entity)
                for r in res:
                    sub = r['subject'].split('(')[0].strip()
                    obj = r['object'].split('(')[0].strip()
                    rel = r['relation']
                    relations.append(f"{sub} {rel} {obj}")
            
            relations_text = "，".join(relations)
            # 过滤掉 Elasticsearch query_string 特殊字符
            import re
            relations_text = re.sub(r'[\+\-\=\&\|><!\(\)\{\}\[\]\^"~\*\?:\\/]', ' ', relations_text)
            
            # 2. 模拟 Agent 将图谱背景与用户 Query 融合后，调用 search_metallurgy_text (即 Hybrid)
            combined_query = query
            if relations_text:
                combined_query = f"{query}。相关背景：{relations_text}"
            
            chunks = self.semantic_tool.search(combined_query, top_k=top_k)
            return [getattr(c, "text_content", "") for c in chunks]
        except Exception as e:
            print(f"Agent Multi-hop Error: {e}")
            return []

    def evaluate_metrics(self, contents: List[str], expected_keywords: List[str]) -> tuple:
        if not contents:
            return 0.0, 0.0

        # Calculate Keyword Recall
        merged_text = "\n".join(contents).lower()
        found_count = sum(1 for kw in expected_keywords if kw.lower() in merged_text)
        recall = found_count / len(expected_keywords) if expected_keywords else 0.0

        # Calculate MRR
        mrr = 0.0
        for idx, content in enumerate(contents):
            content_lower = content.lower()
            if any(kw.lower() in content_lower for kw in expected_keywords):
                mrr = 1.0 / (idx + 1)
                break

        return recall, mrr

    def evaluate_all(self) -> Dict[str, Any]:
        results = {
            "BM25": {"recall": [], "mrr": [], "latency": []},
            "Dense Vector": {"recall": [], "mrr": [], "latency": []},
            "Hybrid (RRF)": {"recall": [], "mrr": [], "latency": []},
            "Agent Multi-hop": {"recall": [], "mrr": [], "latency": []}
        }

        # Clear proxies
        for key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
            os.environ.pop(key, None)

        print("\n=== Running Retrieval Recall Evaluation ===")
        for tc in TEST_CASES:
            qid = tc["id"]
            query = tc["query"]
            expected = tc["expect_keywords"]
            print(f"\nEvaluating {qid}: {query[:30]}...")

            # 1. BM25
            t0 = time.perf_counter()
            bm25_res = self.run_bm25(query, 5)
            dt = (time.perf_counter() - t0) * 1000
            rec, mrr = self.evaluate_metrics(bm25_res, expected)
            results["BM25"]["recall"].append(rec)
            results["BM25"]["mrr"].append(mrr)
            results["BM25"]["latency"].append(dt)
            print(f"  BM25           -> Recall: {rec:.2f}, MRR: {mrr:.2f}, Time: {dt:.1f}ms")

            # 2. Dense
            t0 = time.perf_counter()
            dense_res = self.run_dense(query, 5)
            dt = (time.perf_counter() - t0) * 1000
            rec, mrr = self.evaluate_metrics(dense_res, expected)
            results["Dense Vector"]["recall"].append(rec)
            results["Dense Vector"]["mrr"].append(mrr)
            results["Dense Vector"]["latency"].append(dt)
            print(f"  Dense Vector   -> Recall: {rec:.2f}, MRR: {mrr:.2f}, Time: {dt:.1f}ms")

            # 3. Hybrid
            t0 = time.perf_counter()
            hybrid_res = self.run_hybrid(query, 5)
            dt = (time.perf_counter() - t0) * 1000
            rec, mrr = self.evaluate_metrics(hybrid_res, expected)
            results["Hybrid (RRF)"]["recall"].append(rec)
            results["Hybrid (RRF)"]["mrr"].append(mrr)
            results["Hybrid (RRF)"]["latency"].append(dt)
            print(f"  Hybrid (RRF)   -> Recall: {rec:.2f}, MRR: {mrr:.2f}, Time: {dt:.1f}ms")

            # 4. Agent Multi-hop
            t0 = time.perf_counter()
            agent_res = self.run_agent_multihop(query, tc.get("graph_entities", []), 5)
            dt = (time.perf_counter() - t0) * 1000
            rec, mrr = self.evaluate_metrics(agent_res, expected)
            results["Agent Multi-hop"]["recall"].append(rec)
            results["Agent Multi-hop"]["mrr"].append(mrr)
            results["Agent Multi-hop"]["latency"].append(dt)
            print(f"  Agent Multi-hop -> Recall: {rec:.2f}, MRR: {mrr:.2f}, Time: {dt:.1f}ms")

        # Compile aggregates
        print("\n=== AGGREGATED EVALUATION RESULTS ===")
        print(f"| {'Retrieval Mode':<20} | {'Avg Recall@5':<12} | {'Avg MRR@5':<10} | {'Avg Latency':<12} |")
        print(f"| {'-'*20} | {'-'*12} | {'-'*10} | {'-'*12} |")

        aggregated = {}
        for mode, metrics in results.items():
            avg_rec = sum(metrics["recall"]) / len(metrics["recall"])
            avg_mrr = sum(metrics["mrr"]) / len(metrics["mrr"])
            avg_lat = sum(metrics["latency"]) / len(metrics["latency"])
            aggregated[mode] = {"recall": avg_rec, "mrr": avg_mrr, "latency": avg_lat}
            print(f"| {mode:<20} | {avg_rec:<12.2%} | {avg_mrr:<10.3f} | {avg_lat:<10.1f}ms |")

        try:
            self.graph_tool.close()
        except Exception:
            pass

        return aggregated

if __name__ == "__main__":
    evaluator = RetrievalEvaluator()
    evaluator.evaluate_all()
