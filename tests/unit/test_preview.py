"""The app preview: promoted on task completion, served sandboxed to the backlog's phone frame."""

import time

import pytest
from httpx import ASGITransport, AsyncClient

from painkiller.api import security
from painkiller.api.server import create_app
from painkiller.core.preview import promote_preview, read_preview
from tests.auth_helpers import admin_headers, user_headers


def _stage(repo, files=None):
    staged = repo / ".painkiller" / "preview-build"
    for name, content in (files or {"index.html": "<html><head><title>x</title></head><body></body></html>"}).items():
        path = staged / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return staged


def test_promote_replaces_the_previous_preview(tmp_path):
    assert read_preview(str(tmp_path)) is None
    _stage(tmp_path, {"index.html": "<html><head></head></html>", "assets/old.js": "1"})
    promote_preview(str(tmp_path), "t1", "Primeira")
    _stage(tmp_path, {"index.html": "<html><head></head></html>", "assets/new.js": "2"})

    meta = promote_preview(str(tmp_path), "t2", "Segunda")

    assert meta["task_id"] == "t2"
    assert read_preview(str(tmp_path))["task_title"] == "Segunda"
    preview = tmp_path / ".painkiller" / "preview"
    assert (preview / "assets" / "new.js").exists()
    assert not (preview / "assets" / "old.js").exists()
    assert not (tmp_path / ".painkiller" / "preview-build").exists()


def test_promote_without_a_build_keeps_the_current_preview(tmp_path):
    _stage(tmp_path)
    promote_preview(str(tmp_path), "t1", "Primeira")

    assert promote_preview(str(tmp_path), "t2", "Sem build") is None
    assert read_preview(str(tmp_path))["task_id"] == "t1"


def test_preview_key_is_bound_to_the_project_and_expires(monkeypatch):
    key = security.issue_preview_key("p1")
    assert security.verify_preview_key("p1", key)
    assert not security.verify_preview_key("p2", key)
    assert not security.verify_preview_key("p1", "garbage")
    # Estável no dia: o iframe não recarrega a cada leitura.
    assert security.issue_preview_key("p1") == key
    monkeypatch.setattr(time, "time", lambda: int(key.split(".")[0]) + 1)
    assert not security.verify_preview_key("p1", key)


@pytest.fixture
async def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("PAINKILLER_STORAGE_DIR", str(tmp_path / "storage"))
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    app.state.vcs = None
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield app, c


async def _project(client):
    res = await client.post("/api/projects", json={"name": "Clipes", "api_key": "k"}, headers=admin_headers())
    assert res.status_code == 200, res.text
    return res.json()


async def test_preview_info_before_and_after_a_build(app_client):
    _, client = app_client
    project = await _project(client)

    res = await client.get(f"/api/projects/{project['id']}/preview", headers=admin_headers())
    assert res.json() == {
        "supported": True, "available": False, "url": None,
        "task_id": None, "task_title": None, "built_at": None,
    }

    from pathlib import Path
    repo = Path(project["repo_path"])
    _stage(repo, {"index.html": "<html><head><title>x</title></head></html>", "assets/app.js": "console.log(1)"})
    promote_preview(str(repo), "t1", "Lista de clipes")

    info = (await client.get(f"/api/projects/{project['id']}/preview", headers=admin_headers())).json()
    assert info["available"] is True
    assert info["task_title"] == "Lista de clipes"
    assert info["url"].startswith(f"/preview/{project['id']}/")

    # O iframe não manda cabeçalhos: a chave da URL basta.
    page = await client.get(info["url"])
    assert page.status_code == 200
    base = info["url"].split("?")[0]
    assert f'<head><base href="{base}"><script>' in page.text
    assert "history.replaceState" in page.text
    # Isolado: origem opaca, sem acesso ao token do Painkiller.
    assert page.headers["content-security-policy"].startswith("sandbox allow-scripts")
    assert "allow-same-origin" not in page.headers["content-security-policy"]

    asset = await client.get(base + "assets/app.js")
    assert asset.status_code == 200
    assert asset.headers["access-control-allow-origin"] == "*"
    assert "javascript" in asset.headers["content-type"]

    assert (await client.get(base + "assets/missing.js")).status_code == 404
    assert (await client.get(base + "%2e%2e/%2e%2e/%2e%2e/etc/passwd")).status_code == 404


async def test_preview_refuses_a_bad_key_and_other_owners(app_client):
    app, client = app_client
    project = await _project(client)
    from pathlib import Path
    _stage(Path(project["repo_path"]))
    promote_preview(project["repo_path"], "t1", "x")

    res = await client.get(f"/preview/{project['id']}/{security.issue_preview_key('other')}/")
    assert res.status_code == 404

    stranger = await app.state.tracker.create_user(email="s@example.com", name="S")
    res = await client.get(f"/api/projects/{project['id']}/preview", headers=user_headers(stranger.id))
    assert res.status_code == 404
