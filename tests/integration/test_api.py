"""Integration tests for FastAPI endpoints using AsyncClient."""

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
        # Initialize DB
        tracker: SQLiteIssueTracker = app.state.tracker
        await tracker.init_db()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=admin_headers()) as client:
            yield client
        await tracker.close()


@pytest.mark.asyncio
async def test_project_and_task_api(app_client: AsyncClient):
    # 1. Create project
    res = await app_client.post(
        "/api/projects",
        json={"name": "API Test Project", "repo_path": "/tmp/api_proj", "api_key": "k"},
    )
    assert res.status_code == 200
    proj_data = res.json()
    assert proj_data["name"] == "API Test Project"
    proj_id = proj_data["id"]

    # 2. Create task
    res_task = await app_client.post(
        f"/api/projects/{proj_id}/tasks",
        json={
            "title": "Initial Task",
            "description": "Write initial tests",
            "target_files": ["test.py"],
            "acceptance_criteria": ["must pass"],
        },
    )
    assert res_task.status_code == 200
    task_data = res_task.json()
    assert task_data["title"] == "Initial Task"

    # 3. List tasks
    res_list = await app_client.get(f"/api/projects/{proj_id}/tasks")
    assert res_list.status_code == 200
    assert len(res_list.json()) == 1


@pytest.mark.asyncio
async def test_dashboard_static_page(app_client: AsyncClient):
    res = await app_client.get("/")
    assert res.status_code == 200
    assert "Painkiller" in res.text
