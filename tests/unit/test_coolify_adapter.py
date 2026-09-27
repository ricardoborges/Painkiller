"""Unit tests for CoolifyAdapter: HTTP is intercepted with httpx.MockTransport."""

import json

import httpx
import pytest

from painkiller.adapters.deploy.coolify_adapter import CoolifyAdapter, slugify
from painkiller.core.domain.models import DeploymentInfo, DeploymentStatus, Project


def _adapter(handler, **overrides) -> CoolifyAdapter:
    params = dict(
        base_url="https://coolify.example",
        token="tok",
        project_uuid="proj-uuid",
        server_uuid="srv-uuid",
        gitea_external_url="http://localhost:3000",
    )
    params.update(overrides)
    return CoolifyAdapter(transport=httpx.MockTransport(handler), **params)


def _project(**overrides) -> Project:
    params = dict(
        id="proj-1",
        name="Loja da Maria",
        repo_path="/repo",
        repo_url="http://localhost:3000/painkiller/loja-da-maria",
    )
    params.update(overrides)
    return Project(**params)


def test_slugify():
    assert slugify("Loja da Maria!") == "loja-da-maria"
    assert slugify("   ") == "app"


def test_is_configured_lists_missing_settings():
    adapter = CoolifyAdapter(base_url="", token="", project_uuid="x", server_uuid="")
    assert not adapter.is_configured()
    assert adapter.missing_settings() == ["COOLIFY_URL", "COOLIFY_TOKEN", "COOLIFY_SERVER_UUID"]


def test_clone_url_rewrites_gitea_host_for_coolify():
    adapter = _adapter(lambda r: httpx.Response(200), git_base_url="http://192.168.0.10:3000")
    assert adapter.clone_url_for(_project()) == "http://192.168.0.10:3000/painkiller/loja-da-maria.git"

    plain = _adapter(lambda r: httpx.Response(200))
    assert plain.clone_url_for(_project()) == "http://localhost:3000/painkiller/loja-da-maria.git"


def test_clone_url_requires_remote_repo():
    adapter = _adapter(lambda r: httpx.Response(200))
    with pytest.raises(RuntimeError):
        adapter.clone_url_for(_project(repo_url=None))


@pytest.mark.asyncio
async def test_ensure_application_creates_and_reads_fqdn():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok"
        if request.method == "POST" and request.url.path == "/api/v1/applications/public":
            seen["payload"] = json.loads(request.content)
            return httpx.Response(201, json={"uuid": "app-123"})
        if request.method == "GET" and request.url.path == "/api/v1/applications/app-123":
            return httpx.Response(200, json={"uuid": "app-123", "fqdn": "https://loja.example,https://other"})
        return httpx.Response(404)

    adapter = _adapter(handler, domain_template="https://{slug}.apps.example")
    project = _project(deployment=DeploymentInfo(port=8080, build_pack="dockerfile", dockerfile_location="/Dockerfile"))
    info = await adapter.ensure_application(project)

    assert info.app_uuid == "app-123"
    assert info.url == "https://loja.example"
    assert info.status == DeploymentStatus.CREATED
    payload = seen["payload"]
    assert payload["git_repository"] == "http://localhost:3000/painkiller/loja-da-maria.git"
    assert payload["git_branch"] == "main"
    assert payload["build_pack"] == "dockerfile"
    assert payload["ports_exposes"] == "8080"
    assert payload["dockerfile_location"] == "/Dockerfile"
    assert payload["domains"] == "https://loja-da-maria.apps.example"
    assert payload["environment_name"] == "production"
    assert payload["instant_deploy"] is False


@pytest.mark.asyncio
async def test_ensure_application_is_idempotent():
    calls = []
    adapter = _adapter(lambda r: calls.append(r) or httpx.Response(500))
    existing = DeploymentInfo(app_uuid="app-1", status=DeploymentStatus.LIVE)
    info = await adapter.ensure_application(_project(deployment=existing))
    assert info is existing
    assert calls == []


@pytest.mark.asyncio
async def test_deploy_falls_back_to_get_and_records_deployment_uuid():
    methods = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/deploy":
            methods.append(request.method)
            assert request.url.params["uuid"] == "app-1"
            if request.method == "POST":
                return httpx.Response(405)
            return httpx.Response(200, json={"deployments": [{"deployment_uuid": "dep-9", "resource_uuid": "app-1"}]})
        if request.url.path == "/api/v1/applications/app-1":
            return httpx.Response(200, json={"fqdn": "https://loja.example"})
        return httpx.Response(404)

    adapter = _adapter(handler)
    info = await adapter.deploy(_project(deployment=DeploymentInfo(app_uuid="app-1")))
    assert methods == ["POST", "GET"]
    assert info.last_deployment_uuid == "dep-9"
    assert info.status == DeploymentStatus.DEPLOYING
    assert info.url == "https://loja.example"


@pytest.mark.asyncio
async def test_deploy_requires_application():
    adapter = _adapter(lambda r: httpx.Response(200))
    with pytest.raises(RuntimeError):
        await adapter.deploy(_project())


@pytest.mark.asyncio
async def test_unauthorized_is_reported_in_portuguese():
    adapter = _adapter(lambda r: httpx.Response(401, json={"message": "Unauthenticated."}))
    with pytest.raises(RuntimeError) as exc:
        await adapter.ensure_application(_project())
    assert "COOLIFY_TOKEN" in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remote_status, expected",
    [
        ("in_progress", DeploymentStatus.DEPLOYING),
        ("queued", DeploymentStatus.DEPLOYING),
        ("finished", DeploymentStatus.LIVE),
        ("failed", DeploymentStatus.FAILED),
    ],
)
async def test_refresh_status_maps_deployment_status(remote_status, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/deployments/dep-1":
            return httpx.Response(200, json={"status": remote_status})
        if request.url.path == "/api/v1/applications/app-1":
            return httpx.Response(200, json={"fqdn": "https://loja.example"})
        return httpx.Response(404)

    adapter = _adapter(handler)
    current = DeploymentInfo(app_uuid="app-1", last_deployment_uuid="dep-1", status=DeploymentStatus.DEPLOYING)
    info = await adapter.refresh_status(_project(deployment=current))
    assert info.status == expected
    assert info.url == "https://loja.example"


@pytest.mark.asyncio
async def test_not_configured_fails_before_any_request():
    adapter = CoolifyAdapter(base_url="", token="", project_uuid="", server_uuid="",
                             transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(RuntimeError) as exc:
        await adapter.ensure_application(_project())
    assert "COOLIFY_URL" in str(exc.value)
