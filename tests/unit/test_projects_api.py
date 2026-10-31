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


@pytest.mark.asyncio
async def test_effort_is_stored_per_project_and_follows_the_harness(client: AsyncClient):
    headers = admin_headers()
    bad = await client.post("/api/projects", json={"name": "X", "api_key": "k", "effort": "turbo"}, headers=headers)
    assert bad.status_code == 400

    proj = (await client.post(
        "/api/projects",
        json={"name": "Esforço", "api_key": "AIza-key", "model": "gemini-3.8-pro", "effort": "high"},
        headers=headers,
    )).json()
    assert (proj["model"], proj["effort"]) == ("gemini-3.8-pro", "high")

    # dsh também tem esforço: trocar para ele mantém o valor.
    kept = (await client.put(f"/api/projects/{proj['id']}", json={"harness": "deepseek_superpowers", "api_key": "sk-ds"}, headers=headers)).json()
    assert kept["effort"] == "high"

    # Maki não tem: o valor é apagado.
    dropped = (await client.put(f"/api/projects/{proj['id']}", json={"harness": "maki_superpowers"}, headers=headers)).json()
    assert dropped["effort"] is None


@pytest.mark.asyncio
async def test_implementation_notes_are_optional_and_editable(client: AsyncClient):
    headers = admin_headers()
    res = await client.post(
        "/api/projects",
        json={"name": "Notes", "purpose": "p", "solution_description": "s", "api_key": "AIzaSyTest1234"},
        headers=headers,
    )
    assert res.status_code == 200
    proj = res.json()
    assert proj["implementation_notes"] == ""

    upd = await client.put(
        f"/api/projects/{proj['id']}",
        json={"implementation_notes": "Valores em centavos."},
        headers=headers,
    )
    assert upd.status_code == 200
    assert upd.json()["implementation_notes"] == "Valores em centavos."
    # Um PUT sem o campo não o apaga.
    upd = await client.put(f"/api/projects/{proj['id']}", json={"name": "Notes 2"}, headers=headers)
    assert upd.json()["implementation_notes"] == "Valores em centavos."


async def _project(client: AsyncClient) -> str:
    res = await client.post(
        "/api/projects",
        json={"name": "Tasks", "purpose": "p", "solution_description": "s", "api_key": "AIza-test-key-1234"},
        headers=admin_headers(),
    )
    assert res.status_code == 200
    return res.json()["id"]


@pytest.mark.asyncio
async def test_manual_task_can_be_deleted(client: AsyncClient):
    headers = admin_headers()
    project_id = await _project(client)
    res = await client.post(f"/api/projects/{project_id}/tasks", json={"title": "À mão"}, headers=headers)
    assert res.status_code == 200
    task = res.json()
    assert task["manual"] is True

    res = await client.delete(f"/api/tasks/{task['id']}", headers=headers)
    assert res.status_code == 200
    res = await client.get(f"/api/projects/{project_id}/tasks", headers=headers)
    assert res.json() == []


@pytest.mark.asyncio
async def test_imported_task_cannot_be_deleted(client: AsyncClient):
    headers = admin_headers()
    project_id = await _project(client)
    tracker = client._transport.app.state.tracker
    task = await tracker.create_task(project_id=project_id, title="Da spec", description="")
    assert task.manual is False

    res = await client.delete(f"/api/tasks/{task.id}", headers=headers)
    assert res.status_code == 409
    assert await tracker.get_task(task.id) is not None


@pytest.mark.asyncio
async def test_manual_task_with_dependents_or_completed_is_kept(client: AsyncClient):
    from painkiller.core.domain.models import TaskStatus

    headers = admin_headers()
    project_id = await _project(client)
    base = (await client.post(f"/api/projects/{project_id}/tasks", json={"title": "Base"}, headers=headers)).json()
    await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"title": "Depois", "dependencies": [base["id"]]},
        headers=headers,
    )
    res = await client.delete(f"/api/tasks/{base['id']}", headers=headers)
    assert res.status_code == 409
    assert "Depois" in res.json()["detail"]

    tracker = client._transport.app.state.tracker
    done = (await client.post(f"/api/projects/{project_id}/tasks", json={"title": "Feita"}, headers=headers)).json()
    await tracker.update_task_status(done["id"], TaskStatus.COMPLETED)
    res = await client.delete(f"/api/tasks/{done['id']}", headers=headers)
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_legacy_tasks_are_classified_on_startup(tmp_path):
    """Rows from before the `manual` column: a lone task was added by hand, a batch was imported."""
    from datetime import datetime, timedelta

    from sqlalchemy import text

    from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker

    url = f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}"
    tracker = SQLiteIssueTracker(url)
    await tracker.init_db()
    a = await tracker.create_task(project_id="p", title="A", description="", session_id="s")
    b = await tracker.create_task(project_id="p", title="B", description="", session_id="s")
    lone = await tracker.create_task(project_id="p", title="Solo", description="", session_id="s")
    fix = await tracker.create_task(project_id="p", title="Fix", description="x\ndeploy-fix: d1", session_id="s")
    later = datetime.now() + timedelta(hours=1)
    async with tracker.engine.begin() as conn:
        await conn.execute(text("UPDATE tasks SET manual = NULL"))
        await conn.execute(text("UPDATE tasks SET created_at = :t WHERE id = :id"), {"t": later, "id": lone.id})
        await conn.execute(
            text("UPDATE tasks SET created_at = :t WHERE id = :id"),
            {"t": later + timedelta(hours=1), "id": fix.id},
        )
    await tracker.close()

    tracker = SQLiteIssueTracker(url)
    await tracker.init_db()
    assert (await tracker.get_task(a.id)).manual is False
    assert (await tracker.get_task(b.id)).manual is False
    assert (await tracker.get_task(lone.id)).manual is True
    assert (await tracker.get_task(fix.id)).manual is False
    await tracker.close()
