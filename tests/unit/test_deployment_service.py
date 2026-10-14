"""Unit tests for DeploymentService."""

import pytest
from unittest.mock import AsyncMock
from painkiller.core.domain.models import (
    Project,
    Task,
    TaskStatus,
    DeploymentRecord,
    DeploymentStatus,
    EnvironmentType,
    IterationSession,
    SessionStatus,
)
from painkiller.engine.deployment_service import DeploymentNotFailedError, DeploymentService


@pytest.mark.asyncio
async def test_deployment_service_test_branch_resolution():
    mock_tracker = AsyncMock()
    mock_deployment = AsyncMock()

    project = Project(id="proj-1", name="App", repo_path="/tmp", default_branch="main")
    task = Task(id="task-10", project_id="proj-1", title="Feature X", description="Desc",
                status=TaskStatus.COMPLETED, assigned_branch="feature/task-10")

    mock_tracker.get_project.return_value = project
    mock_tracker.get_task.return_value = task
    mock_tracker.save_deployment.side_effect = lambda rec: rec

    returned_rec = DeploymentRecord(
        id="dep-1",
        project_id="proj-1",
        task_id="task-10",
        environment=EnvironmentType.TEST,
        branch="feature/task-10",
        status=DeploymentStatus.BUILDING,
        url="http://app-test.local",
    )
    mock_deployment.deploy_environment.return_value = returned_rec

    service = DeploymentService(tracker=mock_tracker, deployment=mock_deployment)
    result = await service.trigger_deploy(
        project_id="proj-1",
        environment=EnvironmentType.TEST,
        task_id="task-10",
    )

    assert result.branch == "feature/task-10"
    mock_deployment.deploy_environment.assert_called_once_with(
        project=project,
        environment=EnvironmentType.TEST,
        branch="feature/task-10",
        task_id="task-10",
        session_id=None,
    )
    mock_tracker.update_project_deployment_urls.assert_called_once_with("proj-1", test_url="http://app-test.local")


@pytest.mark.asyncio
async def test_test_deploy_without_task_skips_unpushed_branches():
    """A RUNNING task's branch was never pushed; the last COMPLETED one was."""
    mock_tracker = AsyncMock()
    mock_deployment = AsyncMock()

    project = Project(id="proj-1", name="App", repo_path="/tmp", default_branch="main")
    mock_tracker.get_project.return_value = project
    mock_tracker.list_tasks.return_value = [
        Task(id="t1", project_id="proj-1", title="A", description="d",
             status=TaskStatus.COMPLETED, assigned_branch="feature/t1"),
        Task(id="t2", project_id="proj-1", title="B", description="d",
             status=TaskStatus.RUNNING, assigned_branch="feature/t2"),
        Task(id="t3", project_id="proj-1", title="C", description="d"),
    ]
    mock_tracker.save_deployment.side_effect = lambda rec: rec
    mock_deployment.deploy_environment.return_value = DeploymentRecord(
        id="dep-3", project_id="proj-1", environment=EnvironmentType.TEST,
        branch="feature/t1", status=DeploymentStatus.BUILDING,
    )

    service = DeploymentService(tracker=mock_tracker, deployment=mock_deployment)
    await service.trigger_deploy(project_id="proj-1", environment=EnvironmentType.TEST)

    assert mock_deployment.deploy_environment.call_args.kwargs["branch"] == "feature/t1"
    assert mock_deployment.deploy_environment.call_args.kwargs["task_id"] == "t1"


@pytest.mark.asyncio
async def test_test_deploy_with_running_task_falls_back_to_last_completed():
    mock_tracker = AsyncMock()
    mock_deployment = AsyncMock()

    project = Project(id="proj-1", name="App", repo_path="/tmp", default_branch="main")
    running = Task(id="t2", project_id="proj-1", title="B", description="d",
                   status=TaskStatus.RUNNING, assigned_branch="feature/t2")
    mock_tracker.get_project.return_value = project
    mock_tracker.get_task.return_value = running
    mock_tracker.list_tasks.return_value = [
        Task(id="t1", project_id="proj-1", title="A", description="d",
             status=TaskStatus.COMPLETED, assigned_branch="feature/t1"),
        running,
    ]
    mock_tracker.save_deployment.side_effect = lambda rec: rec
    mock_deployment.deploy_environment.return_value = DeploymentRecord(
        id="dep-5", project_id="proj-1", environment=EnvironmentType.TEST,
        branch="feature/t1", status=DeploymentStatus.BUILDING,
    )

    service = DeploymentService(tracker=mock_tracker, deployment=mock_deployment)
    await service.trigger_deploy(project_id="proj-1", environment=EnvironmentType.TEST, task_id="t2")

    assert mock_deployment.deploy_environment.call_args.kwargs["branch"] == "feature/t1"
    assert mock_deployment.deploy_environment.call_args.kwargs["task_id"] == "t1"


