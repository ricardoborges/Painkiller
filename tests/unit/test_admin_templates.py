"""Unit and integration tests for Admin Project Templates and public template listing."""

import io
import pytest
from httpx import ASGITransport, AsyncClient
from painkiller.api.server import create_app
from painkiller.core.domain.models import ProjectType, is_coolify_compatible, User, UserRole
from tests.auth_helpers import admin_headers, user_headers


@pytest.fixture
async def app_and_client(tmp_path, monkeypatch):
    monkeypatch.setenv("PAINKILLER_STORAGE_DIR", str(tmp_path / "storage"))
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield app, c


@pytest.mark.asyncio
async def test_coolify_compatibility_logic():
    assert is_coolify_compatible(ProjectType.API) is True
    assert is_coolify_compatible(ProjectType.WEB_STATIC) is True
    assert is_coolify_compatible(ProjectType.WEB_FULLSTACK) is True
    assert is_coolify_compatible(ProjectType.DESKTOP) is False
    assert is_coolify_compatible(ProjectType.MOBILE_CROSSPLATFORM) is False
    assert is_coolify_compatible(ProjectType.ANDROID_NATIVE) is False
    assert is_coolify_compatible("invalid_type") is False


@pytest.mark.asyncio
async def test_admin_template_crud(app_and_client):
    app, client = app_and_client
    headers = admin_headers()

    # 1. Create Web Fullstack template (auto Coolify compatible)
    res = await client.post(
        "/api/admin/templates",
        json={
            "name": "FastAPI + SvelteKit",
            "description": "Fullstack web app with Python and SvelteKit",
            "project_type": "web_fullstack",
            "prompt": "Siga o padrão ports and adapters.",
        },
        headers=headers,
    )
    assert res.status_code == 200
    tpl1 = res.json()
    assert tpl1["id"].startswith("tpl-")
    assert tpl1["name"] == "FastAPI + SvelteKit"
    assert tpl1["project_type"] == "web_fullstack"
    assert tpl1["coolify_compatible"] is True
    assert tpl1["is_active"] is True
    assert tpl1["prompt"] == "Siga o padrão ports and adapters."

    # 2. Create Android Native template (incompatible with Coolify)
    res2 = await client.post(
        "/api/admin/templates",
        json={
            "name": "Android Native App",
            "description": "Native Android with Kotlin and Jetpack Compose",
            "project_type": "android_native",
            "prompt": "Arquitetura MVVM limpa.",
        },
        headers=headers,
    )
    assert res2.status_code == 200
    tpl2 = res2.json()
    assert tpl2["project_type"] == "android_native"
    assert tpl2["coolify_compatible"] is False

    # 3. List admin templates
    list_res = await client.get("/api/admin/templates", headers=headers)
    assert list_res.status_code == 200
    all_tpls = list_res.json()
    assert len(all_tpls) == 2

    # 4. Get by ID
    get_res = await client.get(f"/api/admin/templates/{tpl1['id']}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "FastAPI + SvelteKit"

    # 5. Update template
    up_res = await client.put(
        f"/api/admin/templates/{tpl1['id']}",
        json={"name": "FastAPI + Svelte 5 Fullstack", "is_active": False},
        headers=headers,
    )
    assert up_res.status_code == 200
    assert up_res.json()["name"] == "FastAPI + Svelte 5 Fullstack"
    assert up_res.json()["is_active"] is False

    # 6. Delete template
    del_res = await client.delete(f"/api/admin/templates/{tpl2['id']}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True

    # Verify deleted
    get_del = await client.get(f"/api/admin/templates/{tpl2['id']}", headers=headers)
    assert get_del.status_code == 404


@pytest.mark.asyncio
async def test_admin_authorization_required(app_and_client):
    app, client = app_and_client
    tracker = app.state.tracker

    # Create a regular user in the DB
    reg_user = await tracker.create_user(email="user@example.com", name="Regular User")
    u_headers = user_headers(reg_user.id)

    # Regular user attempting admin endpoints should get 403
    res = await client.get("/api/admin/templates", headers=u_headers)
    assert res.status_code == 403

    res = await client.post(
        "/api/admin/templates",
        json={"name": "Test", "project_type": "api"},
        headers=u_headers,
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_public_active_templates_listing(app_and_client):
    app, client = app_and_client
    tracker = app.state.tracker
    adm_headers = admin_headers()

    reg_user = await tracker.create_user(email="alice@example.com", name="Alice")
    u_headers = user_headers(reg_user.id)

    # Admin creates an active and an inactive template
    await client.post(
        "/api/admin/templates",
        json={"name": "Active Web", "project_type": "web_static", "is_active": True},
        headers=adm_headers,
    )
    await client.post(
        "/api/admin/templates",
        json={"name": "Draft Mobile", "project_type": "mobile_crossplatform", "is_active": False},
        headers=adm_headers,
    )

    # Regular user calls public endpoint
    pub_res = await client.get("/api/templates", headers=u_headers)
    assert pub_res.status_code == 200
    templates = pub_res.json()
    assert len(templates) == 1
    assert templates[0]["name"] == "Active Web"


@pytest.mark.asyncio
async def test_template_skill_and_scaffold_upload_download_delete(app_and_client):
    app, client = app_and_client
    headers = admin_headers()

    # Create template
    res = await client.post(
        "/api/admin/templates",
        json={"name": "Scaffolded API", "project_type": "api"},
        headers=headers,
    )
    assert res.status_code == 200
    tpl_id = res.json()["id"]

    # 1. Invalid skill file format (e.g. .txt)
    bad_file = ("bad.txt", io.BytesIO(b"hello world"), "text/plain")
    res_bad = await client.post(
        f"/api/admin/templates/{tpl_id}/skill",
        files={"file": bad_file},
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
    data = res_skill.json()
    assert data["skill_filename"] == "architecture_skill.md"
    assert data["skill_path"] is not None

    # Download skill
    dl_skill = await client.get(f"/api/admin/templates/{tpl_id}/skill/download", headers=headers)
    assert dl_skill.status_code == 200
    assert dl_skill.content == skill_content

    # 3. Upload valid scaffold file (.zip)
    scaffold_content = b"PK\x03\x04mockzipcontent"
    res_scaffold = await client.post(
        f"/api/admin/templates/{tpl_id}/scaffold",
        files={"file": ("starter_scaffold.zip", io.BytesIO(scaffold_content), "application/zip")},
        headers=headers,
    )
    assert res_scaffold.status_code == 200
    data2 = res_scaffold.json()
    assert data2["scaffold_filename"] == "starter_scaffold.zip"
    assert data2["scaffold_path"] is not None

    # Download scaffold
    dl_scaffold = await client.get(f"/api/admin/templates/{tpl_id}/scaffold/download", headers=headers)
    assert dl_scaffold.status_code == 200
    assert dl_scaffold.content == scaffold_content

    # 4. Delete skill and scaffold
    del_skill = await client.delete(f"/api/admin/templates/{tpl_id}/skill", headers=headers)
    assert del_skill.status_code == 200
    assert del_skill.json()["skill_path"] is None

    del_scaffold = await client.delete(f"/api/admin/templates/{tpl_id}/scaffold", headers=headers)
    assert del_scaffold.status_code == 200
    assert del_scaffold.json()["scaffold_path"] is None
