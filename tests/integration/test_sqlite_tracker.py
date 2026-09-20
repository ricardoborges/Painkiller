"""Integration tests for SQLiteIssueTracker adapter."""

import pytest
from painkiller.core.domain.models import TaskStatus, ClarificationStatus
from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker


@pytest.fixture
async def tracker():
    t = SQLiteIssueTracker(db_url="sqlite+aiosqlite:///:memory:")
    await t.init_db()
    yield t
    await t.close()


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
