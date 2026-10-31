"""Template scaffold: unpacked into a new project's repo as its first commit."""

import os
import subprocess
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from painkiller.api.server import create_app
from painkiller.core.templates import ANDROID_TEMPLATE, ANDROID_TEMPLATE_ID, CAPACITOR_TEMPLATE, CAPACITOR_TEMPLATE_ID
from painkiller.core.scaffold import ScaffoldError, copy_scaffold_dir, extract_scaffold
from tests.auth_helpers import admin_headers


def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return str(path)


def test_extract_strips_single_root_folder_and_skips_junk(tmp_path):
    src = _zip(tmp_path / "s.zip", {
        "starter/package.json": '{"name": "x"}',
        "starter/src/app.ts": "export {}",
        "starter/node_modules/left-pad/index.js": "x",
        "starter/.git/HEAD": "ref",
        "__MACOSX/starter/._package.json": "x",
    })
    dest = tmp_path / "repo"
    dest.mkdir()

    written = extract_scaffold(src, str(dest))

    assert sorted(written) == ["package.json", "src/app.ts"]
    assert (dest / "src" / "app.ts").read_text() == "export {}"
    assert not (dest / "node_modules").exists()
    assert not (dest / ".git").exists()


def test_extract_keeps_flat_zip_as_is(tmp_path):
    src = _zip(tmp_path / "s.zip", {"pyproject.toml": "[project]", "app/main.py": "print()"})
    dest = tmp_path / "repo"
    dest.mkdir()
    assert sorted(extract_scaffold(src, str(dest))) == ["app/main.py", "pyproject.toml"]


def test_extract_refuses_path_traversal(tmp_path):
    src = _zip(tmp_path / "s.zip", {"ok.txt": "x", "../evil.txt": "x"})
    dest = tmp_path / "repo"
    dest.mkdir()
    with pytest.raises(ScaffoldError):
        extract_scaffold(src, str(dest))
    assert not (tmp_path / "evil.txt").exists()


def test_extract_refuses_non_zip(tmp_path):
    bad = tmp_path / "s.zip"
    bad.write_bytes(b"PK\x03\x04garbage")
    with pytest.raises(ScaffoldError):
        extract_scaffold(str(bad), str(tmp_path))


@pytest.fixture
async def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("PAINKILLER_STORAGE_DIR", str(tmp_path / "storage"))
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    app.state.vcs = None
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=admin_headers()) as c:
            yield app, c


async def test_create_project_from_uploaded_scaffold(app_client, tmp_path):
    app, client = app_client
    scaffold = _zip(tmp_path / "scaffold.zip", {"kit/package.json": "{}", "kit/src/main.tsx": "y"})
    await app.state.tracker.update_project_template(
        CAPACITOR_TEMPLATE_ID, name="Capacitor Kit", scaffold_path=scaffold, scaffold_filename="scaffold.zip",
    )

    res = await client.post("/api/projects", json={"name": "Loja", "api_key": "k"})

    assert res.status_code == 200, res.text
    repo = res.json()["repo_path"]
    assert os.path.exists(os.path.join(repo, "src", "main.tsx"))
    # O zip do admin substitui o embutido, não se soma a ele.
    assert not os.path.exists(os.path.join(repo, "capacitor.config.ts"))
    log = subprocess.run(["git", "log", "--format=%s"], cwd=repo, capture_output=True, text=True).stdout
    assert "scaffold from template Capacitor Kit" in log
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout == ""


async def test_create_project_defaults_to_capacitor(app_client):
    _, client = app_client
    res = await client.post("/api/projects", json={"name": "Loja", "api_key": "k"})

    assert res.status_code == 200, res.text
    # Sem template_id, o projeto nasce do Capacitor, o único template ativo.
    assert res.json()["template_id"] == CAPACITOR_TEMPLATE_ID
    repo = res.json()["repo_path"]
    assert os.path.exists(os.path.join(repo, "capacitor.config.ts"))


async def test_create_project_from_inactive_native_template_is_refused(app_client):
    _, client = app_client
    res = await client.post(
        "/api/projects", json={"name": "Loja", "api_key": "k", "template_id": ANDROID_TEMPLATE_ID}
    )
    assert res.status_code == 400


async def test_create_project_from_capacitor_template(app_client):
    app, client = app_client
    res = await client.post(
        "/api/projects", json={"name": "Clipes", "api_key": "k", "template_id": CAPACITOR_TEMPLATE_ID}
    )

    assert res.status_code == 200, res.text
    project = res.json()
    assert project["template_id"] == CAPACITOR_TEMPLATE_ID
    repo = project["repo_path"]
    tracked = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True).stdout.split()
    assert {"package.json", "package-lock.json", "capacitor.config.ts", "android/gradlew", "src/App.tsx"} <= set(tracked)
    # Só o arcabouço do Capacitor: nada do Kotlin na raiz.
    assert "settings.gradle.kts" not in tracked
    assert os.access(os.path.join(repo, "android", "gradlew"), os.X_OK)
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout == ""
    # O template fica gravado: é ele que escolhe o ambiente e a verificação das tarefas.
    stored = await app.state.tracker.get_project(project["id"])
    assert stored.template_id == CAPACITOR_TEMPLATE_ID


async def test_create_project_with_unknown_template_is_refused(app_client):
    _, client = app_client
    res = await client.post("/api/projects", json={"name": "Loja", "api_key": "k", "template_id": "nope"})
    assert res.status_code == 400


def test_bundled_scaffold_gradlew_keeps_lf(tmp_path):
    written = copy_scaffold_dir(ANDROID_TEMPLATE.scaffold_dir, str(tmp_path))
    assert "gradlew" in written and "settings.gradle.kts" in written
    # Com CRLF, `sh ./gradlew` quebra no worker Linux.
    with open(tmp_path / "gradlew", "rb") as f:
        assert b"\r\n" not in f.read()


def test_bundled_capacitor_scaffold_is_ready_to_build(tmp_path):
    written = copy_scaffold_dir(CAPACITOR_TEMPLATE.scaffold_dir, str(tmp_path))
    assert "android/gradlew" in written and "package-lock.json" in written
    with open(tmp_path / "android" / "gradlew", "rb") as f:
        assert b"\r\n" not in f.read()
    # Gerados pelo `cap sync`: entram na verificação, nunca no arcabouço.
    assert not any(w.startswith(("node_modules/", "dist/", "android/app/src/main/assets/public/")) for w in written)
