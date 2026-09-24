"""Integration tests for project routes: harness and api_key support."""

import pytest
from httpx import ASGITransport, AsyncClient
from painkiller.api.server import create_app
from tests.auth_helpers import admin_headers


@pytest.fixture
async def client(tmp_path):
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_create_project_with_harness_and_api_key(client: AsyncClient):
    headers = admin_headers()
    res = await client.post(
        "/api/projects",
        json={
            "name": "DSH Project",
            "purpose": "Testing DSH",
            "solution_description": "Solution",
            "harness": "deepseek_superpowers",
            "api_key": "sk-secret12345678",
        },
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["id"].startswith("proj-admin-dsh-project-")
    assert data["harness"] == "deepseek_superpowers"
    # Raw API key must never be exposed
    assert "sk-secret12345678" not in str(data)
    assert data.get("has_api_key") is True
    assert data.get("masked_api_key") == "sk-***5678"

    # Verify GET /api/projects/{id} also masks the key
    get_res = await client.get(f"/api/projects/{data['id']}", headers=headers)
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["harness"] == "deepseek_superpowers"
    assert "sk-secret12345678" not in str(get_data)
    assert get_data.get("has_api_key") is True
    assert get_data.get("masked_api_key") == "sk-***5678"


@pytest.mark.asyncio
async def test_update_project_harness_and_api_key(client: AsyncClient):
    headers = admin_headers()
    # Create with default harness
    res = await client.post(
        "/api/projects",
        json={
            "name": "Default Project",
            "purpose": "Testing default",
            "solution_description": "Solution",
            "api_key": "AIzaSy-gemini-key",
        },
        headers=headers,
    )
    assert res.status_code == 200
    proj = res.json()
    assert proj["harness"] == "agy_superpowers"
    assert proj.get("has_api_key") is True

    # Switching to a DeepSeek harness without a new key would keep a Gemini key.
    refused = await client.put(
        f"/api/projects/{proj['id']}",
        json={"harness": "deepseek_superpowers"},
        headers=headers,
    )
    assert refused.status_code == 400
    assert "DeepSeek" in refused.json()["detail"]

    # Update to deepseek harness with API key
    update_res = await client.put(
        f"/api/projects/{proj['id']}",
        json={
            "harness": "deepseek_superpowers",
            "api_key": "sk-deepseek-testkey",
        },
        headers=headers,
    )
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["harness"] == "deepseek_superpowers"
    assert "sk-deepseek-testkey" not in str(updated)
    assert updated.get("has_api_key") is True


@pytest.mark.asyncio
async def test_create_project_requires_api_key(client: AsyncClient):
    res = await client.post(
        "/api/projects",
        json={"name": "Sem chave", "harness": "maki_superpowers", "api_key": "  "},
        headers=admin_headers(),
    )
    assert res.status_code == 400
    assert "DeepSeek" in res.json()["detail"]


@pytest.mark.asyncio
async def test_same_provider_harness_switch_keeps_the_key(client: AsyncClient):
    headers = admin_headers()
    proj = (await client.post(
        "/api/projects",
        json={"name": "Troca", "harness": "deepseek_superpowers", "api_key": "sk-ds-key-123456"},
        headers=headers,
    )).json()
    res = await client.put(f"/api/projects/{proj['id']}", json={"harness": "maki_superpowers"}, headers=headers)
    assert res.status_code == 200
    assert res.json()["has_api_key"] is True
