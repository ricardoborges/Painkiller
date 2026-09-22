"""Unit tests for the interactive initial-analysis engine and its event parsing."""

import asyncio
import json
import os
from typing import AsyncIterator, Optional
from unittest.mock import AsyncMock

import pytest

from painkiller.adapters.sandbox.docker_agent_session import parse_agent_line
from painkiller.core.domain.models import (
    AgentEvent,
    AgentEventType,
    AnalysisSession,
    AnalysisStatus,
    Project,
    Task,
)
from painkiller.core.ports.agent_session import AgentSessionPort
from painkiller.engine.analysis import (
    LEGACY_BACKLOG_RELATIVE,
    AnalysisOrchestrator,
    backlog_relative,
    build_analysis_prompt,
)


class FakeAgentSession(AgentSessionPort):
    """In-memory stand-in for the Docker adapter."""

    def __init__(self, events: list[AgentEvent]):
        self.events = events
        self.sent: list[str] = []
        self.closed = False
        self.stopped = False
        self.release = asyncio.Event()

    async def start(
        self,
        session_id,
        repo_path,
        prompt="",
        env=None,
        timeout_seconds=3600,
        resume=False,
        claude_session_id=None,
        harness=None,
        api_key=None,
        **kwargs,
    ) -> str:
        self.prompt = prompt
        self.resume = resume
        self.claude_session_id = claude_session_id
        self.harness = harness
        self.api_key = api_key
        return "pk-analysis-fake"

    async def is_alive(self, session_id) -> bool:
        return True

    async def send(self, session_id, text) -> None:
        self.sent.append(text)

    async def close_input(self, session_id) -> None:
        self.closed = True

    async def stop(self, session_id) -> None:
        self.stopped = True

    async def stream(self, session_id) -> AsyncIterator[AgentEvent]:
        for event in self.events:
            yield event
        self.release.set()


def _project(tmp_path) -> Project:
    return Project(
        id="proj-1",
        name="Painkiller",
        repo_path=str(tmp_path),
        description="Plataforma",
        purpose="Automatizar",
        solution_description="Agentes",
    )


# ---- parsing do stream-json ------------------------------------------------


def test_parses_assistant_text():
    line = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Qual o objetivo?"}]}}
    )
    event = parse_agent_line(line)
    assert event.type == AgentEventType.ASSISTANT
    assert event.text == "Qual o objetivo?"


def test_parses_tool_use_by_name():
    line = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write"}]}}
    )
    assert parse_agent_line(line).type == AgentEventType.TOOL_USE


def test_result_line_becomes_result_event():
    event = parse_agent_line(json.dumps({"type": "result", "result": "pronto"}))
    assert event.type == AgentEventType.RESULT
    assert event.text == "pronto"


def test_non_json_stderr_noise_is_surfaced_not_dropped():
    # Avisos do node chegam misturados no mesmo fluxo de logs do contêiner.
    event = parse_agent_line("npm warn deprecated foo@1.0.0")
    assert event.type == AgentEventType.ERROR


def test_parses_incremental_text_delta():
    line = json.dumps(
        {"type": "stream_event",
         "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Qual"}}}
    )
    event = parse_agent_line(line)
    assert event.type == AgentEventType.ASSISTANT_DELTA
    assert event.text == "Qual"


