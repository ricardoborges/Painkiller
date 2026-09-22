"""Unit tests for Gitea reverse proxy and SSO identity injection."""

from unittest.mock import patch
import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from painkiller.api.security import (
    BREAK_GLASS_ID,
    break_glass_fingerprint,
    issue_token,
)
from painkiller.api.server import create_app


@pytest.fixture
async def app(tmp_path):
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'proxy_test.db'}")
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _mock_upstream_client(captured_requests: list):
    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            status_code=200,
            content=b"mock gitea content",
            headers={"content-type": "text/html", "set-cookie": "i_like_gitea=session123; Path=/"},
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_gitea_proxy_injects_identity_for_regular_user(app, client):
    user = await app.state.tracker.create_user(
        email="ricardo@test.com",
        name="Ricardo Borges",
        gitea_username="ricardoborges",
    )
    token = issue_token(user.id)

    captured = []
    upstream = _mock_upstream_client(captured)
    with patch("painkiller.api.routes.gitea_proxy._get_http_client", return_value=upstream):
        client.cookies.set("painkiller_token", token)
        res = await client.get("/gitea/ricardoborges/hello-world")

        assert res.status_code == 200
        assert res.content == b"mock gitea content"
        assert "set-cookie" in res.headers

        assert len(captured) == 1
        forwarded_req = captured[0]
        assert forwarded_req.url.path == "/ricardoborges/hello-world"
        assert forwarded_req.headers["x-webauth-user"] == "ricardoborges"
        assert forwarded_req.headers["x-webauth-email"] == "ricardo@test.com"


async def test_gitea_proxy_injects_admin_identity(app, client):
    token = issue_token(BREAK_GLASS_ID, pw=break_glass_fingerprint())

    captured = []
    upstream = _mock_upstream_client(captured)
    with patch("painkiller.api.routes.gitea_proxy._get_http_client", return_value=upstream):
        res = await client.get(
            "/gitea/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert res.status_code == 200
        assert len(captured) == 1
        forwarded_req = captured[0]
        assert forwarded_req.url.path == "/admin/users"
        assert forwarded_req.headers["x-webauth-user"] == "painkiller"
        assert forwarded_req.headers["x-webauth-email"] == "bot@painkiller.local"


async def test_gitea_proxy_unauthenticated_does_not_inject_headers(app, client):
    captured = []
    upstream = _mock_upstream_client(captured)
    with patch("painkiller.api.routes.gitea_proxy._get_http_client", return_value=upstream):
        res = await client.get("/gitea/explore/repos")

        assert res.status_code == 200
        assert len(captured) == 1
        forwarded_req = captured[0]
        assert forwarded_req.url.path == "/explore/repos"
        assert "x-webauth-user" not in forwarded_req.headers
        assert "x-webauth-email" not in forwarded_req.headers


async def test_gitea_proxy_strips_spoofed_headers(app, client):
    captured = []
    upstream = _mock_upstream_client(captured)
    with patch("painkiller.api.routes.gitea_proxy._get_http_client", return_value=upstream):
        res = await client.get(
            "/gitea/explore/repos",
            headers={"X-WEBAUTH-USER": "evil_hacker", "X-WEBAUTH-EMAIL": "evil@hacker.com"},
        )

        assert res.status_code == 200
        assert len(captured) == 1
        forwarded_req = captured[0]
        assert "x-webauth-user" not in forwarded_req.headers
        assert "x-webauth-email" not in forwarded_req.headers


async def test_gitea_proxy_preserves_basic_auth_for_git_cli(app, client):
    captured = []
    upstream = _mock_upstream_client(captured)
    with patch("painkiller.api.routes.gitea_proxy._get_http_client", return_value=upstream):
        res = await client.get(
            "/gitea/user/repo.git/info/refs?service=git-upload-pack",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )

        assert res.status_code == 200
        assert len(captured) == 1
        forwarded_req = captured[0]
        assert forwarded_req.headers["authorization"] == "Basic dXNlcjpwYXNz"
