"""Initial-analysis engine: drives a live brainstorming session with the analyst."""

import asyncio
import json
import os
import uuid
from typing import AsyncIterator, Optional

from painkiller.core.domain.models import (
    AgentEvent,
    AgentEventType,
    AnalysisSession,
    AnalysisStatus,
    Project,
    Task,
    TaskStatus,
)
from painkiller.core.ports.agent_session import AgentSessionPort
from painkiller.core.ports.issue_tracker import IssueTrackerPort
from painkiller.core.attachment_reader import extract_attachment_text

#: Onde o agente deposita o backlog decomposto, lido de volta pela API através
#: do bind mount assim que o analista aprova a especificação.
BACKLOG_RELATIVE = ".painkiller/backlog.json"

#: Quantos eventos ficam guardados para replay quando o EventSource reconecta.
REPLAY_LIMIT = 500

#: Pedaços de texto em andamento: vão ao vivo para quem está assistindo, mas
#: nunca ao histórico — são milhares por turno, e o ASSISTANT canônico que vem
#: logo depois já carrega o texto inteiro. Quem reconecta vê a conversa, não a
#: digitação.
TRANSIENT_EVENTS = frozenset(
    {AgentEventType.ASSISTANT_DELTA, AgentEventType.THINKING_DELTA}
)


class AnalysisRun:
    """In-process bookkeeping for one live session."""

    def __init__(self, session: AnalysisSession, repo_path: str):
        self.session = session
        self.repo_path = repo_path
        self.events: list[AgentEvent] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.pump: Optional[asyncio.Task] = None
        # Marcado quando o stream do agente se esgota. Sem isto, um cliente que
        # assina depois do fim esperaria para sempre por um evento que não vem
        # — o pump já publicou seu None antes de a fila dele existir.
        self.done = False


class AnalysisOrchestrator:
    """Starts, feeds and harvests interactive analysis sessions.

    Sessions live in an in-process dict, like InterrogationWizard: a uvicorn
    restart loses them (and orphans the container, which `stop` would have
    removed). Moving this to the tracker is the natural next step.
    """

    def __init__(self, agent: AgentSessionPort, tracker: IssueTrackerPort):
        self.agent = agent
        self.tracker = tracker
        self.runs: dict[str, AnalysisRun] = {}

    # ---- ciclo de vida -------------------------------------------------

    async def start(self, project: Project) -> AnalysisSession:
        session_id = f"analysis-{uuid.uuid4().hex[:8]}"
        session = AnalysisSession(id=session_id, project_id=project.id)
        run = AnalysisRun(session=session, repo_path=project.repo_path)
        self.runs[session_id] = run

        prompt = build_analysis_prompt(project)
        try:
            session.container_name = await self.agent.start(
                session_id=session_id,
                repo_path=project.repo_path,
                prompt=prompt,
            )
        except Exception as e:
            session.status = AnalysisStatus.FAILED
            session.error = str(e)
            raise

        session.status = AnalysisStatus.WAITING_AGENT
        run.pump = asyncio.create_task(self._pump(run))
        return session

    async def _pump(self, run: AnalysisRun) -> None:
        """Drain the adapter's event stream and fan it out to SSE subscribers."""
        try:
            async for event in self.agent.stream(run.session.id):
                self._apply_status(run, event)
                if event.type not in TRANSIENT_EVENTS:
                    run.events.append(event)
                    del run.events[:-REPLAY_LIMIT]
                for queue in list(run.subscribers):
                    queue.put_nowait(event)
        except Exception as e:
            run.session.status = AnalysisStatus.FAILED
            run.session.error = str(e)
            failure = AgentEvent(type=AgentEventType.ERROR, text=str(e))
            run.events.append(failure)
            for queue in list(run.subscribers):
                queue.put_nowait(failure)
        finally:
            run.done = True
            # None fecha os geradores de SSE que ainda estiverem pendurados.
            for queue in list(run.subscribers):
                queue.put_nowait(None)

    @staticmethod
    def _apply_status(run: AnalysisRun, event: AgentEvent) -> None:
        if event.type == AgentEventType.RESULT:
            # O agente terminou o turno: a bola volta para o analista.
            run.session.status = AnalysisStatus.WAITING_ANALYST
        elif event.type == AgentEventType.EXIT:
            code = event.raw.get("exit_code", 1)
            run.session.exit_code = code
            run.session.status = (
                AnalysisStatus.FINISHED if code == 0 else AnalysisStatus.FAILED
            )

    async def send(self, session_id: str, text: str) -> AnalysisSession:
        run = self._require(session_id)
        await self.agent.send(session_id, text)
        run.session.status = AnalysisStatus.WAITING_AGENT
        return run.session

    async def finish(self, session_id: str) -> AnalysisSession:
        """Close the agent's stdin so it wraps up and exits."""
        run = self._require(session_id)
        await self.agent.close_input(session_id)
        return run.session

    async def stop(self, session_id: str) -> None:
        run = self.runs.pop(session_id, None)
        if not run:
            return
        if run.pump:
            run.pump.cancel()
        await self.agent.stop(session_id)

    def get(self, session_id: str) -> AnalysisSession:
        return self._require(session_id).session

    def _require(self, session_id: str) -> AnalysisRun:
        run = self.runs.get(session_id)
        if not run:
            raise ValueError(f"Sessão {session_id} não encontrada")
        return run

    # ---- streaming -----------------------------------------------------

    async def subscribe(self, session_id: str) -> AsyncIterator[AgentEvent]:
        """Replay what already happened, then follow the session live."""
        run = self._require(session_id)
        queue: asyncio.Queue = asyncio.Queue()
        backlog = list(run.events)
        run.subscribers.add(queue)
        try:
            for event in backlog:
                yield event
            # O pump já se esgotou: nada mais será publicado nesta fila.
            if run.done:
                return
            while True:
                event = await queue.get()
                if event is None:
                    return
                yield event
        finally:
            run.subscribers.discard(queue)

    # ---- colheita ------------------------------------------------------

    async def commit_backlog(self, session_id: str) -> list[Task]:
        """Turn the backlog.json the agent wrote into real tasks."""
        run = self._require(session_id)
        path = os.path.join(run.repo_path, ".painkiller", "backlog.json")
        if not os.path.exists(path):
            raise FileNotFoundError(
                "O agente ainda não gravou .painkiller/backlog.json. Conclua a análise e peça "
                "a ele para registrar o backlog antes de importar."
            )

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        drafts = data.get("tasks") or []
        created: list[Task] = []
        title_to_id: dict[str, str] = {}

        for draft in drafts:
            # Dependências vêm por título, porque o agente não conhece os IDs
            # que o tracker só atribui na criação.
            resolved = [title_to_id[d] for d in draft.get("dependencies", []) if d in title_to_id]
            task = await self.tracker.create_task(
                project_id=run.session.project_id,
                title=draft.get("title", "Sem título"),
                description=draft.get("description", ""),
                target_files=draft.get("target_files", []),
                acceptance_criteria=draft.get("acceptance_criteria", []),
                dependencies=resolved,
            )
            title_to_id[task.title] = task.id
            created.append(task)

        if created:
            created[0] = await self.tracker.update_task_status(created[0].id, TaskStatus.READY)

        run.session.spec_path = data.get("spec_path")
        return created


