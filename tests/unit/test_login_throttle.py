"""Failed logins and verification codes are throttled; container limits."""

import pytest
from httpx import ASGITransport, AsyncClient

from painkiller.adapters.sandbox.limits import DEFAULT_PIDS_LIMIT, container_limits
from painkiller.api.security import AttemptLimiter
from painkiller.api.server import create_app


def test_limiter_blocks_after_the_limit_and_forgets_after_the_window(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("painkiller.api.security.time.monotonic", lambda: now[0])
    limiter = AttemptLimiter(limit=3, window_seconds=60)

    for _ in range(3):
        assert not limiter.blocked("a")
        limiter.fail("a")
    assert limiter.blocked("a")
    assert not limiter.blocked("b")

    now[0] += 61
    assert not limiter.blocked("a")


def test_limiter_reset_and_key_cap():
    limiter = AttemptLimiter(limit=1, window_seconds=60, max_keys=2)
    limiter.fail("a")
    limiter.reset("a")
    assert not limiter.blocked("a")
    for key in ("a", "b", "c"):
        limiter.fail(key)
    assert len(limiter._failures) == 2


async def test_wrong_passwords_end_in_429_even_with_the_right_one_afterwards(tmp_path):
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'throttle.db'}")
    app.state.login_attempts = AttemptLimiter(limit=3, window_seconds=300)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for _ in range(3):
                resp = await client.post("/api/auth/login", json={"username": "admin", "password": "errada"})
                assert resp.status_code == 401
            resp = await client.post("/api/auth/login", json={"username": "admin", "password": "errada"})
            assert resp.status_code == 429
            # Outro usuário não é afetado.
            resp = await client.post("/api/auth/login", json={"username": "outro", "password": "x"})
            assert resp.status_code == 401


async def test_verification_code_guesses_are_limited(tmp_path):
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'code.db'}")
    app.state.code_attempts = AttemptLimiter(limit=2, window_seconds=900)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/auth/register", json={
                "first_name": "Ana", "last_name": "Silva", "email": "ana@example.com",
                "password": "Password123!", "confirm_password": "Password123!",
            })
            assert resp.status_code == 200, resp.text
            user = await app.state.tracker.get_user_by_email_or_username("ana@example.com")
            wrong = "000000" if user.verification_code != "000000" else "111111"
            for _ in range(2):
                resp = await client.post("/api/auth/verify-code", json={"email": "ana@example.com", "code": wrong})
                assert resp.status_code == 400
            # Bloqueado: nem o código certo passa até a janela acabar.
            resp = await client.post(
                "/api/auth/verify-code", json={"email": "ana@example.com", "code": user.verification_code}
            )
            assert resp.status_code == 429


def test_container_limits_default_and_overrides(monkeypatch):
    monkeypatch.delenv("PAINKILLER_AGENT_PIDS_LIMIT", raising=False)
    monkeypatch.delenv("PAINKILLER_AGENT_MEMORY", raising=False)
    assert container_limits() == {"pids_limit": DEFAULT_PIDS_LIMIT}

    monkeypatch.setenv("PAINKILLER_AGENT_PIDS_LIMIT", "0")
    monkeypatch.setenv("PAINKILLER_AGENT_MEMORY", "6g")
    assert container_limits() == {"mem_limit": "6g"}

    monkeypatch.setenv("PAINKILLER_AGENT_PIDS_LIMIT", "lixo")
    assert container_limits()["pids_limit"] == DEFAULT_PIDS_LIMIT
