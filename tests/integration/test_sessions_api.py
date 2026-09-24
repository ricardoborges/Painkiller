import os
import tempfile
import pytest
from httpx import AsyncClient, ASGITransport
from painkiller.api.server import create_app
from tests.auth_helpers import admin_headers
from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker


@pytest.fixture
async def app_client():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        app = create_app(db_url=f"sqlite+aiosqlite:///{db_path}")
        tracker: SQLiteIssueTracker = app.state.tracker
        await tracker.init_db()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=admin_headers()) as client:
            yield client
        await tracker.close()


@pytest.mark.asyncio
async def test_sessions_crud_and_auto_creation(app_client: AsyncClient):
    # Criar projeto
    resp = await app_client.post(
        "/api/projects",
        json={
            "name": "App Iterativo",
            "repo_path": "/tmp/test",
            "description": "App",
            "purpose": "Teste",
            "solution_description": "Sol",
            "api_key": "k",
        },
    )
    assert resp.status_code == 200
    proj_id = resp.json()["id"]

    # Listar sessões -> deve auto-criar Sessão 1
    resp = await app_client.get(f"/api/projects/{proj_id}/sessions")
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) == 1
    assert sessions[0]["number"] == 1
    assert sessions[0]["title"] == "Sessão 1"
    s1_id = sessions[0]["id"]

    # Criar Sessão 2
    resp = await app_client.post(f"/api/projects/{proj_id}/sessions")
    assert resp.status_code == 200
    s2 = resp.json()
    assert s2["number"] == 2
    assert s2["title"] == "Sessão 2"
    s2_id = s2["id"]

    # Obter detalhes da Sessão 1
    resp = await app_client.get(f"/api/projects/{proj_id}/sessions/{s1_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == s1_id

    # Atualizar status da Sessão 1
    resp = await app_client.patch(
        f"/api/projects/{proj_id}/sessions/{s1_id}",
        json={"status": "IN_SPRINT", "title": "Sessão 1 - MVP"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "IN_SPRINT"
    assert resp.json()["title"] == "Sessão 1 - MVP"

    # Criar tarefa na Sessão 1
    resp = await app_client.post(
        f"/api/projects/{proj_id}/tasks",
        json={
            "title": "Configurar DB",
            "description": "Subir migrations",
            "session_id": s1_id,
        },
    )
    assert resp.status_code == 200
    t1_id = resp.json()["id"]

    # Listar tarefas da Sessão 1
    resp = await app_client.get(f"/api/projects/{proj_id}/sessions/{s1_id}/tasks")
    assert resp.status_code == 200
    s1_tasks = resp.json()
    assert len(s1_tasks) == 1
    assert s1_tasks[0]["id"] == t1_id

    # Listar tarefas da Sessão 2 (deve estar vazia)
    resp = await app_client.get(f"/api/projects/{proj_id}/sessions/{s2_id}/tasks")
    assert resp.status_code == 200
    assert len(resp.json()) == 0

    # Migrar tarefa 1 para a Sessão 2
    resp = await app_client.post(
        f"/api/projects/{proj_id}/sessions/{s2_id}/migrate-tasks",
        json={"task_ids": [t1_id]},
    )
    assert resp.status_code == 200
    migrated = resp.json()
    assert len(migrated) == 1
    assert migrated[0]["session_id"] == s2_id

    # Agora Sessão 2 tem a tarefa
    resp = await app_client.get(f"/api/projects/{proj_id}/sessions/{s2_id}/tasks")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
