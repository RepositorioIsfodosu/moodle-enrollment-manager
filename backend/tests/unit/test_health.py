from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.main import app


def test_live():
    response = TestClient(app).get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_hides_errors(monkeypatch):
    def unavailable():
        raise SQLAlchemyError("sensitive-database-password")

    monkeypatch.setattr("app.main.get_engine", unavailable)
    response = TestClient(app).get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["postgresql"] is False
    assert "sensitive" not in response.text