@pytest.mark.asyncio
async def test_test_deploy_without_completed_task_uses_default_branch():
    mock_tracker = AsyncMock()
    mock_deployment = AsyncMock()

    project = Project(id="proj-1", name="App", repo_path="/tmp", default_branch="main")
    mock_tracker.get_project.return_value = project
    mock_tracker.list_tasks.return_value = [
        Task(id="t2", project_id="proj-1", title="B", description="d",
             status=TaskStatus.RUNNING, assigned_branch="feature/t2"),
    ]
    mock_tracker.save_deployment.side_effect = lambda rec: rec
    mock_deployment.deploy_environment.return_value = DeploymentRecord(
        id="dep-4", project_id="proj-1", environment=EnvironmentType.TEST,
        branch="main", status=DeploymentStatus.BUILDING,
    )

    service = DeploymentService(tracker=mock_tracker, deployment=mock_deployment)
    await service.trigger_deploy(project_id="proj-1", environment=EnvironmentType.TEST)

    assert mock_deployment.deploy_environment.call_args.kwargs["branch"] == "main"
    assert mock_deployment.deploy_environment.call_args.kwargs["task_id"] is None


@pytest.mark.asyncio
async def test_deployment_service_production_always_uses_main():
    mock_tracker = AsyncMock()
    mock_deployment = AsyncMock()

    project = Project(id="proj-1", name="App", repo_path="/tmp", default_branch="main")
    mock_tracker.get_project.return_value = project
    mock_tracker.save_deployment.side_effect = lambda rec: rec

    returned_rec = DeploymentRecord(
        id="dep-2",
        project_id="proj-1",
        environment=EnvironmentType.PRODUCTION,
        branch="main",
        status=DeploymentStatus.HEALTHY,
        url="http://app-prod.local",
    )
    mock_deployment.deploy_environment.return_value = returned_rec

    service = DeploymentService(tracker=mock_tracker, deployment=mock_deployment)
    result = await service.trigger_deploy(
        project_id="proj-1",
        environment=EnvironmentType.PRODUCTION,
        task_id="task-ignored",
    )

    assert result.branch == "main"
    mock_deployment.deploy_environment.assert_called_once_with(
        project=project,
        environment=EnvironmentType.PRODUCTION,
        branch="main",
        task_id="task-ignored",
        session_id=None,
    )
    mock_tracker.update_project_deployment_urls.assert_called_once_with("proj-1", production_url="http://app-prod.local")


@pytest.mark.asyncio
async def test_test_deploy_refuses_task_of_finalized_session():
    """Finalizing a session deleted its branches: its tasks cannot be tested anymore."""
    from painkiller.core.domain.models import IterationSession, SessionStatus
    from painkiller.engine.deployment_service import BranchUnavailableError

    mock_tracker = AsyncMock()
    mock_deployment = AsyncMock()
    mock_tracker.get_project.return_value = Project(id="proj-1", name="App", repo_path="/tmp")
    mock_tracker.get_task.return_value = Task(
        id="task-10", project_id="proj-1", title="X", description="", status=TaskStatus.COMPLETED,
        assigned_branch="feature/task-10", session_id="s1",
    )
    mock_tracker.get_session.return_value = IterationSession(
        id="s1", project_id="proj-1", number=1, title="Sessão 1", status=SessionStatus.COMPLETED
    )

    service = DeploymentService(tracker=mock_tracker, deployment=mock_deployment)
    with pytest.raises(BranchUnavailableError):
        await service.trigger_deploy(project_id="proj-1", environment=EnvironmentType.TEST, task_id="task-10")
    mock_deployment.deploy_environment.assert_not_called()


@pytest.mark.asyncio
async def test_deploy_pushes_branch_to_gitea_before_coolify():
    """A push that failed at task completion left Coolify with "Remote branch not found"."""
    from painkiller.engine.deployment_service import BranchPushError

    tracker = AsyncMock()
    deployment = AsyncMock()
    git = AsyncMock()
    project = Project(id="proj-1", name="App", repo_path="/repo", default_branch="main",
                      repo_url="http://gitea:3000/alice/app.git")
    tracker.get_project.return_value = project
    tracker.get_task.return_value = Task(id="t1", project_id="proj-1", title="A", description="d",
                                         status=TaskStatus.COMPLETED, assigned_branch="feature/t1")
    tracker.get_session.return_value = None
    tracker.save_deployment.side_effect = lambda rec: rec
    deployment.deploy_environment.return_value = DeploymentRecord(
        id="dep-1", project_id="proj-1", environment=EnvironmentType.TEST,
        branch="feature/t1", status=DeploymentStatus.BUILDING,
    )
    git.push.return_value = (0, "")
    service = DeploymentService(tracker=tracker, deployment=deployment, git=git)

    await service.trigger_deploy(project_id="proj-1", environment=EnvironmentType.TEST, task_id="t1")
    git.push.assert_awaited_once_with("/repo", "feature/t1")

    # Produção publica a branch padrão: sem o push, sairia um commit antigo.
    git.push.reset_mock()
    await service.trigger_deploy(project_id="proj-1", environment=EnvironmentType.PRODUCTION)
    git.push.assert_awaited_once_with("/repo", "main")

    # Push recusado: o Coolify nem é chamado.
    git.push.return_value = (1, "fatal: unable to access")
    deployment.deploy_environment.reset_mock()
    with pytest.raises(BranchPushError):
        await service.trigger_deploy(project_id="proj-1", environment=EnvironmentType.TEST, task_id="t1")
    deployment.deploy_environment.assert_not_called()


