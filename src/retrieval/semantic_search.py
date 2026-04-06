import sys
import os
from elasticsearch import Elasticsearch
from langchain_openai import OpenAIEmbeddings
from typing import List, Dict, Any
from src.core.config import settings

# Inject Xiaoye root into sys.path to resolve ragflow_sandbox cleanly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from ragflow_sandbox.core_components.nlp.query_builder import QueryBuilder
from ragflow_sandbox.core_components.search.hybrid_scorer import HybridScorer

class SemanticSearchTool:
    """
    Tool for performing Hybrid Search (BM25 + Dense KNN) in Elasticsearch.
    Designed to be invoked by the LangChain ReAct agent.
    Combines queries via Local Reciprocal Rank Fusion (RRF).
    """
    
    def __init__(self):
        self.es = Elasticsearch(settings.ELASTICSEARCH_URL)
        self.embeddings = OpenAIEmbeddings(
            model=settings.QWEN_EMBEDDING_MODEL,
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_BASE_URL,
            check_embedding_ctx_length=False,
        )
        self.index_name = "metallurgy_chunks"
        
        # Initialize extracted RAGFlow components
        self.query_builder = QueryBuilder()
        self.hybrid_scorer = HybridScorer()

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Translates query -> ES DSL (BM25) + Dense Vector.
        Retrieves both streams and fuses them using RRF.
        """
        print(f"[SemanticSearchTool] Generating Hybrid Search for query: '{query}'")
        
        # 1. Expand query via NLP tools
        es_dsl, keywords = self.query_builder.build_es_query(query)
        print(f"[SemanticSearchTool] Expanded Keywords: {keywords}")
        
        query_vector = self.embeddings.embed_query(query)

        # We request 2 times the top_k to give RRF enough candidates to work with
        candidate_pool_size = top_k * 2

        # 2. Vector Search (KNN)
        knn_query = {
            "field": "vector",
            "query_vector": query_vector,
            "k": candidate_pool_size,
            "num_candidates": candidate_pool_size * 5
        }
        
        try:
            vector_res = self.es.search(
                index=self.index_name, 
                knn=knn_query, 
                _source=["chunk_id", "doc_id", "content", "source_type"], 
                size=candidate_pool_size
            )
            vector_hits = vector_res.get("hits", {}).get("hits", [])
        except Exception as e:
            print(f"[SemanticSearchTool] Vector search error: {e}")
            vector_hits = []

        # 3. Lexical Search (BM25 via query_string)
        try:
            lexical_res = self.es.search(
                index=self.index_name, 
                query=es_dsl, 
                _source=["chunk_id", "doc_id", "content", "source_type"], 
                size=candidate_pool_size
            )
            lexical_hits = lexical_res.get("hits", {}).get("hits", [])
        except Exception as e:
            print(f"[SemanticSearchTool] Lexical search error: {e}")
            lexical_hits = []

        # 4. Local RRF Fusion
        docs_map = {}
        vec_results = []
        for hit in vector_hits:
            cid = hit.get("_id") 
            docs_map[cid] = hit.get("_source")
            vec_results.append({"doc_id": cid, "score": hit.get("_score")})
            
        lex_results = []
        for hit in lexical_hits:
            cid = hit.get("_id")
            docs_map[cid] = hit.get("_source")
            lex_results.append({"doc_id": cid, "score": hit.get("_score")})

        rrf_ranked = self.hybrid_scorer.reciprocal_rank_fusion(lex_results, vec_results, k=60)
        
        # 5. Return Top-K
        final_results = []
        for item in rrf_ranked[:top_k]:
            cid = item["doc_id"]
            src = docs_map[cid]
            final_results.append({
                "score": item["rrf_score"],
                "doc_id": src.get("doc_id"),
                "content": src.get("content"),
                "source_type": src.get("source_type")
            })
            
        return final_results
