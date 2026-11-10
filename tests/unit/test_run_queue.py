"""The server-side run queue ("Executar Todas")."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from painkiller.core.domain.models import IterationSession, Project, SessionStatus, Task, TaskStatus
from painkiller.engine.run_queue import (
    QueueBusyError,
    RunQueueService,
    SessionClosedError,
    execution_order,
    notification_text,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_task(n: int, status: TaskStatus = TaskStatus.BACKLOG, deps: tuple[str, ...] = ()) -> Task:
    return Task(
        id=f"t{n}", project_id="p1", session_id="s1", title=f"Tarefa {n}", description="D",
        status=status, dependencies=list(deps), created_at=T0 + timedelta(minutes=n),
    )


class World:
    """Tracker and orchestrator fakes sharing one task table."""

    def __init__(self, tasks: list[Task], outcomes: dict[str, TaskStatus] | None = None):
        self.tasks = {t.id: t for t in tasks}
        self.outcomes = outcomes or {}
        self.dispatched: list[str] = []
        self.project = Project(id="p1", name="App", repo_path="/repo", api_key="k")
        self.session = IterationSession(id="s1", project_id="p1", number=1, title="S", status=SessionStatus.BACKLOG)
        self.tracker = AsyncMock()
        self.tracker.list_tasks.side_effect = lambda project_id, **_: list(self.tasks.values())
        self.tracker.get_session.side_effect = lambda sid: self.session if sid == "s1" else None
        self.tracker.get_project.return_value = self.project
        self.orchestrator = MagicMock()
        self.orchestrator.dispatch_task = AsyncMock(side_effect=self._dispatch)
        self.orchestrator.merge_task = AsyncMock(side_effect=self._merge)
        self.gate: asyncio.Event | None = None
        self.notified: list[str] = []

    async def _dispatch(self, task_id: str) -> Task:
        self.dispatched.append(task_id)
        if self.gate is not None:
            await self.gate.wait()
        task = self.tasks[task_id]
        task.status = self.outcomes.get(task_id, TaskStatus.COMPLETED)
        return task

    async def _merge(self, task_id: str) -> Task:
        self.tasks[task_id].status = TaskStatus.COMPLETED
        return self.tasks[task_id]

    async def _notify(self, project, run) -> None:
        self.notified.append(run.reason)

    def service(self, **kwargs) -> RunQueueService:
        return RunQueueService(self.tracker, self.orchestrator, notify=self._notify, **kwargs)


async def finished(service: RunQueueService) -> dict:
    await service._runs["p1"].job
    return service.state("p1")


def test_execution_order_puts_dependencies_first():
    tasks = [make_task(1, deps=("t3",)), make_task(2), make_task(3)]
    assert [t.id for t in execution_order(tasks)] == ["t3", "t1", "t2"]


def test_execution_order_survives_a_dependency_cycle():
    tasks = [make_task(1, deps=("t2",)), make_task(2, deps=("t1",))]
    assert sorted(t.id for t in execution_order(tasks)) == ["t1", "t2"]


async def test_queue_runs_every_task_in_order_without_a_client():
    world = World([make_task(1, deps=("t2",)), make_task(2), make_task(3, TaskStatus.COMPLETED)])
    service = world.service()

    started = await service.start(world.project, "s1")
    assert started["running"] is True
    state = await finished(service)

    assert world.dispatched == ["t2", "t1"]
    assert state["running"] is False and state["reason"] == "all_done"
    assert world.session.status == SessionStatus.IN_SPRINT
    assert world.notified == ["all_done"]


async def test_queue_stops_on_a_failed_task_and_says_which():
    world = World([make_task(1), make_task(2)], outcomes={"t1": TaskStatus.FAILED})
    service = world.service()

    await service.start(world.project, "s1")
    state = await finished(service)

    assert world.dispatched == ["t1"]
    assert (state["reason"], state["task_id"], state["task_title"]) == ("failed", "t1", "Tarefa 1")
    assert world.notified == ["failed"]


async def test_queue_resumes_after_the_question_that_stopped_it_is_answered():
    world = World([make_task(1), make_task(2)], outcomes={"t1": TaskStatus.AWAITING_ANALYST})
    service = world.service()
    await service.start(world.project, "s1")
    assert (await finished(service))["reason"] == "question"

    # A resposta redespacha a tarefa pela rota; concluída, a fila segue sozinha.
    world.tasks["t1"].status = TaskStatus.COMPLETED
    await service.resume_after_answer(world.tasks["t1"])
    state = await finished(service)

    assert world.dispatched == ["t1", "t2"]
    assert state["reason"] == "all_done"


async def test_queue_stops_on_unmet_dependencies_without_dispatching():
    world = World([make_task(1, deps=("fora",))])
    service = world.service()

    await service.start(world.project, "s1")
    state = await finished(service)

    assert world.dispatched == []
    assert state["reason"] == "blocked" and state["blocked_by"] == ["fora"]
    assert world.notified == []


async def test_pause_lets_the_running_task_finish_and_starts_no_other():
    world = World([make_task(1), make_task(2)])
    world.gate = asyncio.Event()
    service = world.service()
    await service.start(world.project, "s1")
    await asyncio.sleep(0.01)

    assert service.pause("p1")["pausing"] is True
    world.gate.set()
    state = await finished(service)

    assert world.dispatched == ["t1"]
    assert world.tasks["t1"].status == TaskStatus.COMPLETED
    assert state["reason"] == "paused" and world.notified == []


async def test_second_start_is_refused_while_running():
    world = World([make_task(1)])
    world.gate = asyncio.Event()
    service = world.service()
    await service.start(world.project, "s1")
    await asyncio.sleep(0.01)

    with pytest.raises(QueueBusyError):
        await service.start(world.project, "s1")

    world.gate.set()
    await finished(service)


async def test_closed_session_is_refused():
    world = World([make_task(1)])
    world.session.status = SessionStatus.COMPLETED
    with pytest.raises(SessionClosedError):
        await world.service().start(world.project, "s1")


async def test_budget_reached_pauses_before_the_next_task():
    world = World([make_task(1), make_task(2)])
    spent = iter([False, True])

    async def over_budget(project) -> bool:
        return next(spent)

    service = world.service(over_budget=over_budget)
    await service.start(world.project, "s1")
    state = await finished(service)

    assert world.dispatched == ["t1"]
    assert state["reason"] == "budget" and state["task_id"] == "t2"
    assert world.notified == ["budget"]


async def test_dispatch_error_stops_the_queue_with_its_message():
    world = World([make_task(1)])
    world.orchestrator.dispatch_task.side_effect = RuntimeError("sem chave")
    service = world.service()

    await service.start(world.project, "s1")
    state = await finished(service)

    assert state["reason"] == "run_failed" and state["detail"] == "sem chave"


async def test_in_review_task_is_merged_by_the_queue():
    world = World([make_task(1, TaskStatus.IN_REVIEW)])
    service = world.service()

    await service.start(world.project, "s1")
    state = await finished(service)

    world.orchestrator.merge_task.assert_awaited_once_with("t1")
    assert state["reason"] == "all_done"


async def test_notification_text_follows_the_project_language():
    world = World([make_task(1)], outcomes={"t1": TaskStatus.AWAITING_ANALYST})
    service = world.service()
    await service.start(world.project, "s1")
    await finished(service)
    run = service._runs["p1"]

    subject, body = notification_text(world.project, run)
    assert "espera a sua resposta" in subject and "Tarefa 1" in body

    english = world.project.model_copy(update={"language": "en-US"})
    subject, body = notification_text(english, run)
    assert "waiting for your answer" in subject and "Tarefa 1" in body


async def test_queue_api_starts_reports_and_pauses(tmp_path):
    from httpx import ASGITransport, AsyncClient

    from painkiller.api.server import create_app
    from tests.auth_helpers import admin_headers

    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'queue.db'}")
    async with app.router.lifespan_context(app):
        tracker = app.state.tracker
        project = await tracker.create_project(name="App", repo_path=str(tmp_path / "repo"), api_key="k")
        task = await tracker.create_task(project_id=project.id, title="Tela", description="D")
        gate = asyncio.Event()

        async def dispatch(task_id: str):
            await gate.wait()
            return await tracker.update_task_status(task_id, TaskStatus.COMPLETED)

        app.state.orchestrator.dispatch_task = dispatch
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            url = f"/api/projects/{project.id}/queue"
            assert (await client.get(url, headers=admin_headers())).json()["running"] is False

            resp = await client.post(url, json={}, headers=admin_headers())
            assert resp.status_code == 200, resp.text
            assert resp.json()["running"] is True
            assert (await client.post(url, json={}, headers=admin_headers())).status_code == 409

            await asyncio.sleep(0.05)
            state = (await client.get(url, headers=admin_headers())).json()
            assert (state["reason"], state["task_id"]) == ("running", task.id)

            assert (await client.delete(url, headers=admin_headers())).json()["pausing"] is True
            gate.set()
            await app.state.run_queue._runs[project.id].job
            state = (await client.get(url, headers=admin_headers())).json()
            assert state["running"] is False and state["reason"] == "paused"
