import pytest
from src.models.chunk_document import ChunkDocument, BoundingBox, make_text_chunk, make_image_chunk

def test_bounding_box_serialization():
    bbox = BoundingBox(x0=0.1, y0=0.2, x1=0.3, y1=0.4)
    data = bbox.to_dict()
    assert data == {"x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.4}
    
    restored = BoundingBox.from_dict(data)
    assert restored.x0 == 0.1
    assert restored.y1 == 0.4

def test_chunk_document_to_dict():
    doc = make_text_chunk(
        text="Sample context",
        doc_id="doc_001",
        source_pdf_id="paper.pdf",
        page_number=5,
        bbox=BoundingBox(0, 0, 100, 100)
    )
    
    data = doc.to_dict()
    assert data["doc_id"] == "doc_001"
    assert data["content"] == "Sample context"
    assert data["chunk_type"] == "text"
    assert data["source_pdf_id"] == "paper.pdf"
    assert data["page_number"] == 5
    assert data["bbox"]["x1"] == 100
    assert "chunk_id" in data

def test_chunk_document_from_es_hit():
    es_source = {
        "chunk_id": "chunk_abc123",
        "doc_id": "doc_002",
        "content": "Image caption text",
        "chunk_type": "figure",
        "source_pdf_id": "fig.pdf",
        "page_number": 12,
        "bbox": {"x0": 1, "y0": 2, "x1": 3, "y1": 4},
        "image_uri": "/tmp/img.png",
        "source_type": "image_description"
    }
    
    doc = ChunkDocument.from_es_hit(es_source, score=0.99)
    assert doc.chunk_id == "chunk_abc123"
    assert doc.doc_id == "doc_002"
    assert doc.chunk_type == "figure"
    assert doc.text_content == "Image caption text"
    assert doc.page_number == 12
    assert doc.bbox.y0 == 2
    assert doc.image_uri == "/tmp/img.png"
    assert doc.score == 0.99

def test_to_citation_str():
    doc1 = make_text_chunk(
        text="Sample",
        doc_id="doc",
        source_pdf_id="paper.pdf",
        page_number=3
    )
    assert doc1.to_citation_str() == "[来源: paper.pdf, p.3]"
    
    doc2 = make_image_chunk(
        description="Figure 1",
        doc_id="doc",
        source_pdf_id="paper.pdf",
        image_uri="/img",
        page_number=5
    )
    assert "[figure]" in doc2.to_citation_str()
    assert "paper.pdf" in doc2.to_citation_str()
    assert "p.5" in doc2.to_citation_str()
