from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_reports_schema(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == 1
    assert isinstance(body["fts5_enabled"], bool)


def test_health_respects_api_prefix(settings: Settings) -> None:
    prefixed = settings.model_copy(update={"api_prefix": "/v1"})
    with TestClient(create_app(prefixed)) as client:
        assert client.get("/v1/health").status_code == 200
        assert client.get("/api/health").status_code == 404
