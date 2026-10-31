"""The app's optional backend: scaffold under backend/, route and backlog import."""

import os
import subprocess
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from painkiller.adapters.git.git_adapter import GitCliAdapter
from painkiller.api.server import create_app
from painkiller.core.backend import (
    BACKEND_DIR,
    BackendError,
    BackendExistsError,
    add_backend,
    has_backend,
)
from painkiller.core.domain.models import Project, Task, TaskStatus
from painkiller.core.templates import CAPACITOR_TEMPLATE_ID, LEGACY_TEMPLATE_ID
from tests.auth_helpers import admin_headers


def _project(repo_path, template_id=CAPACITOR_TEMPLATE_ID) -> Project:
    return Project(
        id="proj-1",
        name="App",
        repo_path=str(repo_path),
        description="",
        purpose="",
        solution_description="",
        template_id=template_id,
    )


def _tracker(tasks=()) -> AsyncMock:
    tracker = AsyncMock()
    tracker.list_tasks.return_value = list(tasks)
    return tracker


async def _repo(tmp_path) -> GitCliAdapter:
    git = GitCliAdapter()
    await git.init_repo(str(tmp_path), default_branch="main", initial_commit=True)
    return git


def _git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout.strip()


async def test_add_backend_commits_the_scaffold_on_the_default_branch(tmp_path):
    git = await _repo(tmp_path)
    await git.create_branch(str(tmp_path), "feature/x", base_branch="main")

    sha = await add_backend(git, _tracker(), _project(tmp_path))

    assert sha and has_backend(str(tmp_path))
    assert _git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    files = _git(tmp_path, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert "backend/Dockerfile" in files and "backend/app/main.py" in files
    # Só backend/ entra no commit.
    assert all(f.startswith(f"{BACKEND_DIR}/") for f in files)
    assert not any("__pycache__" in f for f in files)


async def test_add_backend_refuses_an_existing_folder(tmp_path):
    git = await _repo(tmp_path)
    os.makedirs(tmp_path / "backend")
    (tmp_path / "backend" / "server.js").write_text("x")

    with pytest.raises(BackendExistsError):
        await add_backend(git, _tracker(), _project(tmp_path))


async def test_add_backend_refuses_while_a_task_runs(tmp_path):
    git = await _repo(tmp_path)
    running = Task(id="t1", project_id="proj-1", title="t", description="", status=TaskStatus.RUNNING)

    with pytest.raises(BackendError, match="em execução"):
        await add_backend(git, _tracker([running]), _project(tmp_path))
    assert not has_backend(str(tmp_path))


async def test_add_backend_refuses_a_native_project(tmp_path):
    git = await _repo(tmp_path)
    with pytest.raises(BackendError, match="Capacitor"):
        await add_backend(git, _tracker(), _project(tmp_path, template_id=LEGACY_TEMPLATE_ID))


# ---- rota ---------------------------------------------------------------------


@pytest.fixture
async def client(tmp_path):
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with app.router.lifespan_context(app):
        app.state.vcs = None
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_backend_route_adds_it_once(client, tmp_path):
    headers = admin_headers()
    repo = tmp_path / "repo"
    res = await client.post(
        "/api/projects",
        json={"name": "Com backend", "api_key": "AIzaSyTest1234", "repo_path": str(repo)},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    project = res.json()
    assert project["has_backend"] is False

    added = await client.post(f"/api/projects/{project['id']}/backend", headers=headers)
    assert added.status_code == 200, added.text
    assert added.json()["has_backend"] is True
    assert (repo / "backend" / "Dockerfile").exists()

    again = await client.post(
        f"/api/projects/{project['id']}/backend", headers={**headers, "Accept-Language": "en-US"}
    )
    assert again.status_code == 409
    assert again.json()["detail"] == "The project already has a backend/ folder."


# ---- importação do backlog ------------------------------------------------------


async def _imported(tmp_path, monkeypatch, backlog: dict) -> AsyncMock:
    import asyncio
    import json

    from painkiller.core.domain.models import AgentEvent, AgentEventType
    from painkiller.engine import analysis
    from tests.unit.test_analysis_orchestrator import FakeAgentSession

    calls = AsyncMock()
    monkeypatch.setattr(analysis, "add_backend", calls)
    tracker = AsyncMock()
    tracker.create_task.side_effect = lambda **kw: Task(id=f"task-{kw['title']}", **kw)
    tracker.update_task_status.side_effect = lambda tid, status: Task(
        id=tid, project_id="proj-1", title="t", description="", status=status
    )
    tracker.get_project.return_value = _project(tmp_path)
    agent = FakeAgentSession([AgentEvent(type=AgentEventType.EXIT, text="0", raw={"exit_code": 0})])
    engine = analysis.AnalysisOrchestrator(agent=agent, tracker=tracker, git=AsyncMock())
    session = await engine.start(_project(tmp_path))
    await asyncio.wait_for(agent.release.wait(), timeout=5)
    path = tmp_path.joinpath(*analysis.backlog_relative(session.id).split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(backlog), encoding="utf-8")
    await engine.commit_backlog(session.id)
    return calls


async def test_backlog_asking_for_a_backend_scaffolds_it(tmp_path, monkeypatch):
    calls = await _imported(tmp_path, monkeypatch, {"backend": True, "tasks": [{"title": "API"}]})
    calls.assert_awaited_once()


async def test_backlog_without_the_flag_leaves_the_repo_alone(tmp_path, monkeypatch):
    calls = await _imported(tmp_path, monkeypatch, {"tasks": [{"title": "Tela"}]})
    calls.assert_not_awaited()


# ---- prompt da tarefa -------------------------------------------------------------


def test_task_prompt_describes_the_backend_only_when_it_exists(tmp_path):
    from painkiller.engine.orchestrator import PainkillerOrchestrator

    orchestrator = PainkillerOrchestrator(tracker=AsyncMock(), sandbox=AsyncMock(), git=AsyncMock())
    task = Task(id="t1", project_id="proj-1", title="Login", description="d")
    project = _project(tmp_path)

    assert "## Backend" not in orchestrator._build_task_instructions(task, project)

    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "Dockerfile").write_text("FROM python:3.13-slim\n")
    instructions = orchestrator._build_task_instructions(task, project)
    assert "## Backend (pasta backend/" in instructions
    assert "backend/.env.example" in instructions


# ---- deploy no Coolify -------------------------------------------------------------


def _repo_with_backend(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "Dockerfile").write_text("FROM python:3.13-slim\n")
    return tmp_path


def _coolify():
    from painkiller.adapters.deployment.coolify_adapter import CoolifyAdapter

    return CoolifyAdapter(
        api_url="http://coolify.test", api_token="t", server_uuid="srv-1", wildcard_domain="coolify.local"
    )


async def test_backend_deploy_creates_its_own_dockerfile_app(tmp_path):
    from unittest.mock import MagicMock, patch

    from painkiller.core.domain.models import DeploymentComponent, EnvironmentType

    project = _project(_repo_with_backend(tmp_path))
    gets = [
        MagicMock(is_success=True, json=lambda: [{"name": "painkiller-proj-1", "uuid": "p-uuid"}]),
        MagicMock(is_success=True, json=lambda: [{"name": "test"}]),
        # O app web já existe: o backend não pode reaproveitá-lo.
        MagicMock(is_success=True, json=lambda: [{"name": "app-test", "uuid": "web-uuid", "fqdn": "http://app-test.coolify.local"}]),
        # Aplicação nova: ainda sem volume.
        MagicMock(is_success=True, json=lambda: {"persistent_storages": [], "file_storages": []}),
    ]
    posts = [
        MagicMock(is_success=True, json=lambda: {"uuid": "api-uuid"}),
        MagicMock(is_success=True, json=lambda: {"uuid": "storage-1"}),
        MagicMock(is_success=True, json=lambda: {"deployment_uuid": "d-1"}),
    ]
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as get, \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        get.side_effect = gets
        post.side_effect = posts
        record = await _coolify().deploy_environment(
            project=project, environment=EnvironmentType.TEST, branch="main",
            component=DeploymentComponent.BACKEND,
        )

    payload = post.call_args_list[0].kwargs["json"]
    assert payload["name"].endswith("-api-test")
    assert payload["build_pack"] == "dockerfile"
    assert payload["base_directory"] == "/backend"
    assert payload["ports_exposes"] == "8000"
    storage = post.call_args_list[1]
    assert storage.args[0].endswith("/applications/api-uuid/storages")
    assert storage.kwargs["json"]["type"] == "persistent"
    assert storage.kwargs["json"]["mount_path"] == "/data"
    assert storage.kwargs["json"]["name"].endswith("-api-test-data")
    assert record.component == DeploymentComponent.BACKEND
    assert record.coolify_app_uuid == "api-uuid"
    assert record.url.endswith("-api-test.coolify.local")


async def test_backend_deploy_is_refused_without_backend(tmp_path):
    from painkiller.core.domain.models import DeploymentComponent, EnvironmentType
    from painkiller.engine.deployment_service import BackendMissingError, DeploymentService

    tracker = AsyncMock()
    tracker.get_project.return_value = _project(tmp_path)
    service = DeploymentService(tracker=tracker, deployment=AsyncMock())

    with pytest.raises(BackendMissingError):
        await service.trigger_deploy("proj-1", EnvironmentType.TEST, component=DeploymentComponent.BACKEND)


async def test_backend_deploy_keeps_the_app_urls_and_shows_in_the_status(tmp_path):
    from painkiller.core.domain.models import (
        DeploymentComponent,
        DeploymentRecord,
        DeploymentStatus,
        EnvironmentType,
    )
    from painkiller.engine.deployment_service import DeploymentService

    tracker = AsyncMock()
    tracker.get_project.return_value = _project(_repo_with_backend(tmp_path))
    tracker.list_tasks.return_value = []
    record = DeploymentRecord(
        id="dep-1", project_id="proj-1", environment=EnvironmentType.PRODUCTION,
        component=DeploymentComponent.BACKEND, status=DeploymentStatus.HEALTHY,
        url="http://app-api-production.coolify.local",
    )
    deployment = AsyncMock()
    deployment.deploy_environment.return_value = record
    tracker.save_deployment.side_effect = lambda r: r
    service = DeploymentService(tracker=tracker, deployment=deployment)

    await service.trigger_deploy("proj-1", EnvironmentType.PRODUCTION, component=DeploymentComponent.BACKEND)

    assert deployment.deploy_environment.call_args.kwargs["component"] == DeploymentComponent.BACKEND
    tracker.update_project_deployment_urls.assert_not_called()

    tracker.get_latest_deployment.side_effect = lambda pid, env, component=DeploymentComponent.APP: (
        record if component == DeploymentComponent.BACKEND and env == EnvironmentType.PRODUCTION else None
    )
    status = await service.get_project_environment_status("proj-1")
    assert status["production"]["url"] is None
    assert status["backend"]["production"]["url"] == "http://app-api-production.coolify.local"
    assert status["backend"]["test"]["status"] is None


async def test_latest_deployment_is_per_component(tmp_path):
    from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker
    from painkiller.core.domain.models import DeploymentComponent, DeploymentRecord, EnvironmentType

    tracker = SQLiteIssueTracker(db_url=f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    await tracker.init_db()
    try:
        await tracker.save_deployment(DeploymentRecord(id="a", project_id="p", environment=EnvironmentType.TEST))
        await tracker.save_deployment(DeploymentRecord(
            id="b", project_id="p", environment=EnvironmentType.TEST, component=DeploymentComponent.BACKEND,
        ))
        app = await tracker.get_latest_deployment("p", EnvironmentType.TEST)
        backend = await tracker.get_latest_deployment("p", EnvironmentType.TEST, DeploymentComponent.BACKEND)
        assert (app.id, app.component) == ("a", DeploymentComponent.APP)
        assert (backend.id, backend.component) == ("b", DeploymentComponent.BACKEND)
    finally:
        await tracker.close()


# ---- VITE_API_URL nos builds ----------------------------------------------------------


def test_https_wildcard_domain_gives_https_hosts(tmp_path):
    from painkiller.adapters.deployment.coolify_adapter import CoolifyAdapter, split_wildcard
    from painkiller.core.domain.models import DeploymentComponent, EnvironmentType

    assert split_wildcard("https://apps.example.com/") == ("https", "apps.example.com")
    assert split_wildcard("127.0.0.1.nip.io") == ("http", "127.0.0.1.nip.io")

    adapter = CoolifyAdapter(wildcard_domain="https://apps.example.com")
    url = adapter.environment_url(_project(tmp_path), EnvironmentType.PRODUCTION, DeploymentComponent.BACKEND)
    assert url.startswith("https://") and url.endswith("-api-production.apps.example.com")
    adapter.configure(wildcard_domain="10.0.0.5.nip.io")
    assert adapter.environment_url(_project(tmp_path), EnvironmentType.TEST).startswith("http://")


def test_backend_build_env_only_with_a_backend(tmp_path):
    from painkiller.adapters.deployment.coolify_adapter import CoolifyAdapter
    from painkiller.core.backend import backend_build_env
    from painkiller.core.domain.models import EnvironmentType

    adapter = CoolifyAdapter(wildcard_domain="apps.local")
    assert backend_build_env(_project(tmp_path), adapter, EnvironmentType.TEST) == {}
    project = _project(_repo_with_backend(tmp_path))
    assert backend_build_env(project, None, EnvironmentType.TEST) == {}
    env = backend_build_env(project, adapter, EnvironmentType.TEST)
    assert env["VITE_API_URL"].endswith("-api-test.apps.local")


async def test_post_task_check_gets_the_test_backend_url(tmp_path):
    from painkiller.adapters.deployment.coolify_adapter import CoolifyAdapter
    from painkiller.core.domain.models import ExecutionResult
    from painkiller.engine.orchestrator import PainkillerOrchestrator

    project = _project(_repo_with_backend(tmp_path)).model_copy(update={"api_key": "k"})
    tracker = AsyncMock()
    tracker.get_task.return_value = Task(id="t1", project_id="proj-1", title="Login", description="d")
    tracker.get_project.return_value = project
    tracker.list_clarifications.return_value = []
    tracker.get_project_template.return_value = None
    sandbox = AsyncMock()
    sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="ok")
    sandbox.run_tests.return_value = (0, "ok")
    git = AsyncMock()
    git.merge_branch.return_value = (0, "ok")

    orchestrator = PainkillerOrchestrator(
        tracker=tracker, sandbox=sandbox, git=git, deployment=CoolifyAdapter(wildcard_domain="apps.local")
    )
    await orchestrator.dispatch_task("t1")

    env = sandbox.run_tests.call_args.kwargs["extra_env"]
    assert env["VITE_API_URL"].endswith("-api-test.apps.local")
    instructions = sandbox.run_task.call_args.args[2]
    assert "import.meta.env.VITE_API_URL" in instructions


# ---- prompt da análise ----------------------------------------------------------------


def test_analysis_prompt_teaches_when_to_propose_a_backend(tmp_path):
    from painkiller.engine.analysis import build_analysis_prompt

    prompt = build_analysis_prompt(_project(tmp_path))
    assert '"backend": true' in prompt
    assert "VITE_API_URL" in prompt
    # Sobra da edição generalista: um Dockerfile na raiz mudaria o que o Coolify publica.
    assert "Dockerfile na raiz ou" not in prompt
    assert "nem Dockerfile na raiz" in prompt

    _repo_with_backend(tmp_path)
    with_backend = build_analysis_prompt(_project(tmp_path))
    assert "já tem um backend em backend/" in with_backend
    assert "acrescente" not in with_backend.split("Backend:")[1].split("\n")[0]


def test_native_analysis_prompt_has_no_backend(tmp_path):
    from painkiller.engine.analysis import build_analysis_prompt

    prompt = build_analysis_prompt(_project(tmp_path, template_id=LEGACY_TEMPLATE_ID))
    assert '"backend": true' not in prompt


async def test_backend_deploy_fails_without_its_data_volume(tmp_path):
    from unittest.mock import MagicMock, patch

    from painkiller.core.domain.models import DeploymentComponent, DeploymentStatus, EnvironmentType

    project = _project(_repo_with_backend(tmp_path))
    gets = [
        MagicMock(is_success=True, json=lambda: [{"name": "painkiller-proj-1", "uuid": "p-uuid"}]),
        MagicMock(is_success=True, json=lambda: [{"name": "production"}]),
        MagicMock(is_success=True, json=lambda: []),
        MagicMock(is_success=True, json=lambda: {"persistent_storages": []}),
    ]
    posts = [
        MagicMock(is_success=True, json=lambda: {"uuid": "api-uuid"}),
        MagicMock(is_success=False, status_code=422, text="name taken"),
    ]
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as get, \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        get.side_effect = gets
        post.side_effect = posts
        record = await _coolify().deploy_environment(
            project=project, environment=EnvironmentType.PRODUCTION, branch="main",
            component=DeploymentComponent.BACKEND,
        )

    # Sem volume, o deploy apagaria os dados na próxima publicação: nem é disparado.
    assert post.call_count == 2
    assert record.status == DeploymentStatus.FAILED
    assert "volume de dados" in record.logs


def test_task_prompt_explains_where_backend_data_lives(tmp_path):
    from painkiller.engine.orchestrator import PainkillerOrchestrator

    _repo_with_backend(tmp_path)
    orchestrator = PainkillerOrchestrator(tracker=AsyncMock(), sandbox=AsyncMock(), git=AsyncMock())
    instructions = orchestrator._build_task_instructions(
        Task(id="t1", project_id="proj-1", title="Notas", description="d"), _project(tmp_path)
    )
    assert "backend/app/db.py" in instructions and "/data" in instructions
    assert "ALTER TABLE ... ADD COLUMN" in instructions
