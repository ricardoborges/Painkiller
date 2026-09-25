"""Initial-analysis engine: drives a live brainstorming session with the analyst."""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
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
    harness_model,
)
from painkiller.core.ports.agent_session import AgentSessionPort
from painkiller.core.ports.git import GitPort
from painkiller.core.ports.issue_tracker import IssueTrackerPort
from painkiller.core.ports.usage_ledger import UsageLedgerPort
from painkiller.core.usage import parse_agent_usage
from painkiller.core.attachment_reader import extract_attachment_text

logger = logging.getLogger(__name__)

#: Pasta onde cada análise deposita o seu backlog decomposto, lido de volta pela
#: API através do bind mount assim que o analista aprova a especificação. Um
#: arquivo por análise: um arquivo único para o projeto fazia a sessão seguinte
#: reimportar as tarefas da anterior.
BACKLOGS_RELATIVE = ".painkiller/backlogs"

#: Arquivo único de versões anteriores. Só é aceito na importação se foi escrito
#: depois do início da análise, e então é movido para o arquivo da sessão.
LEGACY_BACKLOG_RELATIVE = ".painkiller/backlog.json"


def backlog_relative(analysis_session_id: str) -> str:
    """Repo-relative path of the backlog file owned by one analysis session."""
    return f"{BACKLOGS_RELATIVE}/{analysis_session_id}.json"

#: Pasta onde a superpowers grava specs e planos; versionada no remoto (Gitea)
#: ao fim de cada turno do agente e na importação do backlog.
DOCS_RELATIVE = "docs"

#: Linguagem do bloco cercado que a UI troca por opções clicáveis. O mesmo nome
#: está em web/src/lib/choices.ts — mudar aqui exige mudar lá.
CHOICES_FENCE = "painkiller-choices"

#: Pasta, dentro do repositório, onde caem os arquivos que o analista anexa ao
#: chat. O agente os lê pelo bind mount; o exclude do git os mantém fora de
#: qualquer commit (o `git add -A` do `painkiller ask` os levaria junto).
UPLOADS_RELATIVE = ".painkiller/uploads"

#: Cabeçalho do bloco de anexos acrescentado à mensagem do analista. O mesmo
#: texto está em web/src/lib/attachments.ts, que o esconde da transcrição e
#: mostra os arquivos como etiquetas — mudar aqui exige mudar lá.
ATTACHMENTS_HEADER = "Anexos enviados pelo analista"

#: Extensões tratadas como imagem no aviso ao agente.
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"})


def upload_relative(analysis_session_id: str, filename: str) -> str:
    """Repo-relative path of a file the analyst attached to one analysis."""
    return f"{UPLOADS_RELATIVE}/{analysis_session_id}/{filename}"


def safe_upload_name(filename: str) -> str:
    """Basename reduced to characters every shell and bind mount accepts."""
    base = os.path.basename((filename or "").replace("\\", "/")).strip() or "arquivo"
    stem, ext = os.path.splitext(base)
    clean = "".join(c if c.isalnum() and c.isascii() or c in "-_." else "-" for c in stem)
    clean = clean.strip("-.") or "arquivo"
    ext = "".join(c for c in ext.lower() if c.isalnum() and c.isascii() or c == ".")
    return f"{uuid.uuid4().hex[:6]}_{clean[:80]}{ext[:10]}"


def with_attachments(text: str, paths: list[str]) -> str:
    """Append the attachment block the agent reads (and the UI hides)."""
    if not paths:
        return text
    lines = [
        f"{ATTACHMENTS_HEADER} (caminhos relativos à raiz do repositório; "
        "abra cada um com sua ferramenta de leitura de arquivos antes de responder):"
    ]
    for path in paths:
        kind = "imagem" if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS else "arquivo"
        lines.append(f"- `{path}` ({kind})")
    block = "\n".join(lines)
    return f"{text}\n\n{block}" if text else block


