"""Break-glass login, Google sign-in and per-user project isolation."""

import urllib.parse
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from painkiller.api.security import issue_token, verify_token
from painkiller.api.server import create_app
from tests.auth_helpers import admin_headers, user_headers


class FakeGoogle:
    enabled = True
    client_id = "cid"
    client_secret = "csecret"
    redirect_uri = "http://test/api/auth/google/callback"

    def __init__(self, identity: dict):
        self.identity = identity
        self.codes: list[str] = []

    def authorization_url(self, state: str) -> str:
        return f"https://accounts.example/auth?{urllib.parse.urlencode({'state': state})}"

    async def fetch_identity(self, code: str) -> dict:
        self.codes.append(code)
        return self.identity


@pytest.fixture
async def app(tmp_path):
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    # Sem Gitea de verdade: a criação de repositório falha e é só logada.
    vcs = AsyncMock()
    vcs.create_repository.side_effect = RuntimeError("gitea offline")
    vcs.ensure_user.return_value = "alice"
    vcs.ensure_google_auth_source.return_value = 7
    app.state.vcs = vcs
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _fragment(location: str) -> dict:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(location).fragment))


async def test_break_glass_login_uses_env_credentials(client):
    bad = await client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    assert bad.status_code == 401

    ok = await client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["user"]["role"] == "admin"

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "admin"


async def test_break_glass_disabled_without_password(client, monkeypatch):
    monkeypatch.setenv("PAINKILLER_ADMIN_PASSWORD", "")
    res = await client.post("/api/auth/login", json={"username": "admin", "password": ""})
    assert res.status_code == 401
    assert (await client.get("/api/auth/config")).json()["break_glass"] is False


async def test_changing_admin_password_revokes_admin_tokens(client, monkeypatch):
    headers = admin_headers()
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 200
    monkeypatch.setenv("PAINKILLER_ADMIN_PASSWORD", "rotated")
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 401


async def test_api_requires_a_session(client):
    assert (await client.get("/api/projects")).status_code == 401
    assert (await client.get("/api/projects", headers={"Authorization": "Bearer forged.token"})).status_code == 401
    assert (await client.get("/api/usage/settings")).status_code == 401


def test_tokens_reject_tampering_and_wrong_kind():
    token = issue_token("user-1")
    assert verify_token(token)["sub"] == "user-1"
    body, sig = token.split(".")
    assert verify_token(f"{body}x.{sig}") is None
    assert verify_token(token, kind="oauth_state") is None
    assert verify_token(issue_token("user-1", ttl_seconds=-1)) is None


async def test_users_only_see_their_own_projects(app, client):
    tracker = app.state.tracker
    alice = await tracker.create_user(email="alice@example.com", name="Alice", gitea_username="alice")
    bob = await tracker.create_user(email="bob@example.com", name="Bob", gitea_username="bob")

    created = await client.post("/api/projects", json={"name": "Loja"}, headers=user_headers(alice.id))
    assert created.status_code == 200
    project_id = created.json()["id"]
    assert created.json()["owner_id"] == alice.id
    # Repositório privado na conta Gitea da Alice.
    kwargs = app.state.vcs.create_repository.call_args.kwargs
    assert kwargs["owner"] == "alice" and kwargs["private"] is True

    task = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"title": "t", "description": "d"},
        headers=user_headers(alice.id),
    )
    task_id = task.json()["id"]

    bob_h = user_headers(bob.id)
    assert (await client.get("/api/projects", headers=bob_h)).json() == []
    for path in (
        f"/api/projects/{project_id}",
        f"/api/projects/{project_id}/tasks",
        f"/api/projects/{project_id}/docs",
        f"/api/projects/{project_id}/sessions",
        f"/api/projects/{project_id}/usage",
        f"/api/projects/{project_id}/analysis/current",
        f"/api/tasks/{task_id}",
        f"/api/tasks/{task_id}/diff",
    ):
        assert (await client.get(path, headers=bob_h)).status_code == 404, path
    assert (await client.delete(f"/api/projects/{project_id}", headers=bob_h)).status_code == 404
    assert (await client.post(f"/api/tasks/{task_id}/dispatch", headers=bob_h)).status_code == 404

    alice_list = (await client.get("/api/projects", headers=user_headers(alice.id))).json()
    assert [p["id"] for p in alice_list] == [project_id]
    # O admin break-glass enxerga tudo.
    admin_list = (await client.get("/api/projects", headers=admin_headers())).json()
    assert project_id in [p["id"] for p in admin_list]


async def test_sse_accepts_token_in_query(app, client):
    alice = await app.state.tracker.create_user(email="alice@example.com")
    token = issue_token(alice.id)
    res = await client.get(f"/api/tasks/ghost/stream?token={token}")
    assert res.status_code == 404  # autenticou; a tarefa é que não existe


