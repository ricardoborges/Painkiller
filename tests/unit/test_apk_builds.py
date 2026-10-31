"""APK builds: scripts, the background service and the routes (docker is faked)."""

import json
import os
import shutil
import subprocess

import pytest
from httpx import ASGITransport, AsyncClient

from painkiller.api.server import create_app
from painkiller.core.apk import (
    APK_FILE,
    UNSIGNED_FILE,
    apk_path,
    build_apk_script,
    build_dir,
    parse_commit,
    sign_apk_script,
    signing_env,
)
from tests.auth_helpers import admin_headers


def _capacitor_repo(path) -> str:
    (path / "package.json").write_text("{}")
    (path / "capacitor.config.ts").write_text("export default {}")
    return str(path)


def test_debug_script_builds_a_clone_of_the_branch(tmp_path):
    script = build_apk_script(_capacitor_repo(tmp_path), "apk-1", "debug", "main")
    assert "clone --quiet --no-hardlinks --branch main /workspace /tmp/src" in script
    assert "npx cap sync android" in script
    assert "assembleDebug" in script
    assert f"/workspace/.painkiller/apks/apk-1/{APK_FILE}" in script


def test_release_script_leaves_the_apk_unsigned_for_the_signing_step(tmp_path):
    script = build_apk_script(_capacitor_repo(tmp_path), "apk-2", "release", "main")
    assert "assembleRelease" in script
    assert f"/workspace/.painkiller/apks/apk-2/{UNSIGNED_FILE}" in script
    # A chave nunca entra no contêiner que roda o código do repositório.
    assert "/signing" not in script


def test_only_the_debug_script_opens_http_for_the_backend(tmp_path):
    repo = _capacitor_repo(tmp_path)
    assert "allowMixedContent" in build_apk_script(repo, "apk-3", "debug", "main")
    assert "allowMixedContent" not in build_apk_script(repo, "apk-4", "release", "main")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
@pytest.mark.parametrize("backend", [True, False])
def test_debug_http_lines_patch_the_synced_config(tmp_path, backend):
    from painkiller.core.apk import _debug_http_lines

    assets = tmp_path / "android" / "app" / "src" / "main" / "assets"
    assets.mkdir(parents=True)
    (assets / "capacitor.config.json").write_text('{"appId": "x", "android": {"path": "android"}}')
    if backend:
        (tmp_path / "backend").mkdir()
        (tmp_path / "backend" / "Dockerfile").write_text("FROM python\n")

    proc = subprocess.run(["sh", "-c", "\n".join(_debug_http_lines())], cwd=tmp_path, capture_output=True, text=True)

    assert proc.returncode == 0, proc.stderr
    config = json.loads((assets / "capacitor.config.json").read_text())
    manifest = tmp_path / "android" / "app" / "src" / "debug" / "AndroidManifest.xml"
    if backend:
        assert config["android"] == {"path": "android", "allowMixedContent": True}
        assert 'android:usesCleartextTraffic="true"' in manifest.read_text()
    else:
        assert "allowMixedContent" not in config["android"]
        assert not manifest.exists()


def test_native_gradle_repo_builds_at_the_root(tmp_path):
    (tmp_path / "settings.gradle.kts").write_text("")
    script = build_apk_script(str(tmp_path), "apk-3", "debug", "main")
    assert "npm" not in script and "cd android" not in script
    assert "assembleDebug" in script


def test_repo_without_android_build_has_no_script(tmp_path):
    assert build_apk_script(str(tmp_path), "apk-4", "debug", "main") is None


def test_sign_script_creates_the_key_once_and_verifies():
    script = sign_apk_script()
    assert "if [ ! -f /signing/release.jks ]" in script
    assert "apksigner\" sign" in script and "apksigner\" verify" in script
    assert signing_env('Meu, "App"=1')["PK_SIGNING_DN"] == "CN=Meu App1"


def test_parse_commit():
    assert parse_commit("x\nPAINKILLER_COMMIT=abc123\ny") == "abc123"
    assert parse_commit("nada") is None


class FakeSandbox:
    def __init__(self, code: int = 0, write: bool = True):
        self.code = code
        self.write = write
        self.calls: list[dict] = []

    async def build_apk(self, **kwargs) -> tuple[int, str]:
        self.calls.append(kwargs)
        if self.write:
            folder = build_dir(kwargs["repo_path"], kwargs["build_id"])
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, APK_FILE), "wb") as f:
                f.write(b"PK" * 10)
        return self.code, "PAINKILLER_COMMIT=deadbee\nBUILD SUCCESSFUL"


