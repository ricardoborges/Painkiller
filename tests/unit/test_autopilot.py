"""Unit tests for the project autopilot (build the whole backlog, then publish)."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from painkiller.core.domain.models import DeploymentInfo, Project, Task, TaskStatus
from painkiller.engine.autopilot import AutopilotState, ProjectAutopilot, pick_next


def _task(tid: str, status=TaskStatus.BACKLOG, deps=(), minutes=0) -> Task:
    return Task(
        id=tid,
        project_id="p1",
        title=f"Tarefa {tid}",
        description="",
        status=status,
        dependencies=list(deps),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes),
    )


def test_pick_next_respects_order_and_dependencies():
    tasks = [
        _task("b", deps=["a"], minutes=1),
        _task("a", status=TaskStatus.COMPLETED, minutes=0),
        _task("c", deps=["b"], minutes=2),
    ]
    assert pick_next(tasks).id == "b"

    tasks[0].status = TaskStatus.COMPLETED
    assert pick_next(tasks).id == "c"

    tasks[2].status = TaskStatus.FAILED
    assert pick_next(tasks) is None


def test_pick_next_skips_tasks_not_runnable():
    assert pick_next([_task("a", status=TaskStatus.IN_REVIEW)]) is None
    assert pick_next([_task("a", status=TaskStatus.AWAITING_ANALYST)]) is None
    assert pick_next([_task("a", status=TaskStatus.READY)]).id == "a"


class FakeTracker:
    """Just enough of IssueTrackerPort for the loop: a dict of tasks."""

    def __init__(self, tasks: list[Task], project: Project):
        self.tasks = {t.id: t for t in tasks}
        self.project = project

    async def get_project(self, project_id):
        return self.project

    async def list_tasks(self, project_id, status=None):
        return list(self.tasks.values())


async def _wait(autopilot: ProjectAutopilot, project_id: str):
    task = autopilot._tasks[project_id]
    await asyncio.wait_for(task, timeout=5)
    return autopilot.status(project_id)


def _orchestrator(tracker: FakeTracker, outcome: TaskStatus, publish_url="https://app.example"):
    orch = MagicMock()
    orch.can_publish = MagicMock(return_value=True)

    async def dispatch(task_id):
        tracker.tasks[task_id].status = outcome
        return tracker.tasks[task_id]

    async def merge(task_id):
        tracker.tasks[task_id].status = TaskStatus.COMPLETED
        return tracker.tasks[task_id]

    async def publish(project_id):
        tracker.project.deployment = DeploymentInfo(app_uuid="a", url=publish_url)
        return tracker.project

    orch.dispatch_task = AsyncMock(side_effect=dispatch)
    orch.merge_task = AsyncMock(side_effect=merge)
    orch.publish_project = AsyncMock(side_effect=publish)
    return orch


@pytest.mark.asyncio
async def test_runs_everything_in_order_and_publishes():
    project = Project(id="p1", name="App", repo_path="/repo")
    tracker = FakeTracker([_task("a"), _task("b", deps=["a"], minutes=1)], project)
    orch = _orchestrator(tracker, TaskStatus.IN_REVIEW)
    autopilot = ProjectAutopilot(orchestrator=orch, tracker=tracker)

    run = await autopilot.start("p1")
    assert run.state == AutopilotState.RUNNING

    final = await _wait(autopilot, "p1")
    assert final.state == AutopilotState.DONE
    assert final.completed == 2
    assert [c.args[0] for c in orch.dispatch_task.await_args_list] == ["a", "b"]
    assert orch.merge_task.await_count == 2
    orch.publish_project.assert_awaited_once_with("p1")
    assert "https://app.example" in final.message


@pytest.mark.asyncio
async def test_pauses_when_agent_asks_a_question():
    project = Project(id="p1", name="App", repo_path="/repo")
    tracker = FakeTracker([_task("a"), _task("b", minutes=1)], project)
    orch = _orchestrator(tracker, TaskStatus.AWAITING_ANALYST)
    autopilot = ProjectAutopilot(orchestrator=orch, tracker=tracker)

    await autopilot.start("p1")
    final = await _wait(autopilot, "p1")

    assert final.state == AutopilotState.PAUSED
    assert final.current_task_id == "a"
    orch.dispatch_task.assert_awaited_once()
    orch.publish_project.assert_not_awaited()


@pytest.mark.asyncio
async def test_stops_on_failure_without_publishing():
    project = Project(id="p1", name="App", repo_path="/repo")
    tracker = FakeTracker([_task("a")], project)
    orch = _orchestrator(tracker, TaskStatus.FAILED)
    autopilot = ProjectAutopilot(orchestrator=orch, tracker=tracker)

    await autopilot.start("p1")
    final = await _wait(autopilot, "p1")
    assert final.state == AutopilotState.FAILED
    orch.publish_project.assert_not_awaited()


@pytest.mark.asyncio
async def test_does_not_publish_when_provider_not_configured():
    project = Project(id="p1", name="App", repo_path="/repo")
    tracker = FakeTracker([_task("a")], project)
    orch = _orchestrator(tracker, TaskStatus.IN_REVIEW)
    orch.can_publish = MagicMock(return_value=False)
    autopilot = ProjectAutopilot(orchestrator=orch, tracker=tracker)

    await autopilot.start("p1")
    final = await _wait(autopilot, "p1")
    assert final.state == AutopilotState.DONE
    orch.publish_project.assert_not_awaited()


@pytest.mark.asyncio
async def test_refuses_empty_backlog_and_reuses_active_run():
    project = Project(id="p1", name="App", repo_path="/repo")
    autopilot = ProjectAutopilot(orchestrator=MagicMock(), tracker=FakeTracker([], project))
    with pytest.raises(RuntimeError):
        await autopilot.start("p1")

    tracker = FakeTracker([_task("a")], project)
    orch = _orchestrator(tracker, TaskStatus.IN_REVIEW)
    gate = asyncio.Event()

    async def slow_dispatch(task_id):
        await gate.wait()
        tracker.tasks[task_id].status = TaskStatus.IN_REVIEW
        return tracker.tasks[task_id]

    orch.dispatch_task = AsyncMock(side_effect=slow_dispatch)
    autopilot = ProjectAutopilot(orchestrator=orch, tracker=tracker)
    first = await autopilot.start("p1")
    second = await autopilot.start("p1")
    assert first is second
    gate.set()
    await _wait(autopilot, "p1")
    orch.dispatch_task.assert_awaited_once()
