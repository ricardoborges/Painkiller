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
    IterationSession,
    SessionStatus,
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
    # A branch da tarefa é publicada antes do merge (o "Testar" da sessão atual usa ela)
    assert [c.args for c in mock_git.push.call_args_list] == [("/repo", "feature/t1"), ("/repo", "main")]
    mock_tracker.update_task_status.assert_called_with("t1", TaskStatus.COMPLETED)


@pytest.mark.asyncio
async def test_finalize_session_deletes_only_merged_branches(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo", default_branch="main")
    session = IterationSession(id="s1", project_id="p1", number=1, title="Sessão 1", status=SessionStatus.IN_SPRINT)
    done = Task(id="t1", project_id="p1", title="A", description="", status=TaskStatus.COMPLETED,
                assigned_branch="feature/t1", session_id="s1")
    failed = Task(id="t2", project_id="p1", title="B", description="", status=TaskStatus.FAILED,
                  assigned_branch="feature/t2", session_id="s1")
    mock_tracker.get_session.return_value = session
    mock_tracker.get_project.return_value = project
    mock_tracker.list_tasks.return_value = [done, failed]
    mock_git.delete_branch.return_value = (0, "")

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    deleted = await orchestrator.finalize_session("s1")

    # A tarefa que falhou mantém a branch: pode migrar para a próxima sessão
    assert deleted == ["feature/t1"]
    mock_git.delete_branch.assert_awaited_once_with("/repo", "feature/t1", merged_into="main")
    saved = mock_tracker.update_session.await_args.args[0]
    assert saved.status == SessionStatus.COMPLETED




@pytest.mark.asyncio
async def test_dispatch_task_timeout_keeps_error_short(mock_tracker, mock_sandbox, mock_git, monkeypatch):
    monkeypatch.setenv("PAINKILLER_TASK_TIMEOUT", "900")
    project = Project(id="p1", name="App", repo_path="/repo")
    task = Task(id="t1", project_id="p1", title="Build Feature", description="Desc")

    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    huge_log = '{"type":"assistant"}\n' * 20_000
    mock_sandbox.run_task.return_value = ExecutionResult(
        exit_code=137, logs=huge_log, timed_out=True, summary="Rodando os testes de novo."
    )

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    await orchestrator.dispatch_task("t1")

    assert mock_sandbox.run_task.call_args.kwargs["timeout_seconds"] == 900
    failed = [c for c in mock_tracker.update_task_status.call_args_list if c.args[1] == TaskStatus.FAILED]
    error = failed[0].kwargs["error"]
    assert "tempo limite de 15 min" in error
    assert "Rodando os testes de novo." in error
    assert len(error) < 1000
    comment = mock_tracker.add_comment.call_args.kwargs["comment"]
    assert len(comment) < len(huge_log)


@pytest.mark.asyncio
async def test_retry_after_failure_tells_agent_to_continue(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo")
    task = Task(id="t1", project_id="p1", title="Build Feature", description="Desc", status=TaskStatus.FAILED)

    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="ok")

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    await orchestrator.dispatch_task("t1")

    assert "Execução anterior interrompida" in mock_sandbox.run_task.call_args.args[2]


@pytest.mark.asyncio
async def test_stop_orphaned_running_task_marks_it_failed(mock_tracker, mock_sandbox, mock_git):
    # Após um restart da API a tarefa segue RUNNING sem ninguém executando-a aqui.
    task = Task(
        id="t1", project_id="p1", title="T", description="D",
        status=TaskStatus.RUNNING, assigned_branch="feature/t1",
    )
    mock_tracker.get_task.return_value = task

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    await orchestrator.stop_task("t1")

    mock_sandbox.stop_task.assert_awaited_once_with("t1")
    call = mock_tracker.update_task_status.call_args
    assert call.args == ("t1", TaskStatus.FAILED)
    assert "interrompida pelo usuário" in call.kwargs["error"]


@pytest.mark.asyncio
async def test_stop_ignores_task_that_is_not_running(mock_tracker, mock_sandbox, mock_git):
    mock_tracker.get_task.return_value = Task(
        id="t1", project_id="p1", title="T", description="D", status=TaskStatus.COMPLETED
    )

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    await orchestrator.stop_task("t1")

    mock_tracker.update_task_status.assert_not_called()


@pytest.mark.asyncio
async def test_stop_during_dispatch_reports_interruption_not_exit_code(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo")
    task = Task(id="t1", project_id="p1", title="T", description="D")
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)

    async def run_and_get_stopped(*args, **kwargs):
        await orchestrator.stop_task("t1")
        return ExecutionResult(exit_code=137, logs="killed")

    mock_sandbox.run_task.side_effect = run_and_get_stopped
    await orchestrator.dispatch_task("t1")

    failed = [c for c in mock_tracker.update_task_status.call_args_list if c.args[1] == TaskStatus.FAILED]
    assert len(failed) == 1  # só o _dispatch registra; o stop não duplica
    assert "interrompida pelo usuário" in failed[0].kwargs["error"]
    assert "137" not in failed[0].kwargs["error"]


@pytest.mark.asyncio
async def test_abbreviate_tests_restarts_live_run_without_tests(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo")
    task = Task(id="t1", project_id="p1", title="T", description="D")
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project

    async def set_skip(task_id, skip):
        task.skip_tests = skip
        return task

    mock_tracker.set_task_skip_tests.side_effect = set_skip

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    runs = []

    async def run(*args, **kwargs):
        runs.append(args[2])
        if len(runs) == 1:
            assert await orchestrator.abbreviate_tests("t1") is True
            return ExecutionResult(exit_code=137, logs="killed")
        return ExecutionResult(exit_code=0, logs="ok")

    mock_sandbox.run_task.side_effect = run
    await orchestrator.dispatch_task("t1")

    assert len(runs) == 2
    assert "PRIORIDADE MÁXIMA" not in runs[0]
    # No topo: a spec e o plano que o agente lê depois não podem se sobrepor.
    assert runs[1].index("PRIORIDADE MÁXIMA") < runs[1].index("## Descrição")
    assert "prevalece sobre" in runs[1]
    assert "Execução anterior interrompida" in runs[1]
    mock_sandbox.stop_task.assert_awaited_once_with("t1")
    mock_git.run_tests.assert_not_called()
    statuses = [c.args[1] for c in mock_tracker.update_task_status.call_args_list]
    assert TaskStatus.FAILED not in statuses  # o reinício não registra falha
    assert statuses[-1] == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_abbreviate_tests_on_orphaned_task_frees_it_for_redispatch(mock_tracker, mock_sandbox, mock_git):
    task = Task(id="t1", project_id="p1", title="T", description="D", status=TaskStatus.RUNNING)
    mock_tracker.get_task.return_value = task

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    assert await orchestrator.abbreviate_tests("t1") is False

    mock_tracker.set_task_skip_tests.assert_awaited_once_with("t1", True)
    assert mock_tracker.update_task_status.call_args.args == ("t1", TaskStatus.FAILED)


@pytest.mark.asyncio
async def test_abbreviate_tests_refuses_completed_task(mock_tracker, mock_sandbox, mock_git):
    mock_tracker.get_task.return_value = Task(
        id="t1", project_id="p1", title="T", description="D", status=TaskStatus.COMPLETED
    )
    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)

    with pytest.raises(RuntimeError):
        await orchestrator.abbreviate_tests("t1")
    mock_tracker.set_task_skip_tests.assert_not_called()
