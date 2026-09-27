"""Unit tests for the Painkiller orchestrator state machine."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from painkiller.core.domain.models import (
    Project,
    Task,
    TaskStatus,
    ClarificationRequest,
    ClarificationStatus,
    ExecutionResult,
)
from painkiller.engine.orchestrator import PainkillerOrchestrator


@pytest.fixture
def mock_tracker():
    tracker = AsyncMock()
    return tracker


@pytest.fixture
def mock_sandbox():
    sandbox = AsyncMock()
    return sandbox


@pytest.fixture
def mock_git():
    git = AsyncMock()
    git.run_tests.return_value = (0, "Tests passed")
    return git


@pytest.mark.asyncio
async def test_dispatch_task_success(mock_tracker, mock_sandbox, mock_git):
    # test_command explícito: sem ele o orquestrador detecta pelo repositório,
    # e /repo não existe neste teste.
    project = Project(id="p1", name="App", repo_path="/repo", test_command="pytest")
    task = Task(id="t1", project_id="p1", title="Build Feature", description="Desc")

    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="Success")

    orchestrator = PainkillerOrchestrator(
        tracker=mock_tracker,
        sandbox=mock_sandbox,
        git=mock_git,
    )

    await orchestrator.dispatch_task("t1")

    mock_git.create_branch.assert_called_once()
    mock_sandbox.run_task.assert_called_once()
    mock_git.run_tests.assert_called_once_with("/repo", "pytest")
    mock_tracker.update_task_status.assert_any_call("t1", TaskStatus.IN_REVIEW)


@pytest.mark.asyncio
async def test_dispatch_skips_verification_when_nothing_to_run(mock_tracker, mock_sandbox, mock_git, tmp_path):
    """Um repositório sem testes e sem comando configurado não pode falhar por isso."""
    project = Project(id="p1", name="App", repo_path=str(tmp_path))
    task = Task(id="t1", project_id="p1", title="Build Feature", description="Desc")
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_tracker.list_clarifications.return_value = []
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="Success")

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    await orchestrator.dispatch_task("t1")

    mock_git.run_tests.assert_not_called()
    mock_tracker.update_task_status.assert_any_call("t1", TaskStatus.IN_REVIEW)


@pytest.mark.asyncio
async def test_dispatch_treats_pytest_no_tests_as_pass(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo", test_command="pytest")
    task = Task(id="t1", project_id="p1", title="Build Feature", description="Desc")
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_tracker.list_clarifications.return_value = []
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="Success")
    mock_git.run_tests.return_value = (5, "no tests ran")

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    await orchestrator.dispatch_task("t1")

    mock_tracker.update_task_status.assert_any_call("t1", TaskStatus.IN_REVIEW)


@pytest.mark.asyncio
async def test_dispatch_fails_when_tests_fail(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo", test_command="npm test")
    task = Task(id="t1", project_id="p1", title="Build Feature", description="Desc")
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_tracker.list_clarifications.return_value = []
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="Success")
    mock_git.run_tests.return_value = (1, "2 failing")

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    await orchestrator.dispatch_task("t1")

    mock_tracker.update_task_status.assert_any_call("t1", TaskStatus.FAILED)
    mock_git.commit_wip.assert_not_called()


@pytest.mark.asyncio
async def test_answered_clarifications_reach_the_agent_prompt(mock_tracker, mock_sandbox, mock_git):
    """Sem isto o agente refaz a mesma pergunta a cada reexecução."""
    project = Project(id="p1", name="App", repo_path="/repo", test_command="pytest")
    task = Task(id="t1", project_id="p1", title="Build Feature", description="Desc")
    answered = ClarificationRequest(
        id="c1", task_id="t1", question="Which JWT library?", context_summary="auth.py",
        status=ClarificationStatus.ANSWERED, answer="PyJWT",
    )
    still_open = ClarificationRequest(id="c2", task_id="t1", question="Open?", context_summary="")
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_tracker.list_clarifications.return_value = [answered, still_open]
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="ok")

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    await orchestrator.dispatch_task("t1")

    instructions = mock_sandbox.run_task.call_args.args[2]
    assert "Which JWT library?" in instructions
    assert "PyJWT" in instructions
    assert "NÃO pergunte de novo" in instructions
    assert "Open?" not in instructions


@pytest.mark.asyncio
async def test_merge_redeploys_when_application_exists(mock_tracker, mock_sandbox, mock_git):
    from painkiller.core.domain.models import DeploymentInfo, DeploymentStatus

    info = DeploymentInfo(app_uuid="app-1", url="https://app.example", status=DeploymentStatus.LIVE)
    project = Project(id="p1", name="App", repo_path="/repo", repo_url="http://gitea/p/app", deployment=info)
    task = Task(id="t1", project_id="p1", title="Build Feature", description="Desc", assigned_branch="feature/t1")
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_tracker.update_project.return_value = project
    mock_git.merge_branch.return_value = (0, "ok")

    deployer = AsyncMock()
    deployer.is_configured = MagicMock(return_value=True)
    deployer.ensure_application.return_value = info
    deployer.deploy.return_value = info.model_copy(update={"status": DeploymentStatus.DEPLOYING})

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git, deployer=deployer)
    await orchestrator.merge_task("t1")

    deployer.deploy.assert_awaited_once()
    mock_tracker.update_task_status.assert_any_call("t1", TaskStatus.COMPLETED)


@pytest.mark.asyncio
async def test_publish_records_failure_and_reraises(mock_tracker, mock_sandbox, mock_git):
    from painkiller.core.domain.models import DeploymentStatus

    project = Project(id="p1", name="App", repo_path="/repo", repo_url="http://gitea/p/app")
    mock_tracker.get_project.return_value = project
    mock_tracker.update_project.return_value = project
    deployer = AsyncMock()
    deployer.is_configured = MagicMock(return_value=True)
    deployer.ensure_application.side_effect = RuntimeError("Coolify offline")

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git, deployer=deployer)
    with pytest.raises(RuntimeError):
        await orchestrator.publish_project("p1")

    saved = mock_tracker.update_project.call_args.kwargs["deployment"]
    assert saved.status == DeploymentStatus.FAILED
    assert "Coolify offline" in (saved.error or "")


@pytest.mark.asyncio
async def test_dispatch_task_pause_on_clarification(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo")
    task = Task(id="t1", project_id="p1", title="Build Feature", description="Desc")

    clar_req = ClarificationRequest(
        id="c1",
        task_id="t1",
        question="Which JWT library?",
        context_summary="auth.py",
    )

    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=42, logs="Paused", clarification=clar_req)

    orchestrator = PainkillerOrchestrator(
        tracker=mock_tracker,
        sandbox=mock_sandbox,
        git=mock_git,
    )

    await orchestrator.dispatch_task("t1")

    mock_tracker.create_clarification.assert_called_once_with("t1", "Which JWT library?", "auth.py")
    mock_tracker.update_task_status.assert_any_call("t1", TaskStatus.AWAITING_ANALYST)


@pytest.mark.asyncio
async def test_merge_task_success(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo", default_branch="main")
    task = Task(id="t1", project_id="p1", title="Build Feature", description="Desc", assigned_branch="feature/t1")

    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_git.merge_branch.return_value = (0, "Fast-forward")
    mock_git.push.return_value = (0, "Pushed")

    orchestrator = PainkillerOrchestrator(
        tracker=mock_tracker,
        sandbox=mock_sandbox,
        git=mock_git,
    )

    await orchestrator.merge_task("t1")

    mock_git.merge_branch.assert_called_once_with("/repo", source_branch="feature/t1", target_branch="main")
    mock_git.push.assert_called_once_with("/repo", "main")
    mock_tracker.update_task_status.assert_called_with("t1", TaskStatus.COMPLETED)

