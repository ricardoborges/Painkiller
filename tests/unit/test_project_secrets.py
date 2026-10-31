"""Project secrets: storage, rules, routes, and where the values go (and never go)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from painkiller.adapters.deployment.coolify_adapter import CoolifyAdapter
from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker
from painkiller.api.server import create_app
from painkiller.core.domain.models import (
    DeploymentComponent,
    DeploymentRecord,
    DeploymentStatus,
    EnvironmentType,
    ExecutionResult,
    Project,
    ProjectSecret,
    SecretScope,
    Task,
)
from painkiller.core.secrets import SecretNameError, check_secret, redact, secrets_block
from painkiller.engine.deployment_service import DeploymentService
from painkiller.engine.orchestrator import PainkillerOrchestrator
from tests.auth_helpers import admin_headers

APP_KEY = "AIzaMapsPublicKey123"
SERVER_KEY = "sk-openai-very-secret-987"


# ---- regras e redação --------------------------------------------------------------


def test_names_must_match_their_scope():
    assert check_secret(" VITE_MAPS_KEY ", SecretScope.APP) == "VITE_MAPS_KEY"
    assert check_secret("OPENAI_API_KEY", SecretScope.SERVER) == "OPENAI_API_KEY"
    for name, scope in (
        ("MAPS_KEY", SecretScope.APP),
        ("VITE_OPENAI", SecretScope.SERVER),
        ("openai_key", SecretScope.SERVER),
        ("VITE_API_URL", SecretScope.APP),
        ("1KEY", SecretScope.SERVER),
    ):
        with pytest.raises(SecretNameError):
            check_secret(name, scope)


def test_redact_hides_values_and_ignores_tiny_ones():
    log = f"token={SERVER_KEY} key={APP_KEY} n=abc"
    assert redact(log, [SERVER_KEY, APP_KEY, "abc"]) == "token=*** key=*** n=abc"
    assert redact(None, [SERVER_KEY]) is None


def test_secrets_block_lists_names_only():
    secrets = [
        ProjectSecret(name="VITE_MAPS_KEY", scope=SecretScope.APP),
        ProjectSecret(name="OPENAI_API_KEY", scope=SecretScope.SERVER),
    ]
    block = secrets_block(secrets, english=False)
    assert "import.meta.env.VITE_MAPS_KEY" in block
    assert 'os.environ["OPENAI_API_KEY"]' in block
    assert "painkiller ask" in block
    assert "painkiller ask" not in secrets_block(secrets, english=True, in_task=False)


# ---- armazenamento ---------------------------------------------------------------------


@pytest.fixture
async def tracker(tmp_path):
    t = SQLiteIssueTracker(db_url=f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    await t.init_db()
    yield t
    await t.close()


async def test_values_are_sealed_and_listed_without_values(tracker):
    await tracker.put_secret("p1", "OPENAI_API_KEY", SecretScope.SERVER, SERVER_KEY)
    await tracker.put_secret("p1", "VITE_MAPS_KEY", SecretScope.APP, APP_KEY)
    await tracker.put_secret("p2", "OTHER", SecretScope.SERVER, "x" * 10)

    async with tracker.engine.connect() as conn:
        raw = (await conn.execute(text("SELECT value FROM project_secrets"))).scalars().all()
    assert raw and all(v.startswith("enc:v1:") for v in raw)
    assert SERVER_KEY not in " ".join(raw)

    assert [s.name for s in await tracker.list_secrets("p1")] == ["OPENAI_API_KEY", "VITE_MAPS_KEY"]
    assert await tracker.get_secret_values("p1", SecretScope.APP) == {"VITE_MAPS_KEY": APP_KEY}
    assert await tracker.get_secret_values("p1") == {"OPENAI_API_KEY": SERVER_KEY, "VITE_MAPS_KEY": APP_KEY}

    await tracker.put_secret("p1", "OPENAI_API_KEY", SecretScope.SERVER, "sk-rotated-0001")
    assert (await tracker.get_secret_values("p1", SecretScope.SERVER))["OPENAI_API_KEY"] == "sk-rotated-0001"

    removed = await tracker.delete_secret("p1", "OPENAI_API_KEY")
    assert removed.scope == SecretScope.SERVER
    assert await tracker.delete_secret("p1", "OPENAI_API_KEY") is None


async def test_deleting_the_project_deletes_its_secrets(tracker):
    project = await tracker.create_project(name="App", repo_path="/tmp/x", api_key="k")
    await tracker.put_secret(project.id, "OPENAI_API_KEY", SecretScope.SERVER, SERVER_KEY)
    await tracker.delete_project(project.id)
    assert await tracker.list_secrets(project.id) == []


# ---- rotas ----------------------------------------------------------------------------


@pytest.fixture
async def client(tmp_path):
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with app.router.lifespan_context(app):
        project = await app.state.tracker.create_project(name="App", repo_path=str(tmp_path), api_key="k")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield app, c, project


async def test_routes_never_return_values(client):
    app, c, project = client
    base = f"/api/projects/{project.id}/secrets"
    res = await c.put(f"{base}/OPENAI_API_KEY", json={"scope": "server", "value": f" {SERVER_KEY}\n"}, headers=admin_headers())
    assert res.status_code == 200, res.text
    assert SERVER_KEY not in res.text

    listed = await c.get(base, headers=admin_headers())
    assert [s["name"] for s in listed.json()] == ["OPENAI_API_KEY"]
    assert SERVER_KEY not in listed.text
    # Espaços e a quebra de linha de copiar e colar não fazem parte da chave.
    assert await app.state.tracker.get_secret_values(project.id) == {"OPENAI_API_KEY": SERVER_KEY}


async def test_routes_validate_name_and_value(client):
    app, c, project = client
    base = f"/api/projects/{project.id}/secrets"
    bad = await c.put(f"{base}/MAPS", json={"scope": "app", "value": "x"}, headers={**admin_headers(), "Accept-Language": "en-US"})
    assert bad.status_code == 400
    assert bad.json()["detail"].startswith("App secrets start with VITE_")
    empty = await c.put(f"{base}/OPENAI_API_KEY", json={"scope": "server", "value": "  "}, headers=admin_headers())
    assert empty.status_code == 400
    missing = await c.delete(f"{base}/NOPE", headers=admin_headers())
    assert missing.status_code == 404


async def test_delete_also_removes_it_from_coolify(client):
    app, c, project = client
    app.state.deployment_service.deployment = AsyncMock()
    base = f"/api/projects/{project.id}/secrets"
    await c.put(f"{base}/OPENAI_API_KEY", json={"scope": "server", "value": SERVER_KEY}, headers=admin_headers())

    res = await c.delete(f"{base}/OPENAI_API_KEY", headers=admin_headers())

    assert res.status_code == 200
    calls = app.state.deployment_service.deployment.remove_env.call_args_list
    assert {(c.args[1], c.args[2], c.args[3]) for c in calls} == {
        (EnvironmentType.TEST, DeploymentComponent.BACKEND, "OPENAI_API_KEY"),
        (EnvironmentType.PRODUCTION, DeploymentComponent.BACKEND, "OPENAI_API_KEY"),
    }


# ---- para onde os valores vão --------------------------------------------------------------


def _secrets_tracker(project: Project) -> AsyncMock:
    tracker = AsyncMock()
    tracker.get_project.return_value = project

    async def values(project_id, scope=None):
        everything = {"VITE_MAPS_KEY": (SecretScope.APP, APP_KEY), "OPENAI_API_KEY": (SecretScope.SERVER, SERVER_KEY)}
        return {k: v for k, (s, v) in everything.items() if scope is None or s == scope}

    tracker.get_secret_values.side_effect = values
    tracker.list_secrets.return_value = [
        ProjectSecret(name="OPENAI_API_KEY", scope=SecretScope.SERVER),
        ProjectSecret(name="VITE_MAPS_KEY", scope=SecretScope.APP),
    ]
    return tracker


def _project(tmp_path) -> Project:
    return Project(id="p1", name="App", repo_path=str(tmp_path), api_key="k", template_id="capacitor-react")


async def test_task_sees_names_its_check_gets_app_values_and_failures_are_redacted(tmp_path):
    project = _project(tmp_path)
    tracker = _secrets_tracker(project)
    tracker.get_task.return_value = Task(id="t1", project_id="p1", title="Mapa", description="d")
    tracker.list_clarifications.return_value = []
    tracker.get_project_template.return_value = None
    sandbox = AsyncMock()
    sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="ok")
    sandbox.run_tests.return_value = (1, f"FAIL: env VITE_MAPS_KEY={APP_KEY}")

    await PainkillerOrchestrator(tracker=tracker, sandbox=sandbox, git=AsyncMock()).dispatch_task("t1")

    instructions = sandbox.run_task.call_args.args[2]
    assert "VITE_MAPS_KEY" in instructions and "OPENAI_API_KEY" in instructions
    assert APP_KEY not in instructions and SERVER_KEY not in instructions
    # O agente nunca recebe valores no ambiente.
    assert APP_KEY not in repr(sandbox.run_task.call_args) and SERVER_KEY not in repr(sandbox.run_task.call_args)

    assert sandbox.run_tests.call_args.kwargs["extra_env"] == {"VITE_MAPS_KEY": APP_KEY}
    stored = repr(tracker.update_task_status.call_args_list) + repr(tracker.add_comment.call_args_list)
    assert APP_KEY not in stored and "VITE_MAPS_KEY=***" in stored


async def test_backend_deploy_gets_server_values_and_the_app_gets_app_values(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "Dockerfile").write_text("FROM python\n")
    project = _project(tmp_path)
    tracker = _secrets_tracker(project)
    tracker.list_tasks.return_value = []
    tracker.save_deployment.side_effect = lambda r: r
    deployment = AsyncMock()
    deployment.environment_url = MagicMock(return_value="http://app-api-test.local")
    deployment.deploy_environment.return_value = DeploymentRecord(id="d", project_id="p1")
    service = DeploymentService(tracker=tracker, deployment=deployment)

    await service.trigger_deploy("p1", EnvironmentType.TEST, component=DeploymentComponent.BACKEND)
    assert deployment.deploy_environment.call_args.kwargs["env_vars"] == {"OPENAI_API_KEY": SERVER_KEY}

    await service.trigger_deploy("p1", EnvironmentType.TEST)
    assert deployment.deploy_environment.call_args.kwargs["env_vars"] == {
        "VITE_MAPS_KEY": APP_KEY,
        "VITE_API_URL": "http://app-api-test.local",
    }


async def test_deploy_logs_from_coolify_are_redacted(tmp_path):
    project = _project(tmp_path)
    tracker = _secrets_tracker(project)
    tracker.get_deployment.return_value = DeploymentRecord(
        id="d", project_id="p1", status=DeploymentStatus.BUILDING
    )
    tracker.save_deployment.side_effect = lambda r: r
    deployment = AsyncMock()

    async def status(record):
        record.status = DeploymentStatus.FAILED
        record.logs = f"ENV OPENAI_API_KEY={SERVER_KEY}"
        return record

    deployment.get_deployment_status.side_effect = status
    record = await DeploymentService(tracker=tracker, deployment=deployment).get_deployment("d")

    assert record.logs == "ENV OPENAI_API_KEY=***"


async def test_coolify_receives_the_variables_before_the_build(tmp_path):
    adapter = CoolifyAdapter(api_url="http://coolify.test", api_token="t", server_uuid="s", wildcard_domain="c.local")
    project = _project(tmp_path)
    gets = [
        MagicMock(is_success=True, json=lambda: [{"name": "painkiller-p1", "uuid": "pu"}]),
        MagicMock(is_success=True, json=lambda: [{"name": "test"}]),
        MagicMock(is_success=True, json=lambda: [{"name": "app-api-test", "uuid": "app-uuid"}]),
    ]
    patches = [MagicMock(is_success=True), MagicMock(is_success=False, status_code=422, text="bad")]
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as get, \
         patch("httpx.AsyncClient.patch", new_callable=AsyncMock) as patch_, \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        get.side_effect = gets
        patch_.side_effect = patches
        record = await adapter.deploy_environment(
            project=project, environment=EnvironmentType.TEST, branch="main",
            component=DeploymentComponent.BACKEND, env_vars={"OPENAI_API_KEY": SERVER_KEY},
        )

    envs_call = patch_.call_args_list[1]
    assert envs_call.args[0].endswith("/applications/app-uuid/envs/bulk")
    assert envs_call.kwargs["json"]["data"] == [
        {"key": "OPENAI_API_KEY", "value": SERVER_KEY, "is_preview": False, "is_literal": True}
    ]
    # Sem as variáveis o backend subiria quebrado: o deploy nem é disparado.
    post.assert_not_called()
    assert record.status == DeploymentStatus.FAILED
    assert SERVER_KEY not in record.logs
