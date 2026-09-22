"""Unit tests for Coolify deployment adapter."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from painkiller.adapters.deployment.coolify_adapter import CoolifyAdapter
from painkiller.core.domain.models import Project, EnvironmentType, DeploymentStatus


@pytest.mark.asyncio
async def test_coolify_mock_mode_when_token_empty():
    adapter = CoolifyAdapter(api_token="", wildcard_domain="painkiller.local")
    project = Project(
        id="proj-123",
        name="my-app",
        repo_path="/tmp/test",
        default_branch="main",
    )

    record = await adapter.deploy_environment(
        project=project,
        environment=EnvironmentType.TEST,
        branch="feature/task-1",
        task_id="task-1",
    )

    assert record.project_id == "proj-123"
    assert record.environment == EnvironmentType.TEST
    assert record.branch == "feature/task-1"
    assert record.status == DeploymentStatus.HEALTHY
    assert "my-app-test.painkiller.local" in (record.url or "")


@pytest.mark.asyncio
async def test_coolify_deploy_environment_creates_app_and_triggers_deploy():
    adapter = CoolifyAdapter(
        api_url="http://coolify.test",
        api_token="test-token",
        server_uuid="srv-1",
        wildcard_domain="coolify.local",
    )
    project = Project(
        id="proj-456",
        name="store-api",
        repo_path="/tmp/store",
        default_branch="main",
        repo_url="http://localhost:3300/user/store.git",
    )

    # Mocking httpx responses
    mock_get_projects = MagicMock(is_success=True, json=lambda: [{"name": "painkiller-store-api", "uuid": "proj-uuid-1"}])
    mock_get_envs = MagicMock(is_success=True, json=lambda: [{"name": "production"}])
    mock_get_servers = MagicMock(is_success=True, json=lambda: [{"uuid": "srv-1"}])
    mock_get_apps = MagicMock(is_success=True, json=lambda: [])
    mock_post_app = MagicMock(is_success=True, json=lambda: {"uuid": "app-uuid-99"})
    mock_post_deploy = MagicMock(is_success=True, json=lambda: {"deployment_uuid": "dep-uuid-88"})

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        
        mock_get.side_effect = [mock_get_projects, mock_get_envs, mock_get_apps]
        mock_post.side_effect = [mock_post_app, mock_post_deploy]

        record = await adapter.deploy_environment(
            project=project,
            environment=EnvironmentType.PRODUCTION,
            branch="main",
        )

        assert record.coolify_app_uuid == "app-uuid-99"
        assert record.coolify_deployment_uuid == "dep-uuid-88"
        assert record.status == DeploymentStatus.BUILDING
        assert record.url == "http://store-api-production.coolify.local"
