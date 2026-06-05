import os
import sys
from elasticsearch import Elasticsearch
from neo4j import GraphDatabase
from src.core.config import settings
from src.ingestion.pipeline import IngestionPipeline

doc_id = '2fbcf8c2-affa-448b-95d1-7c41811df328'
pdf_path = 'data/storage/2fbcf8c2-affa-448b-95d1-7c41811df328.pdf'
filename = '工业固废磷石膏综合治理现状及对策_姜国庆.pdf'

print("1. Cleaning Elasticsearch chunks...")
es = Elasticsearch(settings.ELASTICSEARCH_URL)
result = es.delete_by_query(
    index="metallurgy_chunks",
    body={"query": {"term": {"doc_id": doc_id}}},
    ignore=[404],
)
print(f"ES deleted: {result.get('deleted', 0)} chunks")

print("2. Cleaning Neo4j relations...")
driver = GraphDatabase.driver(
    settings.NEO4J_URI,
    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
)
with driver.session() as session:
    result = session.run(
        "MATCH ()-[r {doc_id: $doc_id}]->() DELETE r RETURN count(r) AS cnt",
        doc_id=doc_id,
    )
    rel_count = result.single()["cnt"]
    session.run("MATCH (n) WHERE NOT (n)--() DELETE n")
driver.close()
print(f"Neo4j deleted: {rel_count} relations")

print("3. Running IngestionPipeline...")
pipeline = IngestionPipeline(doc_id=doc_id, pdf_path=pdf_path, filename=filename)
pipeline.run()
print("All done!")
