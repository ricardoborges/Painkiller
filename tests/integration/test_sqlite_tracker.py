"""Integration tests for SQLiteIssueTracker adapter."""

import pytest
from painkiller.core.domain.models import (
    TaskStatus,
    ClarificationStatus,
    AnalysisSession,
    AnalysisStatus,
    AgentEvent,
    AgentEventType,
)
from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker


@pytest.fixture
async def tracker():
    t = SQLiteIssueTracker(db_url="sqlite+aiosqlite:///:memory:")
    await t.init_db()
    yield t
    await t.close()


@pytest.mark.asyncio
async def test_skip_tests_flag_persists(tracker: SQLiteIssueTracker):
    proj = await tracker.create_project(name="App", repo_path="/tmp/app")
    task = await tracker.create_task(project_id=proj.id, title="T", description="D")
    assert task.skip_tests is False

    updated = await tracker.set_task_skip_tests(task.id, True)

    assert updated.skip_tests is True
    assert (await tracker.get_task(task.id)).skip_tests is True


@pytest.mark.asyncio
async def test_project_and_task_crud(tracker: SQLiteIssueTracker):
    # 1. Create project
    proj = await tracker.create_project(
        name="Test App",
        repo_path="/tmp/test_app",
        default_branch="main",
    )
    assert proj.id is not None
    assert proj.name == "Test App"

    # 2. Get project
    fetched_proj = await tracker.get_project(proj.id)
    assert fetched_proj is not None
    assert fetched_proj.name == "Test App"

    # 3. Create task
    task = await tracker.create_task(
        project_id=proj.id,
        title="Setup Auth",
        description="Implement auth middleware",
        target_files=["auth.py"],
        acceptance_criteria=["Must reject invalid token"],
    )
    assert task.id is not None
    assert task.status == TaskStatus.BACKLOG

    # 4. List tasks
    tasks = await tracker.list_tasks(project_id=proj.id)
    assert len(tasks) == 1
    assert tasks[0].title == "Setup Auth"

    # 5. Update status
    updated_task = await tracker.update_task_status(task.id, TaskStatus.READY)
    assert updated_task.status == TaskStatus.READY

    filtered_ready = await tracker.list_tasks(project_id=proj.id, status=TaskStatus.READY)
    assert len(filtered_ready) == 1

    filtered_completed = await tracker.list_tasks(project_id=proj.id, status=TaskStatus.COMPLETED)
    assert len(filtered_completed) == 0


@pytest.mark.asyncio
async def test_clarification_flow(tracker: SQLiteIssueTracker):
    proj = await tracker.create_project(name="Clarify App", repo_path="/tmp/clarify")
    task = await tracker.create_task(project_id=proj.id, title="Database Task", description="Choose ORM")

    # Create clarification
    clar = await tracker.create_clarification(
        task_id=task.id,
        question="Use SQLAlchemy or Tortoise?",
        context_summary="models.py setup",
    )
    assert clar.id is not None
    assert clar.status == ClarificationStatus.PENDING

    # Check pending
    pending = await tracker.get_pending_clarification(task.id)
    assert pending is not None
    assert pending.question == "Use SQLAlchemy or Tortoise?"

    # Resolve
    resolved = await tracker.resolve_clarification(clar.id, answer="Use SQLAlchemy 2.0")
    assert resolved.status == ClarificationStatus.ANSWERED
    assert resolved.answer == "Use SQLAlchemy 2.0"

    # Pending should now be None
    pending_after = await tracker.get_pending_clarification(task.id)
    assert pending_after is None


async def test_analysis_session_persistence(tracker: SQLiteIssueTracker):
    proj = await tracker.create_project(name="Analysis App", repo_path="/tmp/analysis")

    # 1. Salvar sessão inicial
    session = AnalysisSession(
        id="analysis-test-1",
        project_id=proj.id,
        status=AnalysisStatus.STARTING,
        container_name="pk-test-container",
        claude_session_id="claude-uuid-1",
    )
    saved = await tracker.save_analysis_session(session)
    assert saved.id == "analysis-test-1"
    assert saved.claude_session_id == "claude-uuid-1"

    # 2. Obter sessão ativa
    active = await tracker.get_active_analysis_session(proj.id)
    assert active is not None
    assert active.id == "analysis-test-1"

    # 3. Salvar eventos da conversa
    evt1 = AgentEvent(type=AgentEventType.ASSISTANT, text="Olá! Qual o escopo?")
    evt2 = AgentEvent(type=AgentEventType.USER, text="Um portal de autenticação")
    await tracker.save_analysis_event(session.id, evt1)
    await tracker.save_analysis_event(session.id, evt2)

    events = await tracker.list_analysis_events(session.id)
    assert len(events) == 2
    assert events[0].type == AgentEventType.ASSISTANT
    assert events[0].text == "Olá! Qual o escopo?"
    assert events[1].type == AgentEventType.USER
    assert events[1].text == "Um portal de autenticação"

    # 4. Finalizar sessão e verificar que get_active retorna None
    session.status = AnalysisStatus.FINISHED
    await tracker.save_analysis_session(session)

    active_after = await tracker.get_active_analysis_session(proj.id)
    assert active_after is None


async def test_init_db_migrates_missing_columns(tmp_path):
    import sqlite3

    db_file = tmp_path / "legacy.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    # Cria tabela projects legada sem a coluna repo_url
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE projects (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            repo_path VARCHAR NOT NULL,
            description TEXT,
            purpose TEXT,
            solution_description TEXT,
            attachments TEXT,
            default_branch VARCHAR,
            created_at DATETIME
        )
        """
    )
    conn.execute(
        "INSERT INTO projects (id, name, repo_path, default_branch, created_at) VALUES ('p1', 'Legacy', '/tmp/leg', 'main', '2026-09-20 00:00:00')"
    )
    conn.commit()
    conn.close()

    tracker = SQLiteIssueTracker(db_url=db_url)
    await tracker.init_db()

    # A consulta a projects deve funcionar normalmente com repo_url migrado
    projects = await tracker.list_projects()
    assert len(projects) == 1
    assert projects[0].id == "p1"
    assert projects[0].repo_url is None

    await tracker.close()


