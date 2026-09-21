import pytest
from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker
from painkiller.core.domain.models import Project, TaskStatus, SessionStatus


@pytest.mark.asyncio
async def test_ensure_initial_session_and_incremental_creation():
    tracker = SQLiteIssueTracker("sqlite+aiosqlite:///:memory:")
    await tracker.init_db()

    project = await tracker.create_project(
        name="Teste",
        repo_path="/tmp/test",
        description="Desc",
        purpose="Prop",
        solution_description="Sol",
    )

    # Primeira chamada deve criar Sessão 1
    s1 = await tracker.ensure_initial_session(project.id)
    assert s1.number == 1
    assert s1.title == "Sessão 1"
    assert s1.status == SessionStatus.PLANNING

    # Chamada subsequente retorna a existente
    s1_again = await tracker.ensure_initial_session(project.id)
    assert s1_again.id == s1.id

    # Criar nova sessão deve gerar Sessão 2
    s2 = await tracker.create_session(project.id)
    assert s2.number == 2
    assert s2.title == "Sessão 2"

    sessions = await tracker.list_sessions(project.id)
    assert len(sessions) == 2
    assert [s.number for s in sessions] == [1, 2]

    # Atualizar sessão
    s1.status = SessionStatus.IN_SPRINT
    s1.spec_path = "docs/superpowers/specs/spec.md"
    updated = await tracker.update_session(s1)
    assert updated.status == SessionStatus.IN_SPRINT
    assert updated.spec_path == "docs/superpowers/specs/spec.md"

    fetched = await tracker.get_session(s1.id)
    assert fetched is not None
    assert fetched.status == SessionStatus.IN_SPRINT


@pytest.mark.asyncio
async def test_tasks_with_session_and_migration():
    tracker = SQLiteIssueTracker("sqlite+aiosqlite:///:memory:")
    await tracker.init_db()

    project = await tracker.create_project(
        name="Teste",
        repo_path="/tmp/test",
        description="Desc",
        purpose="Prop",
        solution_description="Sol",
    )

    s1 = await tracker.ensure_initial_session(project.id)
    s2 = await tracker.create_session(project.id)

    # Criar tarefa na Sessão 1
    t1 = await tracker.create_task(
        project_id=project.id,
        title="Tarefa 1",
        description="Desc 1",
        session_id=s1.id,
    )
    assert t1.session_id == s1.id

    # Criar tarefa na Sessão 2
    t2 = await tracker.create_task(
        project_id=project.id,
        title="Tarefa 2",
        description="Desc 2",
        session_id=s2.id,
    )
    assert t2.session_id == s2.id

    # Listar filtrando por sessão
    s1_tasks = await tracker.list_tasks(project.id, session_id=s1.id)
    assert len(s1_tasks) == 1
    assert s1_tasks[0].id == t1.id

    s2_tasks = await tracker.list_tasks(project.id, session_id=s2.id)
    assert len(s2_tasks) == 1
    assert s2_tasks[0].id == t2.id

    # Migrar tarefa 1 para Sessão 2
    migrated = await tracker.migrate_tasks_to_session([t1.id], s2.id)
    assert len(migrated) == 1
    assert migrated[0].session_id == s2.id

    s2_tasks_after = await tracker.list_tasks(project.id, session_id=s2.id)
    assert len(s2_tasks_after) == 2
