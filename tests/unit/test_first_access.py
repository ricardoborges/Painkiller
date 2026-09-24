"""First access: the administrator is created in the UI and lives in the database."""

import pytest
from httpx import ASGITransport, AsyncClient

from painkiller.api import security
from painkiller.api.server import create_app
from painkiller.cli.admin_reset import _reset


@pytest.fixture(autouse=True)
def frozen_admin(monkeypatch):
    """Overrides conftest: here the signing key and the admin come from the database."""
    monkeypatch.setattr(security, "_admin", None)
    monkeypatch.setattr(security, "_auth_secret", b"")


def _app(db):
    return create_app(db_url=f"sqlite+aiosqlite:///{db}")


@pytest.fixture
async def app(tmp_path):
    app = _app(tmp_path / "fresh.db")
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_fresh_install_only_offers_the_first_access(client):
    config = (await client.get("/api/auth/config")).json()
    assert config["first_access"] is True and config["break_glass"] is False
    # Nem o login de admin funciona antes de existir um.
    assert (await client.post("/api/auth/login", json={"username": "admin", "password": "x" * 12})).status_code == 401


async def test_first_access_creates_the_admin_and_signs_in(app, client):
    weak = await client.post("/api/auth/first-access", json={"username": "ana", "password": "curta"})
    assert weak.status_code == 400

    res = await client.post("/api/auth/first-access", json={"username": " ana ", "password": "senha-bem-longa"})
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["role"] == "admin" and body["user"]["username"] == "ana"
    headers = {"Authorization": f"Bearer {body['token']}"}
    assert (await client.get("/api/setup", headers=headers)).json()["admin_username"] == "ana"

    # Só uma vez: um segundo visitante não toma a plataforma.
    again = await client.post("/api/auth/first-access", json={"username": "eve", "password": "outra-senha-longa"})
    assert again.status_code == 409
    assert (await client.get("/api/auth/config")).json()["first_access"] is False

    # Senha guardada em hash, nunca em claro.
    raw = await app.state.tracker._read_setting("platform")
    assert "senha-bem-longa" not in raw and "scrypt$" in raw

    ok = await client.post("/api/auth/login", json={"username": "ana", "password": "senha-bem-longa"})
    assert ok.status_code == 200
    bad = await client.post("/api/auth/login", json={"username": "ana", "password": "errada-errada"})
    assert bad.status_code == 401


async def test_admin_and_sessions_survive_a_restart(tmp_path):
    db = tmp_path / "restart.db"
    first = _app(db)
    async with first.router.lifespan_context(first):
        async with AsyncClient(transport=ASGITransport(app=first), base_url="http://t") as c:
            token = (await c.post("/api/auth/first-access", json={"username": "ana", "password": "senha-bem-longa"})).json()["token"]

    security._admin = None
    security._auth_secret = b"other-process"
    second = _app(db)
    async with second.router.lifespan_context(second):
        async with AsyncClient(transport=ASGITransport(app=second), base_url="http://t") as c:
            # A chave de assinatura vem do banco: o token de antes do restart continua valendo.
            me = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert me.status_code == 200 and me.json()["username"] == "ana"


async def test_changing_the_password_revokes_old_tokens(client):
    token = (await client.post("/api/auth/first-access", json={"username": "ana", "password": "senha-bem-longa"})).json()["token"]
    old = {"Authorization": f"Bearer {token}"}

    wrong = await client.put("/api/setup/admin", headers=old, json={"current_password": "nao-e-essa", "username": "ana", "new_password": "nova-senha-longa"})
    assert wrong.status_code == 400

    res = await client.put("/api/setup/admin", headers=old, json={"current_password": "senha-bem-longa", "username": "ana", "new_password": "nova-senha-longa"})
    assert res.status_code == 200
    assert (await client.get("/api/auth/me", headers=old)).status_code == 401
    new = {"Authorization": f"Bearer {res.json()['token']}"}
    assert (await client.get("/api/auth/me", headers=new)).status_code == 200
    assert (await client.post("/api/auth/login", json={"username": "ana", "password": "nova-senha-longa"})).status_code == 200


async def test_admin_reset_reopens_the_first_access(tmp_path):
    db = tmp_path / "reset.db"
    app = _app(db)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.post("/api/auth/first-access", json={"username": "ana", "password": "senha-bem-longa"})

    assert await _reset(f"sqlite+aiosqlite:///{db}") is True

    security._admin = None
    again = _app(db)
    async with again.router.lifespan_context(again):
        async with AsyncClient(transport=ASGITransport(app=again), base_url="http://t") as c:
            assert (await c.get("/api/auth/config")).json()["first_access"] is True
            assert (await c.post("/api/auth/first-access", json={"username": "novo", "password": "senha-bem-longa"})).status_code == 200