def build_analysis_prompt(project: Project) -> str:
    """Compose the pt-BR kickoff prompt handed to the containerized agent."""
    parts = [
        "Você é o agente de análise inicial do Painkiller.",
        "",
        "Conduza a elicitação de requisitos com o analista usando a skill "
        "superpowers:brainstorming. Regras desta sessão:",
        "- Escreva sempre em português do Brasil.",
        "- Faça UMA pergunta por vez e espere a resposta do analista.",
        "- Não escreva código de produção nem implemente nada nesta sessão.",
        "- O repositório do projeto está montado em /workspace.",
        "",
        "Quando o analista aprovar a especificação, faça as duas coisas:",
        "1. Grave a especificação em docs/superpowers/specs/AAAA-MM-DD-<tema>-design.md.",
        f"2. Grave o backlog decomposto em {BACKLOG_RELATIVE}, exatamente neste formato:",
        '   {"spec_path": "<caminho do spec>", "tasks": [',
        '     {"title": "...", "description": "...", "target_files": ["..."],',
        '      "acceptance_criteria": ["..."], "dependencies": ["<title de outra task>"]}',
        "   ]}",
        "   Cada tarefa precisa ser atômica e executável por um agente de codificação isolado.",
        "",
        "=== CONTEXTO DO PROJETO ===",
        f"Nome: {project.name}",
        f"Descrição geral: {project.description}",
        f"Propósito de negócio: {project.purpose}",
        f"Solução desejada: {project.solution_description}",
    ]

    if project.attachments:
        parts.append("")
        parts.append("=== DOCUMENTOS DE CONTEXTO ANEXADOS ===")
        for att_path in project.attachments:
            parts.append(extract_attachment_text(att_path))

    parts.append("")
    parts.append("Comece cumprimentando o analista e fazendo a primeira pergunta.")
    return "\n".join(parts)