async def test_users_cannot_pick_repo_path(app, client, tmp_path):
    alice = await app.state.tracker.create_user(email="alice@example.com")
    res = await client.post(
        "/api/projects",
        json={"name": "X", "repo_path": str(tmp_path / "someone-else")},
        headers=user_headers(alice.id),
    )
    assert res.status_code == 403


async def _google_round_trip(client, code: str = "the-code"):
    start = await client.get("/api/auth/google/login", follow_redirects=False)
    assert start.status_code == 302
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(start.headers["location"]).query))["state"]
    nonce = start.cookies.get("pk_oauth_state")
    return await client.get(
        f"/api/auth/google/callback?code={code}&state={urllib.parse.quote(state)}",
        headers={"Cookie": f"pk_oauth_state={nonce}"},
        follow_redirects=False,
    )


async def test_google_sign_in_creates_user_bound_to_gitea(app, client):
    google = FakeGoogle({"sub": "g-123", "email": "Alice@Example.com", "email_verified": True, "name": "Alice"})
    app.state.google_oauth = google

    assert (await client.get("/api/auth/config")).json()["google"] is True

    res = await _google_round_trip(client)
    assert res.status_code == 302
    fragment = _fragment(res.headers["location"])
    assert "token" in fragment, fragment

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {fragment['token']}"})
    assert me.json()["email"] == "alice@example.com"
    assert me.json()["gitea_username"] == "alice"
    assert me.json()["role"] == "user"

    app.state.vcs.ensure_user.assert_awaited_once()
    kwargs = app.state.vcs.ensure_user.call_args.kwargs
    assert kwargs["oauth_source_id"] == 7 and kwargs["oauth_login_name"] == "g-123"

    # Segundo login: mesmo usuário, sem reprovisionar o Gitea.
    again = _fragment((await _google_round_trip(client)).headers["location"])
    assert verify_token(again["token"])["sub"] == verify_token(fragment["token"])["sub"]
    assert app.state.vcs.ensure_user.await_count == 1


async def test_google_callback_rejects_forged_state(app, client):
    app.state.google_oauth = FakeGoogle({"sub": "g", "email": "a@b.c", "email_verified": True})
    res = await client.get(
        f"/api/auth/google/callback?code=x&state={issue_token('n', kind='oauth_state')}",
        headers={"Cookie": "pk_oauth_state=other"},
        follow_redirects=False,
    )
    assert "error" in _fragment(res.headers["location"])
    assert app.state.google_oauth.codes == []


async def test_google_domain_allowlist_and_verified_email(app, client, monkeypatch):
    monkeypatch.setenv("PAINKILLER_GOOGLE_ALLOWED_DOMAINS", "empresa.com.br")
    app.state.google_oauth = FakeGoogle({"sub": "g", "email": "x@gmail.com", "email_verified": True})
    assert "error" in _fragment((await _google_round_trip(client)).headers["location"])

    app.state.google_oauth = FakeGoogle({"sub": "g", "email": "x@empresa.com.br", "email_verified": False})
    assert "error" in _fragment((await _google_round_trip(client)).headers["location"])

    app.state.google_oauth = FakeGoogle({"sub": "g", "email": "x@empresa.com.br", "email_verified": True})
    assert "token" in _fragment((await _google_round_trip(client)).headers["location"])


async def test_google_login_404_when_not_configured(client):
    assert (await client.get("/api/auth/google/login", follow_redirects=False)).status_code == 404
    assert (await client.get("/api/auth/config")).json()["google"] is False


async def test_cookie_authentication_and_lifecycle(app, client):
    # 1. Break-glass login sets the cookie
    login_res = await client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"})
    assert login_res.status_code == 200
    token = login_res.json()["token"]
    assert "painkiller_token" in login_res.cookies
    assert login_res.cookies["painkiller_token"] == token

    # 2. Authenticated request using cookie only
    authed_res = await client.get("/api/projects", cookies={"painkiller_token": token})
    assert authed_res.status_code == 200

    # 3. /me syncs cookie if passed via bearer header
    fresh_client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    me_res = await fresh_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert "painkiller_token" in me_res.cookies

    # 4. /logout clears the cookie
    logout_res = await client.post("/api/auth/logout")
    assert logout_res.status_code == 200
    assert logout_res.cookies.get("painkiller_token") is None or "painkiller_token" in logout_res.headers.get("set-cookie", "")

    # 5. Google callback sets the cookie
    app.state.google_oauth = FakeGoogle({"sub": "cookie-sub", "email": "cookie@test.com", "email_verified": True})
    cb_res = await _google_round_trip(client)
    assert "painkiller_token" in cb_res.cookies
