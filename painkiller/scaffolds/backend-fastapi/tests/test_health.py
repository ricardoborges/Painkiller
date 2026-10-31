from fastapi.testclient import TestClient

from app.main import create_app


def test_health():
    client = TestClient(create_app())
    assert client.get("/health").json() == {"status": "ok"}


def test_rate_limit_blocks_after_the_limit(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    app = create_app()

    @app.get("/ping")
    def ping() -> dict:
        return {"pong": True}

    client = TestClient(app)
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 429
    # O health check do deploy nunca é limitado.
    assert client.get("/health").status_code == 200
