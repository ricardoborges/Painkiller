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


@pytest.mark.asyncio
async def test_coolify_deploy_environment_with_composite_project_id():
    adapter = CoolifyAdapter(
        api_url="http://coolify.test",
        api_token="test-token",
        server_uuid="srv-1",
        wildcard_domain="coolify.local",
    )
    project = Project(
        id="proj-ricardo-store-api-a1b2c3",
        name="Store API",
        repo_path="/tmp/store",
        default_branch="main",
    )

    mock_get_projects = MagicMock(is_success=True, json=lambda: [{"name": "painkiller-proj-ricardo-store-api-a1b2c3", "uuid": "proj-uuid-10"}])
    mock_get_envs = MagicMock(is_success=True, json=lambda: [{"name": "test"}])
    mock_get_servers = MagicMock(is_success=True, json=lambda: [{"uuid": "srv-1"}])
    mock_get_apps = MagicMock(is_success=True, json=lambda: [])
    mock_post_app = MagicMock(is_success=True, json=lambda: {"uuid": "app-uuid-55"})
    mock_post_deploy = MagicMock(is_success=True, json=lambda: {"deployment_uuid": "dep-uuid-44"})

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:

        mock_get.side_effect = [mock_get_projects, mock_get_envs, mock_get_apps]
        mock_post.side_effect = [mock_post_app, mock_post_deploy]

        record = await adapter.deploy_environment(
            project=project,
            environment=EnvironmentType.TEST,
            branch="feature/x",
        )

        assert record.coolify_app_uuid == "app-uuid-55"
        assert record.url == "http://ricardo-store-api-a1b2c3-test.coolify.local"
        # Check app creation payload passed to Coolify
        app_payload = mock_post.call_args_list[0].kwargs["json"]
        assert app_payload["name"] == "ricardo-store-api-a1b2c3-test"
        assert app_payload["domains"] == "http://ricardo-store-api-a1b2c3-test.coolify.local"



@pytest.mark.parametrize(
    "repo_url",
    [
        "http://localhost:8000/gitea/ricardoborges/jogo-de-damas",
        "http://localhost:3300/ricardoborges/jogo-de-damas.git",
        "http://127.0.0.1:3300/ricardoborges/jogo-de-damas",
    ],
)
def test_resolve_repo_url_rewrites_external_gitea_to_internal(repo_url):
    """Coolify rejects localhost repos, so the external Gitea address must become the internal one."""
    adapter = CoolifyAdapter(
        api_token="t",
        gitea_internal_url="http://gitea:3000",
        gitea_external_url="http://localhost:8000/gitea/",
    )
    project = Project(id="proj-1", name="damas", repo_path="/tmp/x", repo_url=repo_url)

    assert adapter._resolve_repo_url(project) == "http://gitea:3000/ricardoborges/jogo-de-damas.git"


def test_resolve_repo_url_keeps_external_hosts():
    adapter = CoolifyAdapter(api_token="t", gitea_internal_url="http://gitea:3000")
    project = Project(
        id="proj-1", name="x", repo_path="/tmp/x", repo_url="https://github.com/acme/app.git"
    )

    assert adapter._resolve_repo_url(project) == "https://github.com/acme/app.git"


@pytest.mark.asyncio
async def test_coolify_private_gitea_repo_uses_deploy_key():
    """Our Gitea forces private repos, so the app is created over SSH with a deploy key."""
    vcs = MagicMock()
    vcs.repo_from_url.return_value = ("ricardoborges", "damas")
    vcs.ssh_clone_url.return_value = "git@gitea:ricardoborges/damas.git"
    vcs.add_deploy_key = AsyncMock()
    adapter = CoolifyAdapter(
        api_url="http://coolify.test",
        api_token="test-token",
        server_uuid="srv-1",
        wildcard_domain="coolify.local",
        vcs=vcs,
    )
    project = Project(
        id="proj-456",
        name="damas",
        repo_path="/tmp/damas",
        default_branch="main",
        repo_url="http://localhost:8000/gitea/ricardoborges/damas",
    )

    responses_get = [
        MagicMock(is_success=True, json=lambda: [{"name": "painkiller-damas", "uuid": "proj-uuid-1"}]),
        MagicMock(is_success=True, json=lambda: [{"name": "test"}]),
        MagicMock(is_success=True, json=lambda: []),  # applications
        MagicMock(is_success=True, json=lambda: []),  # security/keys
    ]
    responses_post = [
        MagicMock(is_success=True, json=lambda: {"uuid": "key-uuid-1"}),
        MagicMock(is_success=True, json=lambda: {"uuid": "app-uuid-1"}),
        MagicMock(is_success=True, json=lambda: {"deployment_uuid": "dep-1"}),
    ]
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_get.side_effect = responses_get
        mock_post.side_effect = responses_post

        record = await adapter.deploy_environment(
            project=project, environment=EnvironmentType.TEST, branch="feature/t1"
        )

    assert record.status == DeploymentStatus.BUILDING
    owner, repo, title, public_key = vcs.add_deploy_key.await_args.args
    assert (owner, repo) == ("ricardoborges", "damas")
    assert public_key.startswith("ssh-ed25519 ")

    key_call, app_call, _ = mock_post.await_args_list
    assert key_call.args[0].endswith("/api/v1/security/keys")
    assert "OPENSSH PRIVATE KEY" in key_call.kwargs["json"]["private_key"]
    assert app_call.args[0].endswith("/api/v1/applications/private-deploy-key")
    assert app_call.kwargs["json"]["private_key_uuid"] == "key-uuid-1"
    assert app_call.kwargs["json"]["git_repository"] == "git@gitea:ricardoborges/damas.git"


@pytest.mark.asyncio
async def test_coolify_reuses_existing_deploy_key():
    vcs = MagicMock()
    vcs.add_deploy_key = AsyncMock()
    adapter = CoolifyAdapter(api_url="http://coolify.test", api_token="t", vcs=vcs)
    client = MagicMock()
    client.get = AsyncMock(
        return_value=MagicMock(is_success=True, json=lambda: [{"name": "painkiller-damas", "uuid": "k-9"}])
    )
    client.post = AsyncMock()

    uuid = await adapter._ensure_deploy_key(client, "ricardoborges", "damas", "damas")

    assert uuid == "k-9"
    vcs.add_deploy_key.assert_not_awaited()
    client.post.assert_not_awaited()
