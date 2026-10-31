"""The built-in templates (Capacitor active, native Android inactive): seeded at startup, configured (never created) by the admin."""

import io
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient
from painkiller.api.server import create_app
from painkiller.core.templates import (
    ANDROID_TEMPLATE,
    ANDROID_TEMPLATE_ID,
    CAPACITOR_TEMPLATE,
    CAPACITOR_TEMPLATE_ID,
    ensure_builtin_templates,
)
from tests.auth_helpers import admin_headers, user_headers


@pytest.fixture
async def app_and_client(tmp_path, monkeypatch):
    monkeypatch.setenv("PAINKILLER_STORAGE_DIR", str(tmp_path / "storage"))
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield app, c


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


async def test_builtin_templates_are_seeded(app_and_client):
    _, client = app_and_client
    res = await client.get("/api/admin/templates", headers=admin_headers())
    assert res.status_code == 200
    templates = {t["id"]: t for t in res.json()}
    assert set(templates) == {ANDROID_TEMPLATE_ID, CAPACITOR_TEMPLATE_ID}
    for spec, project_type in ((ANDROID_TEMPLATE, "android_native"), (CAPACITOR_TEMPLATE, "capacitor_react")):
        tpl = templates[spec.id]
        assert tpl["project_type"] == project_type
        assert tpl["coolify_compatible"] is False
        assert tpl["is_active"] is spec.active
        assert tpl["prompt"] == spec.prompt
        assert tpl["bundled_scaffold"] is True


async def test_seed_drops_other_templates_and_keeps_admin_edits(app_and_client):
    app, client = app_and_client
    tracker = app.state.tracker
    await tracker.update_project_template(ANDROID_TEMPLATE_ID, prompt="Use Hilt.")
    # Resto da edição generalista, com um tipo que não existe mais.
    await tracker.create_project_template(name="Web", project_type="android_native", template_id="tpl-web")
    from sqlalchemy import text
    async with tracker.engine.begin() as conn:
        await conn.execute(text("UPDATE project_templates SET project_type='WEB_FULLSTACK' WHERE id='tpl-web'"))

    await ensure_builtin_templates(tracker)

    templates = {t.id: t for t in await tracker.list_project_templates()}
    assert set(templates) == {ANDROID_TEMPLATE_ID, CAPACITOR_TEMPLATE_ID}
    assert templates[ANDROID_TEMPLATE_ID].prompt == "Use Hilt."


async def test_seed_keeps_native_android_inactive(app_and_client):
    app, _ = app_and_client
    tracker = app.state.tracker
    # Um banco em que o nativo ainda estava ativo volta ao estado fixo.
    await tracker.update_project_template(ANDROID_TEMPLATE_ID, is_active=True)
    await ensure_builtin_templates(tracker)
    assert (await tracker.get_project_template(ANDROID_TEMPLATE_ID)).is_active is False
    assert (await tracker.get_project_template(CAPACITOR_TEMPLATE_ID)).is_active is True


async def test_admin_cannot_create_or_delete_templates(app_and_client):
    _, client = app_and_client
    headers = admin_headers()
    res = await client.post("/api/admin/templates", json={"name": "Web"}, headers=headers)
    assert res.status_code == 405
    res = await client.delete(f"/api/admin/templates/{ANDROID_TEMPLATE_ID}", headers=headers)
    assert res.status_code == 405


async def test_admin_updates_the_template(app_and_client):
    _, client = app_and_client
    headers = admin_headers()
    res = await client.put(
        f"/api/admin/templates/{ANDROID_TEMPLATE_ID}",
        json={"name": "Android (Hilt)", "description": "Com DI", "prompt": "Use Hilt."},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Android (Hilt)"
    assert res.json()["prompt"] == "Use Hilt."

    res = await client.put(f"/api/admin/templates/{ANDROID_TEMPLATE_ID}", json={"name": "  "}, headers=headers)
    assert res.status_code == 400


async def test_admin_authorization_required(app_and_client):
    app, client = app_and_client
    reg_user = await app.state.tracker.create_user(email="user@example.com", name="Regular User")
    u_headers = user_headers(reg_user.id)

    assert (await client.get("/api/admin/templates", headers=u_headers)).status_code == 403
    res = await client.put(f"/api/admin/templates/{ANDROID_TEMPLATE_ID}", json={"prompt": "x"}, headers=u_headers)
    assert res.status_code == 403

    # A listagem pública (formulário de projeto) mostra só o template ativo.
    pub = await client.get("/api/templates", headers=u_headers)
    assert pub.status_code == 200
    assert {t["id"] for t in pub.json()} == {CAPACITOR_TEMPLATE_ID}


async def test_bundled_scaffold_downloads_as_zip(app_and_client):
    _, client = app_and_client
    res = await client.get(f"/api/admin/templates/{ANDROID_TEMPLATE_ID}/scaffold/download", headers=admin_headers())
    assert res.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(res.content)).namelist()
    assert "gradlew" in names
    assert "app/build.gradle.kts" in names
    assert not any(n.startswith(("build/", ".gradle/")) or n == "local.properties" for n in names)