def test_parses_incremental_thinking_delta():
    line = json.dumps(
        {"type": "stream_event",
         "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "hm"}}}
    )
    assert parse_agent_line(line).type == AgentEventType.THINKING_DELTA


def test_signature_and_tool_input_deltas_have_nothing_to_show():
    for delta in ({"type": "signature_delta", "signature": "abc"},
                  {"type": "input_json_delta", "partial_json": "{\"a\":"}):
        line = json.dumps({"type": "stream_event",
                           "event": {"type": "content_block_delta", "delta": delta}})
        assert parse_agent_line(line) is None


def test_stream_event_that_is_not_a_delta_is_ignored():
    line = json.dumps({"type": "stream_event", "event": {"type": "message_stop"}})
    assert parse_agent_line(line) is None


def test_empty_assistant_block_yields_nothing():
    assert parse_agent_line(json.dumps({"type": "assistant", "message": {"content": []}})) is None


# ---- ciclo de vida da sessão -----------------------------------------------


async def test_start_boots_the_agent_and_streams_events(tmp_path):
    events = [
        AgentEvent(type=AgentEventType.ASSISTANT, text="Qual o objetivo?"),
        AgentEvent(type=AgentEventType.RESULT, text="Qual o objetivo?"),
    ]
    agent = FakeAgentSession(events)
    engine = AnalysisOrchestrator(agent=agent, tracker=AsyncMock())

    session = await engine.start(_project(tmp_path))
    await asyncio.wait_for(agent.release.wait(), timeout=5)
    await asyncio.sleep(0)

    assert session.container_name == "pk-analysis-fake"
    assert "superpowers:brainstorming" in agent.prompt
    received = [e async for e in engine.subscribe(session.id)]
    assert [e.text for e in received] == ["Qual o objetivo?", "Qual o objetivo?"]


async def test_result_event_hands_the_turn_back_to_the_analyst(tmp_path):
    agent = FakeAgentSession([AgentEvent(type=AgentEventType.RESULT, text="ok")])
    engine = AnalysisOrchestrator(agent=agent, tracker=AsyncMock())

    session = await engine.start(_project(tmp_path))
    await asyncio.wait_for(agent.release.wait(), timeout=5)
    await asyncio.sleep(0)

    assert session.status == AnalysisStatus.WAITING_ANALYST


async def test_sending_an_answer_flips_the_turn_back_to_the_agent(tmp_path):
    agent = FakeAgentSession([AgentEvent(type=AgentEventType.RESULT, text="ok")])
    engine = AnalysisOrchestrator(agent=agent, tracker=AsyncMock())

    session = await engine.start(_project(tmp_path))
    await asyncio.wait_for(agent.release.wait(), timeout=5)
    await asyncio.sleep(0)
    await engine.send(session.id, "quero um CRUD")

    assert agent.sent[-1] == "quero um CRUD"
    assert engine.get(session.id).status == AnalysisStatus.WAITING_AGENT


async def test_nonzero_exit_marks_the_session_failed(tmp_path):
    agent = FakeAgentSession(
        [AgentEvent(type=AgentEventType.EXIT, text="1", raw={"exit_code": 1})]
    )
    engine = AnalysisOrchestrator(agent=agent, tracker=AsyncMock())

    session = await engine.start(_project(tmp_path))
    await asyncio.wait_for(agent.release.wait(), timeout=5)
    await asyncio.sleep(0)

    assert session.status == AnalysisStatus.FAILED
    assert session.exit_code == 1


async def test_subscribe_replays_history_for_a_reconnecting_client(tmp_path):
    agent = FakeAgentSession(
        [
            AgentEvent(type=AgentEventType.ASSISTANT, text="primeira"),
            AgentEvent(type=AgentEventType.EXIT, text="0", raw={"exit_code": 0}),
        ]
    )
    engine = AnalysisOrchestrator(agent=agent, tracker=AsyncMock())

    session = await engine.start(_project(tmp_path))
    await asyncio.wait_for(agent.release.wait(), timeout=5)
    await asyncio.sleep(0)

    # Um EventSource que reconecta depois do fim ainda precisa ver a conversa.
    replayed = [e.text async for e in engine.subscribe(session.id)]
    assert replayed == ["primeira", "0"]


async def test_subscribe_after_the_stream_ended_without_an_exit_event_terminates(tmp_path):
    # O status ainda é WAITING_ANALYST: só o fim do pump distingue "acabou" de
    # "esperando". Sem essa marca o gerador de SSE ficaria pendurado.
    agent = FakeAgentSession([AgentEvent(type=AgentEventType.RESULT, text="ok")])
    engine = AnalysisOrchestrator(agent=agent, tracker=AsyncMock())

    session = await engine.start(_project(tmp_path))
    await asyncio.wait_for(agent.release.wait(), timeout=5)
    await asyncio.sleep(0)

    replayed = [e.text async for e in engine.subscribe(session.id)]

    assert replayed == ["ok"]
    assert session.status == AnalysisStatus.WAITING_ANALYST


async def test_deltas_reach_live_viewers_but_never_the_replay_buffer(tmp_path):
    # Milhares por turno: guardá-los estouraria o histórico, e o ASSISTANT
    # canônico logo atrás já carrega o texto inteiro.
    agent = FakeAgentSession(
        [
            AgentEvent(type=AgentEventType.ASSISTANT_DELTA, text="Qual "),
            AgentEvent(type=AgentEventType.ASSISTANT_DELTA, text="o objetivo?"),
            AgentEvent(type=AgentEventType.ASSISTANT, text="Qual o objetivo?"),
            AgentEvent(type=AgentEventType.EXIT, text="0", raw={"exit_code": 0}),
        ]
    )
    engine = AnalysisOrchestrator(agent=agent, tracker=AsyncMock())

    session = await engine.start(_project(tmp_path))
    await asyncio.wait_for(agent.release.wait(), timeout=5)
    await asyncio.sleep(0)

    replayed = [e async for e in engine.subscribe(session.id)]

    assert [e.type for e in replayed] == [AgentEventType.ASSISTANT, AgentEventType.EXIT]
    assert replayed[0].text == "Qual o objetivo?"


async def test_unknown_session_is_rejected(tmp_path):
    engine = AnalysisOrchestrator(agent=FakeAgentSession([]), tracker=AsyncMock())
    with pytest.raises(ValueError):
        engine.get("analysis-nope")


# ---- colheita do backlog ---------------------------------------------------


BACKLOG_DATA = {
    "spec_path": "docs/superpowers/specs/2026-09-20-x-design.md",
    "tasks": [
        {"title": "Modelo", "description": "d1", "target_files": ["a.py"],
         "acceptance_criteria": ["c1"], "dependencies": []},
        {"title": "API", "description": "d2", "target_files": ["b.py"],
         "acceptance_criteria": ["c2"], "dependencies": ["Modelo"]},
    ],
}


def _write_backlog(repo, relative, data=BACKLOG_DATA):
    path = repo.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


async def _harvest_engine(tmp_path):
    tracker = AsyncMock()
    tracker.create_task.side_effect = lambda **kw: Task(id=f"task-{kw['title']}", **kw)
    tracker.update_task_status.side_effect = lambda tid, status: Task(
        id=tid, project_id="p", title="t", description="", status=status
    )
    agent = FakeAgentSession([AgentEvent(type=AgentEventType.EXIT, text="0", raw={"exit_code": 0})])
    engine = AnalysisOrchestrator(agent=agent, tracker=tracker)
    session = await engine.start(_project(tmp_path))
    await asyncio.wait_for(agent.release.wait(), timeout=5)
    return engine, session, tracker


async def test_commit_backlog_creates_tasks_and_resolves_dependencies(tmp_path):
    created = []

    async def create_task(project_id, title, description, target_files, acceptance_criteria, dependencies):
        task = Task(
            id=f"task-{len(created)}",
            project_id=project_id,
            title=title,
            description=description,
            target_files=target_files,
            acceptance_criteria=acceptance_criteria,
            dependencies=dependencies,
        )
        created.append(task)
        return task

    tracker = AsyncMock()
    tracker.create_task.side_effect = create_task
    tracker.update_task_status.side_effect = lambda tid, status: created[0].model_copy(
        update={"status": status}
    )

    agent = FakeAgentSession([AgentEvent(type=AgentEventType.EXIT, text="0", raw={"exit_code": 0})])
    engine = AnalysisOrchestrator(agent=agent, tracker=tracker)
    session = await engine.start(_project(tmp_path))
    await asyncio.wait_for(agent.release.wait(), timeout=5)
    _write_backlog(tmp_path, backlog_relative(session.id))

    tasks = await engine.commit_backlog(session.id)

    assert [t.title for t in tasks] == ["Modelo", "API"]
    # A dependência vem por título e precisa virar o ID que o tracker atribuiu.
    assert created[1].dependencies == ["task-0"]
    assert session.spec_path == "docs/superpowers/specs/2026-09-20-x-design.md"
    assert agent.stopped is True


async def test_commit_backlog_without_the_file_is_a_clear_error(tmp_path):
    agent = FakeAgentSession([AgentEvent(type=AgentEventType.EXIT, text="0", raw={"exit_code": 0})])
    engine = AnalysisOrchestrator(agent=agent, tracker=AsyncMock())
    session = await engine.start(_project(tmp_path))
    await asyncio.wait_for(agent.release.wait(), timeout=5)

    with pytest.raises(FileNotFoundError, match=".painkiller/backlogs/"):
        await engine.commit_backlog(session.id)


async def test_commit_backlog_ignores_another_sessions_file(tmp_path):
    engine, session, tracker = await _harvest_engine(tmp_path)
    _write_backlog(tmp_path, backlog_relative("analysis-outra"))

    with pytest.raises(FileNotFoundError):
        await engine.commit_backlog(session.id)
    tracker.create_task.assert_not_called()


async def test_commit_backlog_rejects_a_legacy_file_older_than_the_session(tmp_path):
    engine, session, tracker = await _harvest_engine(tmp_path)
    legacy = _write_backlog(tmp_path, LEGACY_BACKLOG_RELATIVE)
    # Escrito por uma sessão anterior: antes do início desta análise.
    old = session.created_at.timestamp() - 3600
    os.utime(legacy, (old, old))

    with pytest.raises(FileNotFoundError):
        await engine.commit_backlog(session.id)
    tracker.create_task.assert_not_called()
    assert legacy.exists()


async def test_commit_backlog_adopts_a_fresh_legacy_file_so_it_is_not_reimported(tmp_path):
    engine, session, tracker = await _harvest_engine(tmp_path)
    legacy = _write_backlog(tmp_path, LEGACY_BACKLOG_RELATIVE)

    await engine.commit_backlog(session.id)

    assert tracker.create_task.call_count == 2
    assert not legacy.exists()
    assert tmp_path.joinpath(*backlog_relative(session.id).split("/")).exists()


async def test_start_force_new_stops_previous_active_session(tmp_path):
    agent = FakeAgentSession([AgentEvent(type=AgentEventType.RESULT, text="aguardando")])
    tracker = AsyncMock()
    engine = AnalysisOrchestrator(agent=agent, tracker=tracker)
    proj = _project(tmp_path)
    session1 = await engine.start(proj)
    agent.stopped = False

    session2 = await engine.start(proj, force_new=True)
    assert agent.stopped is True
    assert session2.id != session1.id


# ---- prompt ----------------------------------------------------------------


def test_prompt_carries_project_context_and_the_backlog_contract(tmp_path):
    prompt = build_analysis_prompt(_project(tmp_path))
    assert "superpowers:brainstorming" in prompt
    assert ".painkiller/backlog.json" in prompt
    assert "UMA pergunta por vez" in prompt
    assert "Automatizar" in prompt


def test_prompt_teaches_the_clickable_choices_block(tmp_path):
    prompt = build_analysis_prompt(_project(tmp_path))
    # A UI (web/src/lib/choices.ts) procura exatamente esta cerca.
    assert "```painkiller-choices" in prompt
    assert '"options"' in prompt
    assert '"multiple"' in prompt


async def test_start_resumes_existing_active_session(tmp_path):
    tracker = AsyncMock()
    existing_session = AnalysisSession(
        id="analysis-existing",
        project_id="proj-1",
        status=AnalysisStatus.WAITING_ANALYST,
        claude_session_id="uuid-1234",
    )
    tracker.get_active_analysis_session.return_value = existing_session
    tracker.get_analysis_session.return_value = existing_session
    tracker.list_analysis_events.return_value = []

    agent = FakeAgentSession([AgentEvent(type=AgentEventType.RESULT, text="ok")])
    engine = AnalysisOrchestrator(agent=agent, tracker=tracker)

    project = _project(tmp_path)
    resumed = await engine.start(project, force_new=False)

    assert resumed.id == "analysis-existing"
    assert resumed.claude_session_id == "uuid-1234"


async def test_start_with_force_new_creates_new_session(tmp_path):
    tracker = AsyncMock()
    existing_session = AnalysisSession(
        id="analysis-existing",
        project_id="proj-1",
        status=AnalysisStatus.WAITING_ANALYST,
    )
    tracker.get_active_analysis_session.return_value = existing_session

    agent = FakeAgentSession([AgentEvent(type=AgentEventType.RESULT, text="ok")])
    engine = AnalysisOrchestrator(agent=agent, tracker=tracker)

    project = _project(tmp_path)
    session = await engine.start(project, force_new=True)

    assert session.id != "analysis-existing"
    assert session.claude_session_id is not None



# ---- versionamento de docs/ ------------------------------------------------


async def test_each_finished_turn_commits_and_pushes_docs(tmp_path):
    git = AsyncMock()
    git.commit_paths.return_value = "abc123"
    git.current_branch.return_value = "main"
    git.push.return_value = (0, "")
    git.switch_branch.return_value = (0, "")

    agent = FakeAgentSession([AgentEvent(type=AgentEventType.RESULT, text="ok")])
    engine = AnalysisOrchestrator(agent=agent, tracker=AsyncMock(), git=git)
    await engine.start(_project(tmp_path))
    await asyncio.wait_for(agent.release.wait(), timeout=5)
    await asyncio.sleep(0)

    git.commit_paths.assert_awaited_once()
    assert git.commit_paths.await_args.args[1] == ["docs"]
    git.push.assert_awaited_once_with(str(tmp_path), "main")


async def test_docs_sync_failure_does_not_break_the_session(tmp_path):
    git = AsyncMock()
    git.commit_paths.side_effect = RuntimeError("sem git")
    git.switch_branch.return_value = (0, "")

    agent = FakeAgentSession([AgentEvent(type=AgentEventType.RESULT, text="ok")])
    engine = AnalysisOrchestrator(agent=agent, tracker=AsyncMock(), git=git)
    session = await engine.start(_project(tmp_path))
    await asyncio.wait_for(agent.release.wait(), timeout=5)
    await asyncio.sleep(0)

    assert session.status == AnalysisStatus.WAITING_ANALYST
    git.push.assert_not_awaited()


async def test_new_analysis_switches_to_the_default_branch_first(tmp_path):
    git = AsyncMock()
    git.switch_branch.return_value = (0, "")
    git.current_branch.return_value = "main"
    git.push.return_value = (0, "")

    agent = FakeAgentSession([AgentEvent(type=AgentEventType.RESULT, text="ok")])
    engine = AnalysisOrchestrator(agent=agent, tracker=AsyncMock(), git=git)
    await engine.start(_project(tmp_path), force_new=True)

    git.switch_branch.assert_awaited_once_with(str(tmp_path), "main")


async def test_refused_branch_switch_does_not_block_the_analysis(tmp_path):
    git = AsyncMock()
    git.switch_branch.return_value = (1, "alteracoes pendentes")
    git.current_branch.return_value = "feature/t1"
    git.push.return_value = (0, "")

    agent = FakeAgentSession([AgentEvent(type=AgentEventType.RESULT, text="ok")])
    engine = AnalysisOrchestrator(agent=agent, tracker=AsyncMock(), git=git)
    session = await engine.start(_project(tmp_path), force_new=True)
    await asyncio.wait_for(agent.release.wait(), timeout=5)
    await asyncio.sleep(0)

    assert session.container_name == "pk-analysis-fake"
    git.push.assert_awaited_once_with(str(tmp_path), "feature/t1")