def _exclude_uploads(repo_path: str) -> None:
    """Keep the uploads folder out of git through `.git/info/exclude`."""
    git_dir = os.path.join(repo_path, ".git")
    if not os.path.isdir(git_dir):
        return
    exclude = os.path.join(git_dir, "info", "exclude")
    entry = f"/{UPLOADS_RELATIVE}/"
    existing = ""
    if os.path.exists(exclude):
        with open(exclude, "r", encoding="utf-8") as f:
            existing = f.read()
    if entry in existing.splitlines():
        return
    os.makedirs(os.path.dirname(exclude), exist_ok=True)
    with open(exclude, "a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(entry + "\n")


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

    def __init__(self, session: AnalysisSession, repo_path: str, model: str = ""):
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
        # Modelo do projeto, trocado pelo que o agente anunciar no init; o
        # RESULT nem sempre o repete.
        self.model = model


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
        git: Optional[GitPort] = None,
    ):
        self.agent = agent
        self.tracker = tracker
        self.usage = usage
        # Opcional: sem ele os documentos ficam só no disco, como antes.
        self.git = git
        self.runs: dict[str, AnalysisRun] = {}

    # ---- ciclo de vida -------------------------------------------------

    async def start(
        self,
        project: Project,
        force_new: bool = False,
        iteration_session_id: Optional[str] = None,
    ) -> AnalysisSession:
        active = await self.get_active(project.id)
        if not isinstance(active, AnalysisSession):
            active = None
        # Uma análise ativa de outra sessão iterativa não pode ser reaproveitada:
        # a conversa (e o backlog que ela gera) pertence àquela sessão.
        if active and iteration_session_id and not await self._bound_to(active.id, iteration_session_id):
            force_new = True
        if not force_new:
            if active:
                run = self.runs.get(active.id)
                if run and await self.agent.is_alive(active.id):
                    return active
                return await self.resume(project, active.id)
        else:
            if active:
                try:
                    await self.stop(active.id)
                except Exception as e:
                    logger.warning(f"Erro ao parar sessão anterior {active.id}: {e}")

        session_id = f"analysis-{uuid.uuid4().hex[:8]}"
        claude_session_id = str(uuid.uuid4())
        session = AnalysisSession(
            id=session_id,
            project_id=project.id,
            claude_session_id=claude_session_id,
            status=AnalysisStatus.STARTING,
        )
        run = AnalysisRun(session=session, repo_path=project.repo_path, model=harness_model(project.harness, project.model))
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
                # Sem sessão explícita, a análise vai para a mais recente — nunca
                # para a primeira, que já pode estar em execução.
                all_sessions = await self.tracker.list_sessions(project.id)
                if isinstance(all_sessions, (list, tuple)) and all_sessions:
                    iter_sess = all_sessions[-1]
                else:
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

        await self._ensure_default_branch(project)
        prompt = build_analysis_prompt(
            project,
            backlog_path=backlog_relative(session_id),
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
                harness=project.harness,
                api_key=project.api_key,
                model=project.model,
                effort=project.effort,
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
            run = AnalysisRun(session=session, repo_path=project.repo_path, model=harness_model(project.harness, project.model))
            events = await self.tracker.list_analysis_events(session_id)
            run.events = list(events) if isinstance(events, (list, tuple)) else []
            self.runs[session_id] = run

        alive = await self.agent.is_alive(session_id)
        if not alive:
            # Com o contêiner vivo o agente pode estar escrevendo: só trocamos de
            # branch quando ele vai ser religado do zero.
            await self._ensure_default_branch(project)
            try:
                session.container_name = await self.agent.start(
                    session_id=session_id,
                    repo_path=project.repo_path,
                    prompt="",
                    resume=True,
                    claude_session_id=session.claude_session_id,
                    harness=project.harness,
                    api_key=project.api_key,
                    model=project.model,
                    effort=project.effort,
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
                        await self.sync_docs(run)
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
            try:
                await self.agent.stop(run.session.id)
            except Exception:
                pass

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

    async def _ensure_default_branch(self, project: Project) -> None:
        """Put the repo on the default branch so docs/ lands where the UI links to.

        Um dispatch deixa o repositório na feature/ da tarefa. Se houver edição
        pendente em arquivo rastreado, a troca é recusada e a análise segue na
        branch atual — melhor docs numa feature/ do que levar código a meio
        caminho para a principal.
        """
        if self.git is None or not project.repo_path:
            return
        try:
            code, out = await self.git.switch_branch(project.repo_path, project.default_branch)
            if code != 0:
                logger.warning(
                    f"Análise segue fora de {project.default_branch} em {project.repo_path}: {out}"
                )
        except Exception as e:
            logger.warning(f"Não foi possível trocar para {project.default_branch}: {e}")

    async def sync_docs(self, run: AnalysisRun) -> Optional[str]:
        """Commit docs/ on the current branch and push it to the remote.

        O push roda mesmo sem commit novo: a skill de brainstorming costuma
        commitar o spec ela mesma, e esse commit também precisa chegar ao Gitea.
        Falhas só são registradas — versionar não pode derrubar a sessão.
        """
        if self.git is None or not run.repo_path:
            return None
        sha = None
        try:
            sha = await self.git.commit_paths(
                run.repo_path,
                [DOCS_RELATIVE],
                "docs: atualiza documentos da análise inicial",
            )
            branch = await self.git.current_branch(run.repo_path)
            if branch and branch != "HEAD":
                code, out = await self.git.push(run.repo_path, branch)
                if code != 0:
                    logger.warning(f"Push de docs/ falhou em {run.repo_path}: {out}")
        except Exception as e:
            logger.warning(f"Não foi possível versionar docs/ em {run.repo_path}: {e}")
        return sha

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
        elif event.type == AgentEventType.ERROR and event.raw.get("harness_error"):
            # Falha anunciada pelo harness (sem saldo, chave recusada...): é o
            # motivo que o analista precisa ver quando a sessão cair logo depois.
            run.session.error = event.text
        elif event.type == AgentEventType.EXIT:
            code = event.raw.get("exit_code", 1)
            run.session.exit_code = code
            run.session.status = (
                AnalysisStatus.FINISHED if code == 0 else AnalysisStatus.FAILED
            )

    async def save_upload(self, session_id: str, filename: str, data: bytes) -> str:
        """Store a file the analyst attached; returns its repo-relative path."""
        await self.get_or_restore(session_id)
        run = self._require(session_id)
        if not run.repo_path:
            raise ValueError("A sessão não tem repositório para receber o anexo.")
        relative = upload_relative(session_id, safe_upload_name(filename))
        target = os.path.join(run.repo_path, *relative.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)
        try:
            _exclude_uploads(run.repo_path)
        except OSError as e:
            logger.warning(f"Não foi possível excluir {UPLOADS_RELATIVE} do git em {run.repo_path}: {e}")
        return relative

    async def send(
        self, session_id: str, text: str, attachments: Optional[list[str]] = None
    ) -> AnalysisSession:
        # Após um restart a sessão só existe no banco até alguém abrir o stream.
        await self.get_or_restore(session_id)
        run = self._require(session_id)
        # Só aceita anexos desta sessão: o caminho vai para o prompt do agente.
        prefix = f"{UPLOADS_RELATIVE}/{session_id}/"
        paths = [p for p in (attachments or []) if p.startswith(prefix) and ".." not in p]
        text = with_attachments(text, paths)
        # Um restart da API derruba o contêiner, mas a sessão restaurada ainda
        # mostra a vez do analista: sem religar, a resposta cairia numa fila que
        # ninguém lê e a tela ficaria em "agente trabalhando" para sempre. O
        # `resume` sobe o agente na mesma conversa, posicionado no fim da fila,
        # então a mensagem abaixo é a primeira coisa que ele lê.
        if run.session.status != AnalysisStatus.FINISHED and not await self.agent.is_alive(session_id):
            project = await self.tracker.get_project(run.session.project_id)
            if isinstance(project, Project):
                await self.resume(project, session_id)
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
        model = harness_model(project.harness, project.model) if isinstance(project, Project) else ""
        run = AnalysisRun(session=session, repo_path=repo_path, model=model)
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

    async def get_active_for(
        self, project_id: str, iteration_session_id: str
    ) -> Optional[AnalysisSession]:
        """The project's active analysis, only if it belongs to that iteration session."""
        active = await self.get_active(project_id)
        if active and await self._bound_to(active.id, iteration_session_id):
            return active
        return None

    async def _bound_to(self, analysis_id: str, iteration_session_id: str) -> bool:
        try:
            iter_sess = await self.tracker.get_session(iteration_session_id)
        except Exception:
            return False
        return getattr(iter_sess, "analysis_session_id", None) == analysis_id

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

    @staticmethod
    def _backlog_file(run: AnalysisRun) -> Optional[str]:
        """Locate this session's backlog, adopting a fresh legacy file if needed.

        Uma análise iniciada antes da troca de caminho ainda grava o arquivo
        único; ele só vale se foi escrito depois do início desta análise (senão
        é o backlog de outra sessão) e é movido para o caminho desta sessão,
        para não ser importado de novo pela próxima.
        """
        own = os.path.join(run.repo_path, *backlog_relative(run.session.id).split("/"))
        if os.path.exists(own):
            return own
        legacy = os.path.join(run.repo_path, *LEGACY_BACKLOG_RELATIVE.split("/"))
        if not os.path.exists(legacy):
            return None
        started = run.session.created_at
        if isinstance(started, datetime):
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            written = datetime.fromtimestamp(os.path.getmtime(legacy), timezone.utc)
            if written < started:
                return None
        os.makedirs(os.path.dirname(own), exist_ok=True)
        os.replace(legacy, own)
        return own

    async def commit_backlog(
        self,
        session_id: str,
        iteration_session_id: Optional[str] = None,
    ) -> list[Task]:
        """Turn the backlog file this analysis wrote into real tasks."""
        run = self._require(session_id)
        path = self._backlog_file(run)
        if path is None:
            raise FileNotFoundError(
                f"O agente ainda não gravou {backlog_relative(session_id)}. Conclua a análise e "
                "peça a ele para registrar o backlog antes de importar."
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

        await self.sync_docs(run)

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

        try:
            await self.agent.stop(session_id)
        except Exception as e:
            logger.warning(f"Erro ao parar agente após commit do backlog ({session_id}): {e}")

        return created


def build_analysis_prompt(
    project: Project,
    backlog_path: str = LEGACY_BACKLOG_RELATIVE,
    session_number: int = 1,
    previous_sessions: Optional[list[IterationSession]] = None,
    previous_completed_tasks: Optional[list[Task]] = None,
) -> str:
    """Compose the pt-BR kickoff prompt handed to the containerized agent.

    Session 1 is a guided elicitation (superpowers:brainstorming from the first
    message). From session 2 on the agent starts in chat mode: it greets and
    follows the analyst, reaching for superpowers skills only when they fit.
    """
    chat_mode = isinstance(session_number, int) and session_number > 1
    if chat_mode:
        parts = [
            "Você é o agente do Painkiller, em modo conversa com o analista.",
            "",
            "Nesta sessão é o analista quem conduz: ele pode tirar dúvidas sobre o projeto "
            "e o código, pedir ajustes, relatar problemas ou propor novas funcionalidades. "
            "Regras desta sessão:",
            "- Escreva sempre em português do Brasil.",
            "- Responda diretamente ao que o analista pedir, de forma objetiva.",
            "- Use as skills do superpowers quando fizerem sentido (por exemplo, "
            "superpowers:brainstorming quando ele quiser especificar algo novo). "
            "Ao conduzir as perguntas de uma skill, faça UMA pergunta por vez.",
            "- Não escreva código de produção nem implemente nada nesta sessão: "
            "o que for construído vira tarefa no backlog.",
            "- O repositório do projeto está montado em /workspace.",
            "",
        ]
    else:
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
        ]
    parts += [
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
        "Não inclua uma opção \"Outro\": a plataforma sempre acrescenta uma, para o "
        "analista responder livremente.",
        "",
        "Quando o analista aprovar uma especificação, faça as seguintes coisas:",
        "1. Grave a especificação em docs/superpowers/specs/AAAA-MM-DD-<tema>-design.md.",
        f"2. Grave o backlog decomposto em {backlog_path} (arquivo exclusivo desta sessão; "
        "não leia nem reaproveite backlogs de outras sessões), exatamente neste formato:",
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
            "Use esse histórico para responder com contexto ao que o analista trouxer."
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
    if chat_mode:
        parts.append(
            "Comece com uma saudação curta (uma ou duas frases) dizendo que está pronto e "
            "pergunte o que o analista quer fazer nesta sessão. Não inicie uma elicitação "
            "por conta própria nem ofereça alternativas nesta primeira mensagem."
        )
    else:
        parts.append("Comece cumprimentando o analista e fazendo a primeira pergunta.")
    return "\n".join(parts)
