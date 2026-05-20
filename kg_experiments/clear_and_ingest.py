import sys
import os
import uuid

sys.path.append(os.path.abspath('.'))

from elasticsearch import Elasticsearch
from neo4j import GraphDatabase
from src.core.config import settings

def clear_dbs():
    print("================================")
    print("Clearing ES index: metallurgy_chunks...")
    try:
        es = Elasticsearch(settings.ELASTICSEARCH_URL)
        if es.indices.exists(index="metallurgy_chunks"):
            es.indices.delete(index="metallurgy_chunks")
        print("-> ES cleared.")
    except Exception as e:
        print(f"-> ES clear failed: {e}")

    print("\nClearing Neo4j database...")
    try:
        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        driver.close()
        print("-> Neo4j cleared.")
    except Exception as e:
        print(f"-> Neo4j clear failed: {e}")
    print("================================\n")

from src.ingestion.pipeline import IngestionPipeline
from src.db.session import SessionLocal, engine
from src.models.document import DocumentMetadata, Base

def ingest():
    Base.metadata.create_all(bind=engine)
    doc_id = str(uuid.uuid4())
    pdf_path = "/home/xiaohezi/Desktop/prase _claudecode/xiaoye/test.pdf"
    filename = "test.pdf"

    print(f"Adding document to postgres database with ID {doc_id}")
    db = SessionLocal()
    existing = db.query(DocumentMetadata).filter_by(hash="test_hash").first()
    if existing:
        db.delete(existing)
        db.commit()
        
    doc = DocumentMetadata(id=doc_id, filename=filename, hash="test_hash", real_path=pdf_path)
    db.add(doc)
    db.commit()
    db.close()

    print(f"Running full ingestion pipeline for {filename}...")
    pipeline = IngestionPipeline(doc_id=doc_id, pdf_path=pdf_path, filename=filename)
    pipeline.run()

if __name__ == "__main__":
    clear_dbs()
    ingest()
