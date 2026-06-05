import pytest
import json
from unittest.mock import patch, MagicMock
from src.tooling.definitions import search_metallurgy_text

@pytest.mark.small
@patch("src.tooling.definitions.semantic_searcher.search")
@patch("redis.from_url")
def test_search_metallurgy_text_success(mock_redis_from_url, mock_search):
    # Mock search results returning ChunkDocument mocks
    mock_doc1 = MagicMock()
    mock_doc1.doc_id = "doc_123"
    mock_doc1.source_pdf_id = "bolt_study.pdf"
    mock_doc1.page_number = 5
    mock_doc1.source_type = "academic"
    mock_doc1.text_content = "304不锈钢在调质态下具有良好的疲劳极限。"
    mock_doc1.image_uri = None
    mock_doc1.score = 0.9
    mock_doc1.chunk_type = "text"
    mock_doc1.to_citation_str.return_value = "[来源: bolt_study.pdf, p.5]"
    
    mock_doc2 = MagicMock()
    mock_doc2.doc_id = "doc_456"
    mock_doc2.source_pdf_id = "metallurgy_handbook.pdf"
    mock_doc2.page_number = 12
    mock_doc2.source_type = "standard"
    mock_doc2.text_content = "热轧态的抗拉强度约为550MPa。"
    mock_doc2.image_uri = "path/to/chart.png"
    mock_doc2.score = 0.8
    mock_doc2.chunk_type = "text"
    mock_doc2.to_citation_str.return_value = "[来源: metallurgy_handbook.pdf, p.12]"

    mock_search.return_value = [mock_doc1, mock_doc2]

    # Mock Redis client
    mock_redis = MagicMock()
    mock_redis_from_url.return_value = mock_redis

    # Run tool
    result = search_metallurgy_text("304不锈钢性能", top_k=2)

    # Assert search called
    mock_search.assert_called_once_with("304不锈钢性能", top_k=2)

    # Assert content formatted correctly
    assert "Doc: doc_123 [来源: bolt_study.pdf, p.5] (Type: academic)" in result
    assert "Content: 304不锈钢在调质态下具有良好的疲劳极限。" in result
    assert "Doc: doc_456 [来源: metallurgy_handbook.pdf, p.12] (Type: standard)" in result
    assert "Content: 热轧态的抗拉强度约为550MPa。" in result
    assert "Image: ![standard图表](http://127.0.0.1:8000/api/v1/images?path=path/to/chart.png)" in result

    # Assert Redis SSE message is published
    mock_redis.publish.assert_called_once()
    published_data = mock_redis.publish.call_args[0][1]
    parsed = json.loads(published_data)
    assert parsed["type"] == "retrieval_sources"
    assert len(parsed["sources"]) == 2
