"""Integration tests for Deployment API endpoints."""

import os
import tempfile
import pytest
from httpx import AsyncClient, ASGITransport
from painkiller.api.server import create_app
from tests.auth_helpers import admin_headers
from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker


@pytest.fixture
async def deployment_client(monkeypatch):
    monkeypatch.setenv("COOLIFY_API_TOKEN", "")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_deploy.db")
        app = create_app(db_url=f"sqlite+aiosqlite:///{db_path}")
        tracker: SQLiteIssueTracker = app.state.tracker
        await tracker.init_db()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=admin_headers()) as client:
            yield client
        await tracker.close()


@pytest.mark.asyncio
async def test_deployments_api_flow(deployment_client: AsyncClient):
    # 1. Create project
    proj_res = await deployment_client.post(
        "/api/projects",
        json={"name": "Deploy App", "repo_path": "/tmp/deploy_app", "api_key": "k"},
    )
    assert proj_res.status_code == 200
    proj_id = proj_res.json()["id"]

    # 2. Trigger test deploy
    deploy_res = await deployment_client.post(
        f"/api/projects/{proj_id}/deploy",
        json={"environment": "test"},
    )
    assert deploy_res.status_code == 200
    deploy_data = deploy_res.json()
    assert deploy_data["environment"] == "test"
    assert "deploy-app" in deploy_data["url"] and "-test" in deploy_data["url"]
    dep_id = deploy_data["id"]

    # 3. Get deployment details
    detail_res = await deployment_client.get(f"/api/deployments/{dep_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == dep_id

    # 4. Check project environment status
    status_res = await deployment_client.get(f"/api/projects/{proj_id}/deployments/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["test"]["url"] == deploy_data["url"]

    # 5. Trigger production deploy
    prod_res = await deployment_client.post(
        f"/api/projects/{proj_id}/deploy",
        json={"environment": "production"},
    )
    assert prod_res.status_code == 200
    prod_data = prod_res.json()
    assert prod_data["environment"] == "production"
    assert "deploy-app" in prod_data["url"] and "-production" in prod_data["url"]

    # 6. List deployments
    list_res = await deployment_client.get(f"/api/projects/{proj_id}/deployments")
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) == 2
