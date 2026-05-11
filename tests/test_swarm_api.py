import pytest
from fastapi.testclient import TestClient
from src.api.server import app

client = TestClient(app)

def test_fork_api():
    response = client.post(
        "/api/fork_agent",
        json={
            "taskId": "task_123",
            "type": "analyze_region",
            "bbox": {
                "x0": 0.1,
                "y0": 0.2,
                "x1": 0.5,
                "y1": 0.6,
                "pageNumber": 1
            }
        }
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "Fork deployed to background."}
