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


async def _project_with_session(client: AsyncClient) -> tuple[str, str]:
    resp = await client.post(
        "/api/projects",
        json={
            "name": "Manual",
            "repo_path": "/tmp/test-manual",
            "description": "App",
            "purpose": "Teste",
            "solution_description": "Sol",
            "api_key": "k",
        },
    )
    proj_id = resp.json()["id"]
    sessions = (await client.get(f"/api/projects/{proj_id}/sessions")).json()
    return proj_id, sessions[0]["id"]


@pytest.mark.asyncio
async def test_manual_task_moves_planning_session_to_backlog(app_client: AsyncClient):
    proj_id, s1_id = await _project_with_session(app_client)

    resp = await app_client.post(
        f"/api/projects/{proj_id}/tasks",
        json={
            "title": "  Página de contato  ",
            "session_id": s1_id,
            "acceptance_criteria": ["Formulário envia e-mail", "  ", ""],
        },
    )
    assert resp.status_code == 200
    task = resp.json()
    assert task["title"] == "Página de contato"
    assert task["description"] == ""
    assert task["acceptance_criteria"] == ["Formulário envia e-mail"]
    assert task["status"] == "BACKLOG"

    session = (await app_client.get(f"/api/projects/{proj_id}/sessions/{s1_id}")).json()
    assert session["status"] == "BACKLOG"


@pytest.mark.asyncio
async def test_manual_task_validation(app_client: AsyncClient):
    proj_id, s1_id = await _project_with_session(app_client)
    url = f"/api/projects/{proj_id}/tasks"

    assert (await app_client.post(url, json={"title": "   ", "session_id": s1_id})).status_code == 400
    assert (await app_client.post(url, json={"title": "X", "session_id": "nope"})).status_code == 404

    resp = await app_client.post(url, json={"title": "X", "session_id": s1_id, "dependencies": ["task-ghost"]})
    assert resp.status_code == 400

    first = (await app_client.post(url, json={"title": "A", "session_id": s1_id})).json()
    resp = await app_client.post(url, json={"title": "B", "session_id": s1_id, "dependencies": [first["id"]]})
    assert resp.status_code == 200
    assert resp.json()["dependencies"] == [first["id"]]

    # Sessão encerrada não recebe tarefas: as branches dela já foram apagadas.
    await app_client.post(f"/api/projects/{proj_id}/sessions")
    resp = await app_client.post(url, json={"title": "C", "session_id": s1_id})
    assert resp.status_code == 409