@pytest.fixture
async def env(tmp_path):
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'apk.db'}")
    async with app.router.lifespan_context(app):
        sandbox = FakeSandbox()
        app.state.apk_builds.sandbox = sandbox
        repo = tmp_path / "repo"
        repo.mkdir()
        project = await app.state.tracker.create_project(
            name="Meu App", repo_path=_capacitor_repo(repo), api_key="k"
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, client, project, sandbox


async def test_build_runs_in_background_and_can_be_downloaded(env):
    app, client, project, sandbox = env
    res = await client.post(
        f"/api/projects/{project.id}/apk-builds", json={"variant": "release"}, headers=admin_headers()
    )
    assert res.status_code == 200
    build = res.json()
    assert build["status"] == "BUILDING"
    await app.state.apk_builds.drain()

    assert sandbox.calls[0]["variant"] == "release"
    assert sandbox.calls[0]["branch"] == project.default_branch
    res = await client.get(f"/api/projects/{project.id}/apk-builds", headers=admin_headers())
    [done] = res.json()
    assert done["status"] == "SUCCESS"
    assert done["available"] is True
    assert done["commit_sha"] == "deadbee"
    assert done["size_bytes"] == 20

    res = await client.get(
        f"/api/projects/{project.id}/apk-builds/{build['id']}/download", headers=admin_headers()
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.android.package-archive"
    assert 'filename="Meu-App-release-deadbee.apk"' in res.headers["content-disposition"]


async def test_failed_build_is_recorded(env):
    app, client, project, sandbox = env
    sandbox.code, sandbox.write = 1, False
    res = await client.post(f"/api/projects/{project.id}/apk-builds", json={}, headers=admin_headers())
    await app.state.apk_builds.drain()
    build = (await client.get(
        f"/api/projects/{project.id}/apk-builds/{res.json()['id']}", headers=admin_headers()
    )).json()
    assert build["variant"] == "debug"
    assert build["status"] == "FAILED"
    assert "BUILD SUCCESSFUL" in build["logs"]
    res = await client.get(
        f"/api/projects/{project.id}/apk-builds/{build['id']}/download", headers=admin_headers()
    )
    assert res.status_code == 404


async def test_orphaned_build_is_marked_failed(env):
    from painkiller.core.domain.models import ApkBuild

    app, client, project, _ = env
    await app.state.tracker.save_apk_build(ApkBuild(id="apk-old", project_id=project.id))
    [build] = (await client.get(f"/api/projects/{project.id}/apk-builds", headers=admin_headers())).json()
    assert build["status"] == "FAILED"
    assert build["error"]


async def test_project_without_android_build_is_refused(env, tmp_path):
    app, client, _, _ = env
    empty = tmp_path / "empty"
    empty.mkdir()
    project = await app.state.tracker.create_project(name="Web", repo_path=str(empty), api_key="k")
    res = await client.post(f"/api/projects/{project.id}/apk-builds", json={}, headers=admin_headers())
    assert res.status_code == 400


async def test_old_builds_are_pruned_but_the_last_release_stays(env):
    app, client, project, _ = env
    service = app.state.apk_builds
    release = await service.start(project, "release")
    await service.drain()
    for _ in range(11):
        await service.start(project, "debug")
        await service.drain()
    assert os.path.isfile(apk_path(project.repo_path, release.id))
    builds = await service.list_builds(project, limit=100)
    assert sum(b.available for b in builds) == 11


def test_signing_reads_the_password_file_only_once():
    # O apksigner lê cada fonte `file:` como um só fluxo: o mesmo arquivo em
    # --ks-pass e --key-pass dava EOF na senha da chave.
    script = sign_apk_script()
    assert "--ks-pass file:/signing/password" in script
    assert "--key-pass" not in script


async def test_signed_link_downloads_without_a_session(env):
    app, client, project, sandbox = env
    res = await client.post(f"/api/projects/{project.id}/apk-builds", json={}, headers=admin_headers())
    build_id = res.json()["id"]
    await app.state.apk_builds.drain()

    res = await client.get(f"/api/projects/{project.id}/apk-builds/{build_id}/link", headers=admin_headers())
    assert res.status_code == 200
    link = res.json()
    assert link["url"].startswith(app.state.platform.public_url() + f"/apk/{project.id}/{build_id}/")
    assert link["url"].endswith("/Meu-App-debug-deadbee.apk")
    assert link["local"] is True  # sem URL pública configurada, cai no localhost

    path = link["url"].split("://", 1)[1].split("/", 1)[1]
    res = await client.get(f"/{path}")  # sem cabeçalho de autorização
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.android.package-archive"
    assert res.content == b"PK" * 10

    # A chave vale só para aquele build e não pode ser adulterada.
    parts = path.split("/")
    tampered = "/".join(parts[:3] + [parts[3][:-1] + ("A" if parts[3][-1] != "A" else "B")] + parts[4:])
    assert (await client.get(f"/{tampered}")).status_code == 404
    other = "/".join(parts[:2] + ["outro-build"] + parts[3:])
    assert (await client.get(f"/{other}")).status_code == 404


async def test_link_requires_a_ready_build(env):
    app, client, project, sandbox = env
    res = await client.get(f"/api/projects/{project.id}/apk-builds/nada/link", headers=admin_headers())
    assert res.status_code == 404
    res = await client.get(f"/api/projects/{project.id}/apk-builds/nada/link")
    assert res.status_code == 401


def test_expired_apk_key_is_refused(monkeypatch):
    from painkiller.api import security

    key, _ = security.issue_apk_key("p", "b", ttl_seconds=-1)
    assert not security.verify_apk_key("p", "b", key)
    key, _ = security.issue_apk_key("p", "b")
    assert security.verify_apk_key("p", "b", key)
    assert not security.verify_apk_key("p", "c", key)
    assert not security.verify_apk_key("p", "b", "lixo")


# ---- backend: VITE_API_URL e o release ------------------------------------------------


def _add_backend(project):
    folder = os.path.join(project.repo_path, "backend")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "Dockerfile"), "w") as f:
        f.write("FROM python:3.13-slim\n")


