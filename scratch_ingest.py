import sys
import os
import uuid

# Ensure the root project directory is in the sys.path
sys.path.append(os.path.abspath('.'))

from src.ingestion.pipeline import IngestionPipeline
from src.db.session import SessionLocal, engine
from src.models.document import DocumentMetadata, Base

def ingest():
    Base.metadata.create_all(bind=engine)
    doc_id = str(uuid.uuid4())
    pdf_path = "/home/xiaohezi/Desktop/prase _claudecode/xiaoye/test.pdf"
    filename = "test.pdf"

    print(f"Adding document to database with ID {doc_id}")
    db = SessionLocal()
    # Check if a doc with dummy_hash already exists and delete to avoid constraint failure
    existing = db.query(DocumentMetadata).filter_by(hash="test_hash").first()
    if existing:
        db.delete(existing)
        db.commit()
        
    doc = DocumentMetadata(id=doc_id, filename=filename, hash="test_hash", real_path=pdf_path)
    db.add(doc)
    db.commit()
    db.close()

    print("Running pipeline...")
    pipeline = IngestionPipeline(doc_id=doc_id, pdf_path=pdf_path, filename=filename)
    pipeline.run()

if __name__ == "__main__":
    ingest()
