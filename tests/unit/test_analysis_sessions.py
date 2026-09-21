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
