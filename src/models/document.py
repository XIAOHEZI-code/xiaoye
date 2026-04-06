import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, JSON
from src.db.session import Base

class DocumentMetadata(Base):
    """
    Store metadata for ingested PDF documents.
    """
    __tablename__ = "document_metadata"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False, index=True)
    hash = Column(String, unique=True, index=True, nullable=False) # To prevent duplicate processing
    status = Column(String, default="pending", index=True) # pending, processing, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
class ImageEvaluation(Base):
    """
    Store evaluation results of images processed by QWENV3.
    """
    __tablename__ = "image_evaluations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, nullable=False, index=True)
    image_path = Column(String, nullable=False) # Path or URL to the extracted image
    category = Column(String, index=True) # Metallurgy specific category
    evaluation_text = Column(Text, nullable=False) # Qwen's description 
    raw_json = Column(JSON, nullable=True) # Any structured output from Qwen
    created_at = Column(DateTime, default=datetime.utcnow)
