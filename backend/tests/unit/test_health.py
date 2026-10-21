from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.main import app


def test_live():
    response = TestClient(app).get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_hides_errors(monkeypatch):
    def unavailable():
        raise SQLAlchemyError("sensitive-database-password")

    monkeypatch.setattr("app.main.get_engine", unavailable)
    monkeypatch.setattr("app.main.vault", lambda: None)
    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: Settings(
            database_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
            redis_url="redis://127.0.0.1:1/0",
        ),
    )
    response = TestClient(app).get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["postgresql"] is False
    assert "sensitive" not in response.text