async def test_bundled_capacitor_scaffold_downloads_as_zip(app_and_client):
    _, client = app_and_client
    res = await client.get(f"/api/admin/templates/{CAPACITOR_TEMPLATE_ID}/scaffold/download", headers=admin_headers())
    assert res.status_code == 200
    assert 'filename="capacitor-react.zip"' in res.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(res.content))
    names = archive.namelist()
    assert {"package.json", "capacitor.config.ts", "src/App.tsx", "android/settings.gradle"} <= set(names)
    assert not any(n.startswith(("node_modules/", "dist/")) for n in names)
    # O gradlew de android/ sai executável, como o da raiz no template nativo.
    assert (archive.getinfo("android/gradlew").external_attr >> 16) & 0o111


async def test_template_skill_and_scaffold_upload_download_delete(app_and_client):
    _, client = app_and_client
    headers = admin_headers()
    tpl_id = ANDROID_TEMPLATE_ID

    # 1. Invalid skill file format (e.g. .txt)
    res_bad = await client.post(
        f"/api/admin/templates/{tpl_id}/skill",
        files={"file": ("bad.txt", io.BytesIO(b"hello world"), "text/plain")},
        headers=headers,
    )
    assert res_bad.status_code == 400

    # 2. Upload valid skill file (.md)
    skill_content = b"# Skill definition\nGuidelines here"
    res_skill = await client.post(
        f"/api/admin/templates/{tpl_id}/skill",
        files={"file": ("architecture_skill.md", io.BytesIO(skill_content), "text/markdown")},
        headers=headers,
    )
    assert res_skill.status_code == 200
    assert res_skill.json()["skill_filename"] == "architecture_skill.md"

    dl_skill = await client.get(f"/api/admin/templates/{tpl_id}/skill/download", headers=headers)
    assert dl_skill.status_code == 200
    assert dl_skill.content == skill_content

    # 3. A .zip that is not a zip is refused and keeps the bundled scaffold.
    res_bad_zip = await client.post(
        f"/api/admin/templates/{tpl_id}/scaffold",
        files={"file": ("broken.zip", io.BytesIO(b"PK\x03\x04garbage"), "application/zip")},
        headers=headers,
    )
    assert res_bad_zip.status_code == 400

    # 4. Upload valid scaffold file (.zip)
    scaffold_content = _zip_bytes({"app/settings.gradle.kts": 'rootProject.name = "Mine"'})
    res_scaffold = await client.post(
        f"/api/admin/templates/{tpl_id}/scaffold",
        files={"file": ("my_android.zip", io.BytesIO(scaffold_content), "application/zip")},
        headers=headers,
    )
    assert res_scaffold.status_code == 200
    data = res_scaffold.json()
    assert data["scaffold_filename"] == "my_android.zip"
    assert data["bundled_scaffold"] is False

    dl_scaffold = await client.get(f"/api/admin/templates/{tpl_id}/scaffold/download", headers=headers)
    assert dl_scaffold.status_code == 200
    assert dl_scaffold.content == scaffold_content

    # 5. Delete skill and scaffold: the bundled scaffold is back.
    del_skill = await client.delete(f"/api/admin/templates/{tpl_id}/skill", headers=headers)
    assert del_skill.status_code == 200
    assert del_skill.json()["skill_path"] is None

    del_scaffold = await client.delete(f"/api/admin/templates/{tpl_id}/scaffold", headers=headers)
    assert del_scaffold.status_code == 200
    assert del_scaffold.json()["scaffold_path"] is None
    assert del_scaffold.json()["bundled_scaffold"] is True
