from elasticsearch import Elasticsearch
from src.core.config import settings

es = Elasticsearch(settings.ELASTICSEARCH_URL)

# Search for 578
res = es.search(
    index="metallurgy_chunks",
    body={
        "query": {
            "query_string": {
                "query": "578 OR 593"
            }
        }
    }
)

print(f"Found {len(res['hits']['hits'])} hits for '578 OR 593':")
for hit in res['hits']['hits']:
    source = hit['_source']
    print(f"Doc: {source.get('doc_id')}, Page: {source.get('page_number')}, Score: {hit['_score']}")
    for k, v in source.items():
        if k == 'text_vector':
            continue
        print(f"  {k}: {repr(v)}")
    print("-" * 50)