def _failed_record(**kw) -> DeploymentRecord:
    base = dict(
        id="dep-9",
        project_id="proj-1",
        environment=EnvironmentType.PRODUCTION,
        branch="main",
        status=DeploymentStatus.FAILED,
        logs="#24 ERROR: Files prefixed with + are reserved\n```oops```",
    )
    base.update(kw)
    return DeploymentRecord(**base)


def _fix_tracker(record: DeploymentRecord, sessions: list, tasks: list | None = None) -> AsyncMock:
    tracker = AsyncMock()
    tracker.get_deployment.return_value = record
    tracker.get_project.return_value = Project(id="proj-1", name="App", repo_path="/tmp")
    tracker.list_sessions.return_value = sessions
    tracker.list_tasks.return_value = tasks or []
    tracker.create_session.return_value = IterationSession(
        id="sess-new", project_id="proj-1", number=len(sessions) + 1, title="S"
    )
    tracker.create_task.side_effect = lambda **kw: Task(id="task-fix", **kw)
    return tracker


@pytest.mark.asyncio
async def test_fix_task_opens_a_session_when_all_are_closed():
    closed = IterationSession(id="sess-1", project_id="proj-1", number=1, title="S1",
                              status=SessionStatus.COMPLETED)
    tracker = _fix_tracker(_failed_record(), [closed])

    task = await DeploymentService(tracker=tracker, deployment=AsyncMock()).create_fix_task("dep-9")

    tracker.create_session.assert_awaited_once_with("proj-1")
    assert task.session_id == "sess-new"
    assert "Files prefixed with + are reserved" in task.description
    # O log não pode fechar o bloco de código da descrição.
    assert "```oops```" not in task.description
    assert "deploy-fix: dep-9" in task.description


@pytest.mark.asyncio
async def test_fix_task_reuses_open_session_and_pending_task():
    open_session = IterationSession(id="sess-2", project_id="proj-1", number=2, title="S2",
                                    status=SessionStatus.IN_SPRINT)
    existing = Task(id="task-old", project_id="proj-1", title="Fix", session_id="sess-2",
                    description="...\n\ndeploy-fix: dep-9", status=TaskStatus.FAILED)
    tracker = _fix_tracker(_failed_record(), [open_session], [existing])

    task = await DeploymentService(tracker=tracker, deployment=AsyncMock()).create_fix_task("dep-9")

    assert task.id == "task-old"
    tracker.create_session.assert_not_awaited()
    tracker.create_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_fix_task_refuses_a_deploy_that_did_not_fail():
    tracker = _fix_tracker(_failed_record(status=DeploymentStatus.HEALTHY), [])
    with pytest.raises(DeploymentNotFailedError):
        await DeploymentService(tracker=tracker, deployment=AsyncMock()).create_fix_task("dep-9")


@pytest.mark.asyncio
async def test_get_deployment_persists_changes_made_in_place():
    """O adapter do Coolify altera o registro recebido; mesmo assim o banco é atualizado."""
    record = _failed_record(status=DeploymentStatus.BUILDING, logs="start")
    tracker = AsyncMock()
    tracker.get_deployment.return_value = record
    tracker.save_deployment.side_effect = lambda rec: rec

    async def mutate(rec):
        rec.status = DeploymentStatus.FAILED
        rec.logs = "start\nERROR: build"
        return rec

    deployment = AsyncMock()
    deployment.get_deployment_status.side_effect = mutate

    result = await DeploymentService(tracker=tracker, deployment=deployment).get_deployment("dep-9")

    tracker.save_deployment.assert_awaited_once()
    assert result.logs.endswith("ERROR: build")


@pytest.mark.asyncio
async def test_get_deployment_rereads_logs_right_after_it_ended():
    """O Coolify grava o fim do log depois do status final: relê por um tempo."""
    from datetime import datetime, timedelta, timezone

    fresh = _failed_record(logs="partial")
    old = _failed_record(logs="partial", updated_at=datetime.now(timezone.utc) - timedelta(hours=1))
    for record, expected_calls in ((fresh, 1), (old, 0)):
        tracker = AsyncMock()
        tracker.get_deployment.return_value = record
        deployment = AsyncMock()
        deployment.get_deployment_status.side_effect = lambda rec: rec
        await DeploymentService(tracker=tracker, deployment=deployment).get_deployment("dep-9")
        assert deployment.get_deployment_status.await_count == expected_calls