async def _save_backend_deploy(app, project, url, status="HEALTHY"):
    from painkiller.core.domain.models import (
        DeploymentComponent,
        DeploymentRecord,
        DeploymentStatus,
        EnvironmentType,
    )

    await app.state.tracker.save_deployment(DeploymentRecord(
        id=f"dep-{status}", project_id=project.id, environment=EnvironmentType.PRODUCTION,
        component=DeploymentComponent.BACKEND, status=DeploymentStatus(status), url=url,
    ))


async def test_debug_apk_gets_the_test_backend_url(env):
    app, client, project, sandbox = env
    _add_backend(project)
    res = await client.post(f"/api/projects/{project.id}/apk-builds", json={}, headers=admin_headers())
    assert res.status_code == 200
    await app.state.apk_builds.drain()
    assert sandbox.calls[0]["extra_env"]["VITE_API_URL"].endswith("-api-test.127.0.0.1.nip.io")


async def test_release_without_a_production_backend_is_refused(env):
    app, client, project, sandbox = env
    _add_backend(project)
    url = f"/api/projects/{project.id}/apk-builds"

    res = await client.post(url, json={"variant": "release"}, headers=admin_headers())
    assert res.status_code == 409
    assert "Publique o backend" in res.json()["detail"]

    await _save_backend_deploy(app, project, "http://app-api-production.local")
    res = await client.post(url, json={"variant": "release"}, headers={**admin_headers(), "Accept-Language": "en-US"})
    assert res.status_code == 409
    assert res.json()["detail"].startswith("The production backend is on http")
    assert sandbox.calls == []


async def test_release_gets_the_production_backend_url(env):
    app, client, project, sandbox = env
    _add_backend(project)
    await _save_backend_deploy(app, project, "https://app-api-production.example.com")

    res = await client.post(
        f"/api/projects/{project.id}/apk-builds", json={"variant": "release"}, headers=admin_headers()
    )
    assert res.status_code == 200
    await app.state.apk_builds.drain()
    assert sandbox.calls[0]["extra_env"] == {"VITE_API_URL": "https://app-api-production.example.com"}


async def test_release_without_backend_needs_nothing(env):
    app, client, project, sandbox = env
    res = await client.post(
        f"/api/projects/{project.id}/apk-builds", json={"variant": "release"}, headers=admin_headers()
    )
    assert res.status_code == 200
    await app.state.apk_builds.drain()
    assert sandbox.calls[0]["extra_env"] is None


async def test_apk_build_gets_app_secrets_and_its_log_hides_them(env):
    from painkiller.core.domain.models import SecretScope

    app, client, project, sandbox = env
    value = "AIzaMapsPublicKey123"
    await app.state.tracker.put_secret(project.id, "VITE_MAPS_KEY", SecretScope.APP, value)
    await app.state.tracker.put_secret(project.id, "OPENAI_API_KEY", SecretScope.SERVER, "sk-never-in-the-app")
    original = sandbox.build_apk

    async def leaky(**kwargs):
        code, logs = await original(**kwargs)
        return code, f"{logs}\nVITE_MAPS_KEY={value}"

    sandbox.build_apk = leaky
    res = await client.post(f"/api/projects/{project.id}/apk-builds", json={}, headers=admin_headers())
    await app.state.apk_builds.drain()

    assert sandbox.calls[0]["extra_env"] == {"VITE_MAPS_KEY": value}
    build = (await client.get(f"/api/projects/{project.id}/apk-builds/{res.json()['id']}", headers=admin_headers())).json()
    assert value not in (build.get("logs") or "")
