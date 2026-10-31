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
    sandbox.run_tests.return_value = (0, "Tests passed")
    return sandbox


@pytest.fixture
def mock_git():
    git = AsyncMock()
    git.merge_branch.return_value = (0, "Fast-forward")
    return git


async def test_dispatch_refuses_project_without_api_key(mock_tracker, mock_sandbox, mock_git):
    mock_tracker.get_task.return_value = Task(id="t1", project_id="p1", title="T", description="D")
    mock_tracker.get_project.return_value = Project(id="p1", name="App", repo_path="/repo")
    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)

    with pytest.raises(RuntimeError, match="chave de API"):
        await orchestrator.dispatch_task("t1")

    mock_git.create_branch.assert_not_called()
    mock_sandbox.run_task.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_task_success(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo", api_key="k")
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
    mock_sandbox.run_tests.assert_called_once()
    mock_git.merge_branch.assert_called_once_with("/repo", source_branch="feature/t1", target_branch="main")
    mock_tracker.update_task_status.assert_any_call("t1", TaskStatus.RUNNING, assigned_branch="feature/t1", error="")
    mock_tracker.update_task_status.assert_any_call("t1", TaskStatus.COMPLETED)


@pytest.mark.asyncio
async def test_completed_task_promotes_the_app_preview(tmp_path, mock_tracker, mock_sandbox, mock_git):
    from painkiller.core.preview import read_preview

    project = Project(id="p1", name="App", repo_path=str(tmp_path), api_key="k")
    task = Task(id="t1", project_id="p1", title="Tela de lista", description="Desc")
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="Success")
    staged = tmp_path / ".painkiller" / "preview-build"
    staged.mkdir(parents=True)
    (staged / "index.html").write_text("<html></html>")

    await PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git).dispatch_task("t1")

    assert read_preview(str(tmp_path))["task_title"] == "Tela de lista"


@pytest.mark.asyncio
async def test_failed_merge_does_not_promote_the_app_preview(tmp_path, mock_tracker, mock_sandbox, mock_git):
    from painkiller.core.preview import read_preview

    project = Project(id="p1", name="App", repo_path=str(tmp_path), api_key="k")
    task = Task(id="t1", project_id="p1", title="Tela de lista", description="Desc")
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="Success")
    mock_git.merge_branch.return_value = (1, "conflict")
    staged = tmp_path / ".painkiller" / "preview-build"
    staged.mkdir(parents=True)
    (staged / "index.html").write_text("<html></html>")

    await PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git).dispatch_task("t1")

    assert read_preview(str(tmp_path)) is None


@pytest.mark.asyncio
async def test_dispatch_task_treats_test_exit_code_5_as_success(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo", api_key="k")
    task = Task(id="t1", project_id="p1", title="Build HTML Page", description="Desc")

    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="Success")
    # Exit code 5 from pytest means 0 tests collected
    mock_sandbox.run_tests.return_value = (5, "collected 0 items\nno tests ran")

    orchestrator = PainkillerOrchestrator(
        tracker=mock_tracker,
        sandbox=mock_sandbox,
        git=mock_git,
    )

    await orchestrator.dispatch_task("t1")

    mock_tracker.update_task_status.assert_any_call("t1", TaskStatus.COMPLETED)


