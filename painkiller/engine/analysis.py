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
    DeploymentInfo,
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

    async def start(self, project: Project, force_new: bool = False) -> AnalysisSession:
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

        prompt = build_analysis_prompt(project)
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
                    try:
                        await self.tracker.save_analysis_event(run.session.id, event)
                    except Exception:
                        pass
                for queue in list(run.subscribers):
                    queue.put_nowait(event)
                try:
                    await self.tracker.save_analysis_session(run.session)
                except Exception:
                    pass
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

        # Como a aplicação sobe em produção também sai da análise: porta e
        # forma de build vão para o projeto, para o adaptador de deploy usar.
        deploy = data.get("deploy")
        if isinstance(deploy, dict):
            try:
                project = await self.tracker.get_project(run.session.project_id)
                base = project.deployment if isinstance(project, Project) and project.deployment else DeploymentInfo()
                info = base.model_copy(update=_deployment_updates(deploy))
                await self.tracker.update_project(run.session.project_id, deployment=info)
            except Exception:
                pass

        run.session.spec_path = data.get("spec_path")
        run.session.status = AnalysisStatus.FINISHED
        try:
            await self.tracker.save_analysis_session(run.session)
        except Exception:
            pass
        return created


def _deployment_updates(deploy: dict) -> dict:
    """Sanitize the `deploy` block the agent wrote into DeploymentInfo fields."""
    updates: dict = {}
    port = deploy.get("port")
    if isinstance(port, int) and 1 <= port <= 65535:
        updates["port"] = port
    elif isinstance(port, str) and port.isdigit() and 1 <= int(port) <= 65535:
        updates["port"] = int(port)
    build_pack = str(deploy.get("build_pack") or "").strip().lower()
    if build_pack in ("nixpacks", "railpack", "static", "dockerfile", "dockercompose"):
        updates["build_pack"] = build_pack
    dockerfile = deploy.get("dockerfile_location")
    if isinstance(dockerfile, str) and dockerfile.strip():
        updates["dockerfile_location"] = dockerfile.strip()
    return updates


def build_analysis_prompt(project: Project) -> str:
    """Compose the pt-BR kickoff prompt handed to the containerized agent."""
    parts = [
        "Você é o agente de análise inicial do Painkiller, uma plataforma em que uma pessoa "
        "SEM formação técnica descreve o software que quer e o recebe pronto e publicado na internet.",
        "",
        "Conduza a elicitação de requisitos com essa pessoa usando a skill "
        "superpowers:brainstorming. Regras desta sessão:",
        "- Escreva sempre em português do Brasil, em linguagem simples, sem jargão técnico. "
        "Quando um termo técnico for inevitável, explique-o em uma frase.",
        "- Faça UMA pergunta por vez e espere a resposta. Prefira perguntas com exemplos ou "
        "alternativas concretas a perguntas abertas.",
        "- Pergunte sobre o que a pessoa quer que o software FAÇA e para QUEM; as decisões "
        "técnicas (linguagem, banco, framework) são suas — escolha o caminho mais simples e "
        "comum, e não peça que ela decida isso.",
        "- Não escreva código de produção nem implemente nada nesta sessão.",
        "- O repositório do projeto está montado em /workspace.",
        "",
        "Quando a pessoa aprovar a especificação, faça as duas coisas:",
        "1. Grave a especificação em docs/superpowers/specs/AAAA-MM-DD-<tema>-design.md.",
        f"2. Grave o backlog decomposto em {BACKLOG_RELATIVE}, exatamente neste formato:",
        '   {"spec_path": "<caminho do spec>",',
        '    "deploy": {"port": 3000, "build_pack": "dockerfile", "dockerfile_location": "/Dockerfile"},',
        '    "tasks": [',
        '     {"title": "...", "description": "...", "target_files": ["..."],',
        '      "acceptance_criteria": ["..."], "dependencies": ["<title de outra task>"]}',
        "   ]}",
        "   Cada tarefa precisa ser atômica e executável por um agente de codificação isolado, "
        "sem acesso a esta conversa: a descrição tem de ser autossuficiente.",
        "   As tarefas serão executadas em sequência e cada uma é verificada pelos testes do "
        "repositório; inclua a criação dos testes nas próprias tarefas.",
        "",
        "Requisitos de publicação (a aplicação vai para produção automaticamente via Coolify "
        "ao fim do backlog, sem intervenção humana):",
        "- A PRIMEIRA tarefa do backlog deve criar o esqueleto do projeto com um Dockerfile na "
        "raiz que constrói e sobe a aplicação ouvindo em 0.0.0.0 na porta declarada em "
        "\"deploy.port\", mais um endpoint de health check (GET /health respondendo 200).",
        "- Toda configuração sensível deve vir de variáveis de ambiente com valores padrão "
        "seguros para funcionar sem nenhuma configuração manual.",
        "- Dados persistentes devem usar SQLite em arquivo (ou equivalente embutido), a menos "
        "que a pessoa peça algo diferente.",
        "- Em \"deploy\", \"build_pack\" é \"dockerfile\" quando houver Dockerfile (o padrão), "
        "\"static\" para sites sem servidor, ou \"nixpacks\" quando preferir detecção automática.",
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
    parts.append("Comece cumprimentando a pessoa pelo nome do projeto e fazendo a primeira pergunta.")
    return "\n".join(parts)
