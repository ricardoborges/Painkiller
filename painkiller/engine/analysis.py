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
    UsageRecord,
    UsageSource,
    IterationSession,
    SessionStatus,
)
from painkiller.core.ports.agent_session import AgentSessionPort
from painkiller.core.ports.issue_tracker import IssueTrackerPort
from painkiller.core.ports.usage_ledger import UsageLedgerPort
from painkiller.core.usage import parse_agent_usage
from painkiller.core.attachment_reader import extract_attachment_text

#: Onde o agente deposita o backlog decomposto, lido de volta pela API através
#: do bind mount assim que o analista aprova a especificação.
BACKLOG_RELATIVE = ".painkiller/backlog.json"

#: Linguagem do bloco cercado que a UI troca por opções clicáveis. O mesmo nome
#: está em web/src/lib/choices.ts — mudar aqui exige mudar lá.
CHOICES_FENCE = "painkiller-choices"

#: Quantos eventos ficam guardados para replay quando o EventSource reconecta.
REPLAY_LIMIT = 500

#: Pedaços de texto em andamento: vão ao vivo para quem está assistindo, mas
#: nunca ao histórico — são milhares por turno, e o ASSISTANT canônico que vem
#: logo depois já carrega o texto inteiro. Quem reconecta vê a conversa, não a
#: digitação.
TRANSIENT_EVENTS = frozenset(
    {AgentEventType.ASSISTANT_DELTA, AgentEventType.THINKING_DELTA}
)

