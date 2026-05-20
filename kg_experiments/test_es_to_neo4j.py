import sys
import os
import json

sys.path.append(os.path.abspath("."))
from elasticsearch import Elasticsearch
from src.core.config import settings
from src.ingestion.graph_extractor import Neo4jGraphExtractor

def main():
    print("=== Testing ES Chunks -> Neo4j Extraction ===")
    
    es = Elasticsearch(settings.ELASTICSEARCH_URL)
    index_name = "metallurgy_chunks"
    
    # Fetch 3 random text chunks from ES
    query = {
        "query": {
            "bool": {
                "must": [
                    {"exists": {"field": "content"}}
                ]
            }
        },
        "size": 3
    }
    
    print("Fetching chunks from ES...")
    try:
        res = es.search(index=index_name, body=query)
        hits = res['hits']['hits']
        if not hits:
            print("No chunks found in ES.")
            return
        print(f"Found {len(hits)} chunks to test.")
    except Exception as e:
        print(f"Failed to query ES: {e}")
        return
        
    extractor = Neo4jGraphExtractor()
    
    for i, hit in enumerate(hits):
        doc_id = hit['_id']
        source = hit['_source']
        content = source.get('content', '')
        
        if len(content.strip()) < 50:
            print(f"\n--- Chunk {i+1} (ID: {doc_id}) skipped (too short) ---")
            continue
            
        print(f"\n=======================================================")
        print(f"--- Chunk {i+1} (ID: {doc_id}) ---")
        print(f"[Content Excerpt]:\n{content[:300]}...\n")
        
        print("[Extracting Triplets...]")
        triplets = extractor.extract_triplets_from_text(content)
        
        if triplets:
            print(f"-> Extracted {len(triplets)} triplets:")
            for t in triplets:
                print(f"  • ({t.subject}) -[{t.relation}]-> ({t.object_})")
                print(f"      Types: [{t.subject_type}] -> [{t.object_type}]")
                if t.mechanism:
                    print(f"      Mechanism: {t.mechanism}")
                if t.context:
                    print(f"      Context: {t.context}")
        else:
            print("-> No valid triplets extracted from this chunk.")
            
    extractor.close()
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    main()
