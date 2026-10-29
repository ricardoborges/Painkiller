"""Template scaffold: unpacked into a new project's repo as its first commit."""

import os
import subprocess
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from painkiller.api.server import create_app
from painkiller.core.android_template import ANDROID_TEMPLATE_ID, BUNDLED_SCAFFOLD_DIR
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
    scaffold = _zip(tmp_path / "scaffold.zip", {"kit/settings.gradle.kts": "x", "kit/app/build.gradle.kts": "y"})
    await app.state.tracker.update_project_template(
        ANDROID_TEMPLATE_ID, name="Android Hilt", scaffold_path=scaffold, scaffold_filename="scaffold.zip",
    )

    res = await client.post("/api/projects", json={"name": "Loja", "api_key": "k"})

    assert res.status_code == 200, res.text
    repo = res.json()["repo_path"]
    assert os.path.exists(os.path.join(repo, "app", "build.gradle.kts"))
    # O zip do admin substitui o embutido, não se soma a ele.
    assert not os.path.exists(os.path.join(repo, "gradlew"))
    log = subprocess.run(["git", "log", "--format=%s"], cwd=repo, capture_output=True, text=True).stdout
    assert "scaffold from template Android Hilt" in log
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout == ""


async def test_create_project_uses_bundled_android_scaffold(app_client):
    _, client = app_client
    res = await client.post("/api/projects", json={"name": "Loja", "api_key": "k"})

    assert res.status_code == 200, res.text
    repo = res.json()["repo_path"]
    tracked = subprocess.run(["git", "ls-files", "-s"], cwd=repo, capture_output=True, text=True).stdout
    assert "app/src/main/AndroidManifest.xml" in tracked
    assert "gradle/wrapper/gradle-wrapper.jar" in tracked
    assert "local.properties" not in tracked
    # Árvore limpa: a primeira tarefa não herda nada pendente.
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout == ""


async def test_create_project_with_unknown_template_is_refused(app_client):
    _, client = app_client
    res = await client.post("/api/projects", json={"name": "Loja", "api_key": "k", "template_id": "nope"})
    assert res.status_code == 400


def test_bundled_scaffold_gradlew_keeps_lf(tmp_path):
    written = copy_scaffold_dir(BUNDLED_SCAFFOLD_DIR, str(tmp_path))
    assert "gradlew" in written and "settings.gradle.kts" in written
    # Com CRLF, `sh ./gradlew` quebra no worker Linux.
    with open(tmp_path / "gradlew", "rb") as f:
        assert b"\r\n" not in f.read()
