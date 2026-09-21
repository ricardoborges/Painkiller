"""Live activity of task dispatches, fanned out to SSE subscribers.

A dispatch holds its HTTP request open for the whole container run, so without
this the analyst cannot tell a working agent from a stuck one. The hub is
in-memory on purpose: it only describes runs happening in this process. After
a restart a task may still read RUNNING in the tracker while nothing here knows
about it, and the stream says exactly that instead of pretending.
"""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from painkiller.core.domain.models import AgentEvent, AgentEventType

# Deltas chegam aos milhares; vão ao vivo para os inscritos, mas não ao buffer
# de replay — quem reconecta recebe o texto parcial acumulado em um só evento.
TRANSIENT_EVENTS = frozenset(
    {AgentEventType.ASSISTANT_DELTA, AgentEventType.THINKING_DELTA}
)

# Limite do replay: o card mostra só as últimas linhas, e um agente falante
# não deve crescer a memória sem fim.
BUFFER_SIZE = 300


@dataclass
class TaskRun:
    task_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_event_at: Optional[datetime] = None
    events: deque = field(default_factory=lambda: deque(maxlen=BUFFER_SIZE))
    partial: str = ""
    done: bool = False
    subscribers: list[asyncio.Queue] = field(default_factory=list)


class TaskActivityHub:
    """Keeps the recent events of each running task and streams them."""

    def __init__(self) -> None:
        self.runs: dict[str, TaskRun] = {}

    def start(self, task_id: str) -> TaskRun:
        """Open a fresh run, dropping whatever a previous dispatch left."""
        run = TaskRun(task_id=task_id)
        self.runs[task_id] = run
        return run

    def publish(self, task_id: str, event: AgentEvent) -> None:
        """Record an event and push it to subscribers. Must run on the event loop."""
        run = self.runs.get(task_id)
        if run is None or run.done:
            return
        run.last_event_at = event.timestamp
        if event.type == AgentEventType.ASSISTANT_DELTA:
            run.partial += event.text
        elif event.type in (AgentEventType.ASSISTANT, AgentEventType.RESULT):
            run.partial = ""
        if event.type not in TRANSIENT_EVENTS:
            run.events.append(event)
        for queue in run.subscribers:
            queue.put_nowait(event)

    def publisher(self, task_id: str, loop: asyncio.AbstractEventLoop):
        """A thread-safe callback for the sandbox, which reports from an executor."""

        def forward(event: AgentEvent) -> None:
            try:
                on_loop = asyncio.get_running_loop() is loop
            except RuntimeError:
                on_loop = False
            if on_loop:
                self.publish(task_id, event)
            else:
                loop.call_soon_threadsafe(self.publish, task_id, event)

        return forward

    def finish(self, task_id: str) -> None:
        run = self.runs.get(task_id)
        if run is None:
            return
        run.done = True
        run.partial = ""
        for queue in run.subscribers:
            queue.put_nowait(None)
        run.subscribers = []

    def get(self, task_id: str) -> Optional[TaskRun]:
        return self.runs.get(task_id)

    async def subscribe(self, task_id: str) -> AsyncIterator[AgentEvent]:
        """Replay the buffer, then follow until the run finishes."""
        run = self.runs.get(task_id)
        if run is None:
            return
        # Foto do replay e inscrição no mesmo passo, sem await no meio: o que
        # for publicado enquanto o replay é consumido cai na fila, não se perde.
        replay = list(run.events)
        partial = run.partial
        queue: Optional[asyncio.Queue] = None
        if not run.done:
            queue = asyncio.Queue()
            run.subscribers.append(queue)
        try:
            for event in replay:
                yield event
            if partial:
                yield AgentEvent(type=AgentEventType.ASSISTANT_DELTA, text=partial)
            if queue is None:
                return
            while True:
                event = await queue.get()
                if event is None:
                    return
                yield event
        finally:
            current = self.runs.get(task_id)
            if current is not None and queue in current.subscribers:
                current.subscribers.remove(queue)
