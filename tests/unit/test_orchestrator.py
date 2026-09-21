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
    git.merge_branch.return_value = (0, "Fast-forward")
    return git


@pytest.mark.asyncio
async def test_dispatch_task_success(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo")
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
    mock_git.run_tests.assert_called_once()
    mock_git.merge_branch.assert_called_once_with("/repo", source_branch="feature/t1", target_branch="main")
    mock_tracker.update_task_status.assert_any_call("t1", TaskStatus.RUNNING, assigned_branch="feature/t1")
    mock_tracker.update_task_status.assert_any_call("t1", TaskStatus.COMPLETED)


@pytest.mark.asyncio
async def test_dispatch_task_treats_test_exit_code_5_as_success(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo")
    task = Task(id="t1", project_id="p1", title="Build HTML Page", description="Desc")

    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="Success")
    # Exit code 5 from pytest means 0 tests collected
    mock_git.run_tests.return_value = (5, "collected 0 items\nno tests ran")

    orchestrator = PainkillerOrchestrator(
        tracker=mock_tracker,
        sandbox=mock_sandbox,
        git=mock_git,
    )

    await orchestrator.dispatch_task("t1")

    mock_tracker.update_task_status.assert_any_call("t1", TaskStatus.COMPLETED)


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
    mock_tracker.update_task_status.assert_any_call("t1", TaskStatus.AWAITING_ANALYST, assigned_branch="feature/t1")


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


