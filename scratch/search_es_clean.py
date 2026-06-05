from elasticsearch import Elasticsearch
from src.core.config import settings

es = Elasticsearch(settings.ELASTICSEARCH_URL)

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
    for k, v in source.items():
        if isinstance(v, list):
            print(f"  {k}: [list of length {len(v)}]")
        else:
            print(f"  {k}: {repr(v)}")
    print("-" * 50)