#: Eventos que fecham a fala do agente. Em qualquer um deles o turno montado a
#: partir dos deltas precisa ser resolvido: ou o canônico já traz o texto, ou
#: sintetizamos um ASSISTANT com o que foi acumulado. Sem isto, um agente que
#: não emite o canônico deixa a conversa em branco para quem reconecta.
TURN_ENDERS = frozenset(
    {AgentEventType.ASSISTANT, AgentEventType.RESULT, AgentEventType.TOOL_USE}
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
        # Texto do turno em voo, montado a partir dos deltas. Os deltas não vão
        # ao histórico (são milhares), mas o texto que eles formam precisa
        # sobreviver a uma reconexão no meio do turno.
        self.partial = ""
        # Quantos eventos não-transitórios já estão gravados no banco. Ao
        # religar o pump relemos o log inteiro do contêiner, então estes
        # primeiros eventos são reconstruídos em memória mas não regravados.
        self.persisted = 0
        # Modelo anunciado no evento de init; o RESULT nem sempre o repete.
        self.model = os.environ.get("PAINKILLER_AGENT_MODEL", "")


class AnalysisOrchestrator:
    """Starts, feeds and harvests interactive analysis sessions.

    `self.runs` é só cache: sessão e eventos vão para o tracker, e
    `get_or_restore` remonta um run a partir do banco. Um restart do uvicorn
    portanto não perde a conversa — se o contêiner sobreviveu, o pump é religado
    e relê o log (ver `_rewind`); se não, o histórico persistido ainda responde.
    """

    def __init__(
        self,
        agent: AgentSessionPort,
        tracker: IssueTrackerPort,
        usage: Optional[UsageLedgerPort] = None,
    ):
        self.agent = agent
        self.tracker = tracker
        self.usage = usage
        self.runs: dict[str, AnalysisRun] = {}

    # ---- ciclo de vida -------------------------------------------------

    async def start(
        self,
        project: Project,
        force_new: bool = False,
        iteration_session_id: Optional[str] = None,
    ) -> AnalysisSession:
        if not force_new:
            active = await self.get_active(project.id)
            if isinstance(active, AnalysisSession):
                run = self.runs.get(active.id)
                if run and await self.agent.is_alive(active.id):
                    return active
                return await self.resume(project, active.id)

        session_id = f"analysis-{uuid.uuid4().hex[:8]}"
        claude_session_id = str(uuid.uuid4())
        session = AnalysisSession(
            id=session_id,
            project_id=project.id,
            claude_session_id=claude_session_id,
            status=AnalysisStatus.STARTING,
        )
        run = AnalysisRun(session=session, repo_path=project.repo_path)
        self.runs[session_id] = run
        try:
            await self.tracker.save_analysis_session(session)
        except Exception:
            pass

        session_number = 1
        previous_sessions: list[IterationSession] = []
        previous_completed_tasks: list[Task] = []
        if iteration_session_id:
            try:
                iter_sess = await self.tracker.get_session(iteration_session_id)
                if iter_sess:
                    num = getattr(iter_sess, "number", 1)
                    session_number = num if isinstance(num, int) else 1
                    iter_sess.analysis_session_id = session.id
                    await self.tracker.update_session(iter_sess)
                    all_sessions = await self.tracker.list_sessions(project.id)
                    if isinstance(all_sessions, (list, tuple)):
                        previous_sessions = [s for s in all_sessions if getattr(s, "number", 0) < session_number]
                    all_tasks = await self.tracker.list_tasks(project.id, status=TaskStatus.COMPLETED)
                    if isinstance(all_tasks, (list, tuple)):
                        previous_completed_tasks = list(all_tasks)
            except Exception:
                pass
        else:
            try:
                iter_sess = await self.tracker.ensure_initial_session(project.id)
                if iter_sess:
                    iteration_session_id = getattr(iter_sess, "id", None)
                    num = getattr(iter_sess, "number", 1)
                    session_number = num if isinstance(num, int) else 1
                    if hasattr(iter_sess, "analysis_session_id"):
                        iter_sess.analysis_session_id = session.id
                        await self.tracker.update_session(iter_sess)
            except Exception:
                pass

        prompt = build_analysis_prompt(
            project,
            session_number=session_number,
            previous_sessions=previous_sessions,
            previous_completed_tasks=previous_completed_tasks,
        )
        try:
            session.container_name = await self.agent.start(
                session_id=session_id,
                repo_path=project.repo_path,
                prompt=prompt,
                resume=False,
                claude_session_id=claude_session_id,
            )
        except Exception as e:
            session.status = AnalysisStatus.FAILED
            session.error = str(e)
            try:
                await self.tracker.save_analysis_session(session)
            except Exception:
                pass
            raise

        session.status = AnalysisStatus.WAITING_AGENT
        try:
            await self.tracker.save_analysis_session(session)
        except Exception:
            pass
        run.pump = asyncio.create_task(self._pump(run))
        return session

    async def resume(self, project: Project, session_id: str) -> AnalysisSession:
        session = await self.tracker.get_analysis_session(session_id)
        if not isinstance(session, AnalysisSession):
            run = self.runs.get(session_id)
            if run:
                session = run.session
            else:
                raise ValueError(f"Sessão {session_id} não encontrada")

        run = self.runs.get(session_id)
        if not run:
            run = AnalysisRun(session=session, repo_path=project.repo_path)
            events = await self.tracker.list_analysis_events(session_id)
            run.events = list(events) if isinstance(events, (list, tuple)) else []
            self.runs[session_id] = run

        alive = await self.agent.is_alive(session_id)
        if not alive:
            try:
                session.container_name = await self.agent.start(
                    session_id=session_id,
                    repo_path=project.repo_path,
                    prompt="",
                    resume=True,
                    claude_session_id=session.claude_session_id,
                )
                session.status = AnalysisStatus.WAITING_ANALYST
                await self.tracker.save_analysis_session(session)
            except Exception as e:
                session.status = AnalysisStatus.FAILED
                session.error = str(e)
                try:
                    await self.tracker.save_analysis_session(session)
                except Exception:
                    pass
                raise

        if hasattr(self.agent, "register_stdin_file"):
            self.agent.register_stdin_file(session_id, project.repo_path)

        if not run.pump or run.pump.done():
            run.done = False
            if alive:
                self._rewind(run)
            run.pump = asyncio.create_task(self._pump(run))

        return session

    async def _pump(self, run: AnalysisRun) -> None:
        """Drain the adapter's event stream and fan it out to SSE subscribers."""
        # O log do contêiner é relido do início a cada religada do pump, então
        # os primeiros `skip` eventos já estão no banco: reconstruímos o replay
        # em memória sem duplicá-los no histórico persistido.
        skip = run.persisted
        run.persisted = 0

        async def emit(event: AgentEvent) -> None:
            nonlocal skip
            self._apply_status(run, event)
            if event.type not in TRANSIENT_EVENTS:
                run.events.append(event)
                del run.events[:-REPLAY_LIMIT]
                if skip > 0:
                    skip -= 1
                else:
                    try:
                        await self.tracker.save_analysis_event(run.session.id, event)
                    except Exception:
                        pass
                    # Mesmo critério do histórico: um turno relido após
                    # `_rewind` já foi contabilizado na primeira passagem.
                    if event.type == AgentEventType.RESULT:
                        await self._record_usage(run, event)
            for queue in list(run.subscribers):
                queue.put_nowait(event)
            try:
                await self.tracker.save_analysis_session(run.session)
            except Exception:
                pass

        try:
            async for event in self.agent.stream(run.session.id):
                if event.type == AgentEventType.ASSISTANT_DELTA:
                    run.partial += event.text
                elif event.type in TURN_ENDERS:
                    salvaged = self._salvage(run, event)
                    run.partial = ""
                    if salvaged is not None:
                        await emit(salvaged)
                await emit(event)
        except Exception as e:
            run.session.status = AnalysisStatus.FAILED
            run.session.error = str(e)
            try:
                await self.tracker.save_analysis_session(run.session)
            except Exception:
                pass
            failure = AgentEvent(type=AgentEventType.ERROR, text=str(e))
            run.events.append(failure)
            for queue in list(run.subscribers):
                queue.put_nowait(failure)
        finally:
            run.done = True
            try:
                await self.tracker.save_analysis_session(run.session)
            except Exception:
                pass
            # None fecha os geradores de SSE que ainda estiverem pendurados.
            for queue in list(run.subscribers):
                queue.put_nowait(None)

    async def _record_usage(self, run: AnalysisRun, event: AgentEvent) -> None:
        if self.usage is None:
            return
        parsed = parse_agent_usage(event.raw)
        if parsed is None:
            return
        input_tokens, output_tokens, cost, model = parsed
        try:
            await self.usage.record_usage(
                UsageRecord(
                    source=UsageSource.ANALYSIS,
                    model=model or run.model,
                    project_id=run.session.project_id,
                    session_id=run.session.id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    reported_cost_usd=cost,
                )
            )
        except Exception:
            pass

    @staticmethod
    def _rewind(run: AnalysisRun) -> None:
        """Prepare a run whose pump is about to reread the same container log.

        `container.logs(follow=True)` sempre começa do zero, então o replay
        reconstrói em memória o que já está no banco; marcamos quantos eventos
        pular na hora de gravar. Só vale quando o contêiner sobreviveu — um
        contêiner novo tem log novo.
        """
        run.persisted = len(run.events)
        run.events = []
        run.partial = ""

    @staticmethod
    def _salvage(run: AnalysisRun, event: AgentEvent) -> Optional[AgentEvent]:
        """Turn an unclosed delta stream into a canonical ASSISTANT, if needed."""
        text = run.partial.strip()
        if not text:
            return None
        # TOOL_USE traz o nome da ferramenta, nunca a fala: o que o agente disse
        # antes de chamá-la só existe no que acumulamos.
        if event.type is not AgentEventType.TOOL_USE and (event.text or "").strip():
            return None
        return AgentEvent(type=AgentEventType.ASSISTANT, text=text)

    @staticmethod
    def _apply_status(run: AnalysisRun, event: AgentEvent) -> None:
        if event.type == AgentEventType.SYSTEM:
            init = event.raw.get("init") if isinstance(event.raw.get("init"), dict) else {}
            model = init.get("model") or event.raw.get("model")
            if model:
                run.model = str(model)
        elif event.type == AgentEventType.RESULT:
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
        user_event = AgentEvent(type=AgentEventType.USER, text=text)
        try:
            await self.tracker.save_analysis_event(session_id, user_event)
        except Exception:
            pass
        await self.agent.send(session_id, text)
        run.session.status = AnalysisStatus.WAITING_AGENT
        try:
            await self.tracker.save_analysis_session(run.session)
        except Exception:
            pass
        return run.session

    async def finish(self, session_id: str) -> AnalysisSession:
        """Close the agent's stdin so it wraps up and exits."""
        run = self._require(session_id)
        await self.agent.close_input(session_id)
        return run.session

    async def stop(self, session_id: str) -> None:
        run = self.runs.pop(session_id, None)
        if run and run.pump:
            run.pump.cancel()
        await self.agent.stop(session_id)
        session = await self.tracker.get_analysis_session(session_id)
        if session:
            session.status = AnalysisStatus.FINISHED
            try:
                await self.tracker.save_analysis_session(session)
            except Exception:
                pass

    def get(self, session_id: str) -> AnalysisSession:
        return self._require(session_id).session

    async def get_or_restore(self, session_id: str) -> AnalysisSession:
        run = self.runs.get(session_id)
        if run:
            return run.session
        session = await self.tracker.get_analysis_session(session_id)
        if not isinstance(session, AnalysisSession):
            raise ValueError(f"Sessão {session_id} não encontrada")
        project = await self.tracker.get_project(session.project_id)
        repo_path = project.repo_path if isinstance(project, Project) else ""
        run = AnalysisRun(session=session, repo_path=repo_path)
        events = await self.tracker.list_analysis_events(session_id)
        run.events = list(events) if isinstance(events, (list, tuple)) else []
        self.runs[session_id] = run
        if hasattr(self.agent, "register_stdin_file") and repo_path:
            self.agent.register_stdin_file(session_id, repo_path)
        alive = await self.agent.is_alive(session_id)
        if alive and (not run.pump or run.pump.done()):
            run.done = False
            self._rewind(run)
            run.pump = asyncio.create_task(self._pump(run))
        return session

    async def get_active(self, project_id: str) -> Optional[AnalysisSession]:
        for run in self.runs.values():
            if run.session.project_id == project_id and run.session.status not in (
                AnalysisStatus.FINISHED,
                AnalysisStatus.FAILED,
            ):
                return run.session
        active = await self.tracker.get_active_analysis_session(project_id)
        if isinstance(active, AnalysisSession):
            return active
        return None

    def _require(self, session_id: str) -> AnalysisRun:
        run = self.runs.get(session_id)
        if not run:
            raise ValueError(f"Sessão {session_id} não encontrada")
        return run

    # ---- streaming -----------------------------------------------------

    async def subscribe(self, session_id: str) -> AsyncIterator[AgentEvent]:
        """Replay what already happened, then follow the session live."""
        run = self.runs.get(session_id)
        if not run:
            await self.get_or_restore(session_id)
            run = self._require(session_id)
        queue: asyncio.Queue = asyncio.Queue()
        backlog = list(run.events)
        run.subscribers.add(queue)
        try:
            for event in backlog:
                yield event
            # Quem chega no meio de um turno recebe o que já foi dito como um
            # delta único, em vez de olhar para um vazio até o agente falar de novo.
            if run.partial:
                yield AgentEvent(type=AgentEventType.ASSISTANT_DELTA, text=run.partial)
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

    async def commit_backlog(
        self,
        session_id: str,
        iteration_session_id: Optional[str] = None,
    ) -> list[Task]:
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

        target_session_id = iteration_session_id
        if not target_session_id:
            try:
                all_sessions = await self.tracker.list_sessions(run.session.project_id)
                if isinstance(all_sessions, (list, tuple)):
                    for s in all_sessions:
                        if getattr(s, "analysis_session_id", None) == session_id:
                            target_session_id = s.id
                            break
                    if not target_session_id and all_sessions:
                        target_session_id = all_sessions[-1].id
            except Exception:
                pass

        drafts = data.get("tasks") or []
        created: list[Task] = []
        title_to_id: dict[str, str] = {}

        for draft in drafts:
            # Dependências vêm por título, porque o agente não conhece os IDs
            # que o tracker só atribui na criação.
            resolved = [title_to_id[d] for d in draft.get("dependencies", []) if d in title_to_id]
            task_kwargs = {
                "project_id": run.session.project_id,
                "title": draft.get("title", "Sem título"),
                "description": draft.get("description", ""),
                "target_files": draft.get("target_files", []),
                "acceptance_criteria": draft.get("acceptance_criteria", []),
                "dependencies": resolved,
            }
            if target_session_id:
                task_kwargs["session_id"] = target_session_id
            try:
                task = await self.tracker.create_task(**task_kwargs)
            except TypeError:
                task_kwargs.pop("session_id", None)
                task = await self.tracker.create_task(**task_kwargs)
            title_to_id[task.title] = task.id
            created.append(task)

        if created:
            created[0] = await self.tracker.update_task_status(created[0].id, TaskStatus.READY)

        run.session.spec_path = data.get("spec_path")
        run.session.status = AnalysisStatus.FINISHED
        try:
            await self.tracker.save_analysis_session(run.session)
        except Exception:
            pass

        if target_session_id:
            try:
                iter_sess = await self.tracker.get_session(target_session_id)
                if iter_sess:
                    iter_sess.spec_path = data.get("spec_path")
                    iter_sess.status = SessionStatus.BACKLOG
                    await self.tracker.update_session(iter_sess)
            except Exception:
                pass

        return created


def build_analysis_prompt(
    project: Project,
    session_number: int = 1,
    previous_sessions: Optional[list[IterationSession]] = None,
    previous_completed_tasks: Optional[list[Task]] = None,
) -> str:
    """Compose the pt-BR kickoff prompt handed to the containerized agent."""
    parts = [
        "Você é o agente de análise do Painkiller.",
        "",
        "Conduza a elicitação de requisitos com o analista usando a skill "
        "superpowers:brainstorming. Regras desta sessão:",
        "- Escreva sempre em português do Brasil.",
        "- Faça UMA pergunta por vez e espere a resposta do analista.",
        "- Não escreva código de produção nem implemente nada nesta sessão.",
        "- O repositório do projeto está montado em /workspace.",
        "",
        "Quando a pergunta tiver alternativas, a plataforma as mostra como opções "
        "clicáveis. Para isso, escreva a pergunta normalmente e termine a mensagem "
        f"com um único bloco de código `{CHOICES_FENCE}` contendo JSON, sem repetir "
        "as alternativas no texto:",
        f"```{CHOICES_FENCE}",
        '{"multiple": false, "options": [',
        '  {"label": "Rótulo curto", "description": "detalhe opcional"}',
        "]}",
        "```",
        "Use \"multiple\": true só quando fizer sentido marcar mais de uma. "
        "Não inclua uma opção \"Outro\": o analista sempre pode responder livremente.",
        "",
        "Quando o analista aprovar a especificação, faça as seguintes coisas:",
        "1. Grave a especificação em docs/superpowers/specs/AAAA-MM-DD-<tema>-design.md.",
        f"2. Grave o backlog decomposto em {BACKLOG_RELATIVE}, exatamente neste formato:",
        '   {"spec_path": "<caminho do spec>", "tasks": [',
        '     {"title": "...", "description": "...", "target_files": ["..."],',
        '      "acceptance_criteria": ["..."], "dependencies": ["<title de outra task>"]}',
        "   ]}",
        "   Cada tarefa precisa ser atômica e executável por um agente de codificação isolado.",
        "3. Na mensagem final confirmando a gravação do backlog, liste resumidamente as tarefas e termine OBRIGATORIAMENTE com o bloco de alternativas para o analista seguir:",
        f"```{CHOICES_FENCE}",
        '{"multiple": false, "options": [',
        '  {"label": "Seguir para backlog", "description": "Importar as tarefas decompostas e abrir o painel de backlog"}',
        "]}",
        "```",
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

    if isinstance(session_number, int) and session_number > 1:
        parts.append("")
        parts.append(f"=== CICLO ÁGIL ITERATIVO: SESSÃO {session_number} ===")
        parts.append(
            f"Esta é a iteração/sessão de número {session_number} deste projeto. "
            "O software já possui entregas anteriores consolidadas no repositório. "
            "Seu objetivo nesta sessão é elicitar os novos requisitos, melhorias ou "
            "próximas funcionalidades a serem construídas neste ciclo."
        )
        if previous_sessions:
            parts.append("\nHistórico de sessões anteriores:")
            for ps in previous_sessions:
                spec_note = f" (spec: {ps.spec_path})" if ps.spec_path else ""
                parts.append(f"- {ps.title}: status {ps.status.value}{spec_note}")
        if previous_completed_tasks:
            parts.append("\nTarefas concluídas com sucesso em ciclos anteriores:")
            for pt in previous_completed_tasks:
                parts.append(f"- [{pt.id}] {pt.title}: {pt.description}")

    parts.append("")
    parts.append("Comece cumprimentando o analista e fazendo a primeira pergunta.")
    return "\n".join(parts)