@pytest.mark.asyncio
async def test_dispatch_task_pause_on_clarification(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo", api_key="k")
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
    project = Project(id="p1", name="App", repo_path="/repo", api_key="k", default_branch="main")
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
    project = Project(id="p1", name="App", repo_path="/repo", api_key="k", default_branch="main")
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
    project = Project(id="p1", name="App", repo_path="/repo", api_key="k")
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
async def test_failed_run_still_pushes_branch_for_the_ui_link(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo", api_key="k")
    task = Task(id="t1", project_id="p1", title="T", description="D")
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_git.push.return_value = (0, "Pushed")
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=1, logs="boom")

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    await orchestrator.dispatch_task("t1")

    # Ao criar a branch e depois da falha: o link do card nunca dá 404 no Gitea.
    assert [c.args for c in mock_git.push.call_args_list] == [("/repo", "feature/t1")] * 2


@pytest.mark.asyncio
async def test_retry_after_failure_tells_agent_to_continue(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo", api_key="k")
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
    project = Project(id="p1", name="App", repo_path="/repo", api_key="k")
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
async def test_answered_clarifications_reach_the_agent_prompt(mock_tracker, mock_sandbox, mock_git):
    """Sem isto a reexecução após a resposta refaz a mesma pergunta (exit 42 em loop)."""
    project = Project(id="p1", name="App", repo_path="/repo", api_key="k")
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
    assert "auth.py" in instructions
    assert "NÃO pergunte de novo" in instructions
    assert "Open?" not in instructions


@pytest.mark.asyncio
async def test_prompt_has_no_clarification_block_without_answers(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo", api_key="k")
    task = Task(id="t1", project_id="p1", title="Build Feature", description="Desc")
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_tracker.list_clarifications.return_value = []
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="ok")

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    await orchestrator.dispatch_task("t1")

    instructions = mock_sandbox.run_task.call_args.args[2]
    assert "Esclarecimentos já respondidos" not in instructions


@pytest.mark.asyncio
async def test_tracker_without_history_does_not_block_dispatch(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo", api_key="k")
    task = Task(id="t1", project_id="p1", title="Build Feature", description="Desc")
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_tracker.list_clarifications.side_effect = RuntimeError("boom")
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="ok")

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    await orchestrator.dispatch_task("t1")

    mock_sandbox.run_task.assert_called_once()


@pytest.mark.asyncio
async def test_prompt_without_superpowers_goes_straight_to_the_point(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo", api_key="k")
    task = Task(id="t1", project_id="p1", title="Fix typo", description="Desc", use_superpowers=False)
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_tracker.list_clarifications.return_value = []
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="ok")

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    await orchestrator.dispatch_task("t1")

    instructions = mock_sandbox.run_task.call_args.args[2]
    assert "1. NÃO use as skills do Superpowers" in instructions
    assert "Utilize as skills" not in instructions
    assert "4. Faça commit" in instructions
    # O protocolo de dúvidas (exit 42) não depende do superpowers.
    assert "painkiller ask" in instructions


def test_prompt_with_superpowers_keeps_the_skills(mock_tracker, mock_sandbox, mock_git):
    project = Project(id="p1", name="App", repo_path="/repo", api_key="k")
    task = Task(id="t1", project_id="p1", title="Build", description="Desc")
    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)

    instructions = orchestrator._build_task_instructions(task, project)

    assert "1. Utilize as skills e boas práticas do plugin Superpowers" in instructions
    assert "NÃO use as skills" not in instructions
    assert "3. Faça commit" in instructions


@pytest.mark.asyncio
async def test_prompt_carries_android_environment_and_template_guidelines(mock_tracker, mock_sandbox, mock_git):
    from painkiller.core.domain.models import ProjectTemplate

    project = Project(id="p1", name="App", repo_path="/repo", api_key="k")
    task = Task(id="t1", project_id="p1", title="Tela de login", description="Desc")
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_tracker.list_clarifications.return_value = []
    mock_tracker.get_project_template.return_value = ProjectTemplate(
        id="android-kotlin", name="Android", prompt="Use Hilt para injeção de dependência."
    )
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="ok")

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    await orchestrator.dispatch_task("t1")

    instructions = mock_sandbox.run_task.call_args.args[2]
    assert "app Android nativo em Kotlin" in instructions
    assert "./gradlew testDebugUnitTest" in instructions
    assert "## Diretrizes técnicas do app" in instructions
    assert "Use Hilt para injeção de dependência." in instructions


@pytest.mark.asyncio
async def test_capacitor_project_gets_its_own_environment_and_guidelines(mock_tracker, mock_sandbox, mock_git):
    from painkiller.core.domain.models import ProjectTemplate

    project = Project(
        id="p1", name="Clipes", repo_path="/repo", api_key="k",
        template_id="capacitor-react", default_branch="trunk",
    )
    task = Task(id="t1", project_id="p1", title="Lista de clipes", description="Desc")
    mock_tracker.get_task.return_value = task
    mock_tracker.get_project.return_value = project
    mock_tracker.list_clarifications.return_value = []
    mock_tracker.get_project_template.return_value = ProjectTemplate(
        id="capacitor-react", name="Capacitor", prompt="Use TanStack Query."
    )
    mock_sandbox.run_task.return_value = ExecutionResult(exit_code=0, logs="ok")
    mock_sandbox.run_tests.return_value = (0, "ok")

    orchestrator = PainkillerOrchestrator(tracker=mock_tracker, sandbox=mock_sandbox, git=mock_git)
    await orchestrator.dispatch_task("t1")

    instructions = mock_sandbox.run_task.call_args.args[2]
    assert "React + Ionic" in instructions and "npm test" in instructions
    assert "app Android nativo em Kotlin" not in instructions
    assert "Use TanStack Query." in instructions
    # As diretrizes vêm do template do projeto, não do Android nativo.
    mock_tracker.get_project_template.assert_awaited_with("capacitor-react")
    # A verificação compara a tarefa com a branch padrão do projeto.
    assert mock_sandbox.run_tests.call_args.kwargs["base_branch"] == "trunk"
