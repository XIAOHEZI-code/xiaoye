import sys
import os
import time

# Ensure we are running from project root context
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.retrieval.semantic_search import SemanticSearchTool

def setup_mock_data(tool: SemanticSearchTool):
    """
    Inserts a few mock documents into the ES index `metallurgy_chunks`.
    """
    tool.index_name = "test_hybrid_metals_v2"
    index_name = tool.index_name
    
    # Check if index exists, create if not
    if not tool.es.indices.exists(index=index_name):
        # We need mapping for dense vector
        dim = len(tool.embeddings.embed_query("test"))
        tool.es.indices.create(
            index=index_name,
            body={
                "mappings": {
                    "properties": {
                        "chunk_id": {"type": "keyword"},
                        "doc_id": {"type": "keyword"},
                        "content": {"type": "text"},
                        "source_type": {"type": "keyword"},
                        "vector": {"type": "dense_vector", "dims": dim, "index": True, "similarity": "cosine"}
                    }
                }
            }
        )
        print(f"Created index {index_name} with dims {dim}.")

    mock_docs = [
        {
            "chunk_id": "c1",
            "doc_id": "d1",
            "content": "牌号 1Cr18Ni9Ti, 属于奥氏体不锈钢。屈服强度最低为 205 MPa。常用于航空航天和耐酸设备。",
            "source_type": "standard"
        },
        {
            "chunk_id": "c2",
            "doc_id": "d2",
            "content": "马氏体不锈钢的物理极限大约是 200 兆帕左右。这种钢经过淬火后硬度极高。",
            "source_type": "handbook"
        },
        {
            "chunk_id": "c3",
            "doc_id": "d3",
            "content": "普通 Q235 碳素结构钢，屈服强度 235 MPa，常用于建筑桥梁结构。",
            "source_type": "standard"
        }
    ]

    print("Inserting mock data into Elasticsearch...")
    for doc in mock_docs:
        vec = tool.embeddings.embed_query(doc["content"])
        doc["vector"] = vec
        tool.es.index(index=index_name, id=doc["chunk_id"], body=doc)
    
    # Refresh to make docs immediately searchable
    tool.es.indices.refresh(index=index_name)
    print("Mock data ready!\n")

def run_tests():
    tool = SemanticSearchTool()
    setup_mock_data(tool)
    
    queries = [
        "搜索 205 MPa 相关的钢铁牌号",
        "不锈钢物理极限"
    ]
    
    for q in queries:
        print("="*60)
        print(f"Executing Hybrid Search for: '{q}'")
        start = time.time()
        results = tool.search(q, top_k=3)
        elapsed = time.time() - start
        
        print(f"Results (in {elapsed:.3f}s):")
        for i, res in enumerate(results):
            print(f"  [#{i+1}] Score: {res['score']:.4f} | Source: {res['doc_id']}")
            print(f"         Content: {res['content']}")
        print("="*60 + "\n")

if __name__ == "__main__":
    run_tests()
