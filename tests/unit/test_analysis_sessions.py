import pytest
from unittest.mock import AsyncMock, MagicMock
from painkiller.engine.analysis import AnalysisOrchestrator, build_analysis_prompt
from painkiller.core.domain.models import Project, IterationSession, SessionStatus, Task


@pytest.mark.asyncio
async def test_commit_backlog_associates_tasks_to_iteration_session(tmp_path):
    tracker = AsyncMock()
    agent = AsyncMock()
    orchestrator = AnalysisOrchestrator(agent=agent, tracker=tracker)

    # Configurar repo falso com .painkiller/backlog.json
    repo = tmp_path / "repo"
    repo.mkdir()
    pk_dir = repo / ".painkiller"
    pk_dir.mkdir()
    (pk_dir / "backlog.json").write_text(
        '{"spec_path": "docs/superpowers/specs/spec.md", "tasks": [{"title": "T1", "description": "D1"}]}',
        encoding="utf-8",
    )

    session = IterationSession(id="sess-1", project_id="proj-1", number=1, title="Sessão 1")
    tracker.get_session.return_value = session
    tracker.create_task.return_value = MagicMock(id="task-1", title="T1")

    # Mock AnalysisRun
    run = MagicMock(repo_path=str(repo), session=MagicMock(project_id="proj-1", id="an-1"))
    orchestrator.runs["an-1"] = run

    await orchestrator.commit_backlog("an-1", iteration_session_id="sess-1")

    tracker.create_task.assert_called_once()
    assert tracker.create_task.call_args.kwargs.get("session_id") == "sess-1"
    tracker.update_session.assert_called_once()
    updated_session = tracker.update_session.call_args.args[0]
    assert updated_session.status == SessionStatus.BACKLOG
    assert updated_session.spec_path == "docs/superpowers/specs/spec.md"


def test_build_analysis_prompt_cumulative_context():
    project = Project(
        id="p1",
        name="Meu App",
        repo_path="/repo",
        description="Um app legal",
        purpose="Facilitar vendas",
        solution_description="Painel de controle",
    )
    previous_sessions = [
        IterationSession(
            id="s1",
            project_id="p1",
            number=1,
            title="Sessão 1",
            status=SessionStatus.COMPLETED,
            spec_path="docs/superpowers/specs/2026-09-01-spec.md",
        )
    ]
    completed_tasks = [
        Task(
            id="t1",
            project_id="p1",
            session_id="s1",
            title="Setup de banco de dados",
            description="Criar migrations",
        )
    ]

    prompt = build_analysis_prompt(
        project,
        session_number=2,
        previous_sessions=previous_sessions,
        previous_completed_tasks=completed_tasks,
    )

    assert "CICLO ÁGIL ITERATIVO: SESSÃO 2" in prompt
    assert "Sessão 1" in prompt
    assert "Setup de banco de dados" in prompt


def _start_fixture(tmp_path):
    tracker = AsyncMock()
    agent = AsyncMock()
    agent.start.return_value = "pk-agent"
    orchestrator = AnalysisOrchestrator(agent=agent, tracker=tracker)
    project = Project(id="p1", name="App", repo_path=str(tmp_path))
    s1 = IterationSession(
        id="s1", project_id="p1", number=1, title="Sessão 1",
        status=SessionStatus.IN_SPRINT, analysis_session_id="analysis-old",
    )
    s2 = IterationSession(id="s2", project_id="p1", number=2, title="Sessão 2")
    tracker.list_sessions.return_value = [s1, s2]
    tracker.get_session.side_effect = lambda sid: {"s1": s1, "s2": s2}.get(sid)
    tracker.get_active_analysis_session.return_value = None
    tracker.list_tasks.return_value = []
    return orchestrator, project, agent, s1, s2


async def test_start_binds_analysis_to_requested_iteration_session(tmp_path):
    orchestrator, project, agent, s1, s2 = _start_fixture(tmp_path)

    session = await orchestrator.start(project, iteration_session_id="s2")

    assert s2.analysis_session_id == session.id
    assert s1.analysis_session_id == "analysis-old"
    assert "SESSÃO 2" in agent.start.call_args.kwargs["prompt"]
    # Cada análise grava o backlog no próprio arquivo, nunca no compartilhado.
    assert f".painkiller/backlogs/{session.id}.json" in agent.start.call_args.kwargs["prompt"]
    assert ".painkiller/backlog.json" not in agent.start.call_args.kwargs["prompt"]


async def test_start_without_iteration_session_uses_latest_not_first(tmp_path):
    orchestrator, project, agent, s1, s2 = _start_fixture(tmp_path)

    session = await orchestrator.start(project)

    assert s2.analysis_session_id == session.id
    assert s1.analysis_session_id == "analysis-old"


async def test_start_does_not_reuse_active_analysis_of_another_session(tmp_path):
    orchestrator, project, agent, s1, s2 = _start_fixture(tmp_path)
    first = await orchestrator.start(project, iteration_session_id="s1")
    agent.is_alive.return_value = True

    second = await orchestrator.start(project, iteration_session_id="s2")

    assert second.id != first.id
    assert s1.analysis_session_id == first.id
    assert s2.analysis_session_id == second.id


def test_build_analysis_prompt_chat_mode_from_second_session():
    project = Project(id="p1", name="App", repo_path="/repo")

    first = build_analysis_prompt(project, session_number=1)
    second = build_analysis_prompt(project, session_number=2)

    assert "Conduza a elicitação" in first
    assert "modo conversa" not in first
    assert "modo conversa" in second
    assert "Conduza a elicitação" not in second
    # O formato de opções e a entrega do backlog continuam valendo no chat.
    assert "painkiller-choices" in second
    assert ".painkiller/backlog" in second
