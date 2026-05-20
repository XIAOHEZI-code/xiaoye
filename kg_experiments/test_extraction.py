import sys
import os
import json

# Ensure the root project directory is in the sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from src.ingestion.graph_extractor import Neo4jGraphExtractor

def main():
    print("Initializing LLM Extractor...")
    # We do not need Neo4j to be running just to test the LLM extraction logic,
    # but the init method connects to it.
    extractor = Neo4jGraphExtractor()
    
    import requests

    print("Fetching an actual chunk from Elasticsearch...")
    try:
        res = requests.get("http://localhost:9200/metallurgy_chunks/_search?size=1", json={
            "query": {"match_all": {}}
        }).json()
        sample_text = res["hits"]["hits"][0]["_source"]["content"]
    except Exception as e:
        print("Failed to fetch chunk:", e)
        sample_text = ""
    
    print("\n--- Input Text ---")
    print(sample_text.strip())
    print("------------------\n")
    
    print("Extracting triplets from text via LLM...")
    triplets = extractor.extract_triplets_from_text(sample_text)
    
    print(f"\nExtracted {len(triplets)} triplets:")
    for i, t in enumerate(triplets):
        print(f"[{i+1}] ({t.subject}[{t.subject_type}]) -[{t.relation}]-> ({t.object_}[{t.object_type}])")
        if t.mechanism or t.context:
            print(f"    └─ Properties: {{mechanism: '{t.mechanism}', context: '{t.context}'}}")
        
    extractor.close()

if __name__ == "__main__":
    main()
