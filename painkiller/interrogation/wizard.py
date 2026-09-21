"""Interactive Interrogation Wizard and Backlog Generator."""

import uuid
from typing import Optional, Any
from pydantic import BaseModel, Field

from painkiller.core.domain.models import Task, TaskStatus
from painkiller.core.ports.issue_tracker import IssueTrackerPort
from painkiller.core.ports.llm import LLMPort


class AtomicTaskDraft(BaseModel):
    title: str
    description: str
    target_files: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class BacklogDraft(BaseModel):
    spec_summary: str
    tasks: list[AtomicTaskDraft]


class InterrogationSession(BaseModel):
    session_id: str
    project_id: str
    history: list[dict[str, str]] = Field(default_factory=list)
    current_spec: str = ""
    is_complete: bool = False


class InterrogationWizard:
    """Guides the analyst through an interactive requirements interview to produce a verified backlog."""

    def __init__(self, llm: LLMPort, tracker: IssueTrackerPort):
        self.llm = llm
        self.tracker = tracker
        self.sessions: dict[str, InterrogationSession] = {}

    async def start_session(self, project_id: str, initial_goal: str) -> InterrogationSession:
        session_id = f"session-{uuid.uuid4().hex[:8]}"
        session = InterrogationSession(
            session_id=session_id,
            project_id=project_id,
        )

        system_prompt = (
            "Você é o Agente de Interrogação e Arquitetura do Painkiller. "
            "Sua missão é entrevistar o analista/PO técnico para especificar rigorosamente o software a ser criado. "
            "Regras fundamentais:\n"
            "1. Faça APENAS UMA pergunta direcionada por vez.\n"
            "2. Explore requisitos, contratos de API, banco de dados, regras de negócio e casos de erro.\n"
            "3. Quando todos os detalhes estiverem claros e suficientes para codificação autônoma, responda iniciando com 'ESPECIFICAÇÃO_CONCLUÍDA:' seguido do resumo da especificação técnica completa."
        )

        user_msg = f"Objetivo inicial do projeto: {initial_goal}"
        session.history.append({"role": "user", "content": user_msg})

        question = await self.llm.complete(
            prompt=user_msg,
            system_prompt=system_prompt,
            project_id=project_id,
        )
        session.history.append({"role": "assistant", "content": question})

        self.sessions[session_id] = session
        return session

    async def reply(self, session_id: str, analyst_answer: str) -> tuple[str, bool]:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        session.history.append({"role": "user", "content": analyst_answer})

        # Build prompt from history
        conversation_context = "\n".join(
            [f"{m['role'].capitalize()}: {m['content']}" for m in session.history]
        )

        system_prompt = (
            "Você é o Agente de Interrogação do Painkiller. "
            "Continue a entrevista fazendo apenas uma pergunta por vez, OU se a arquitetura e detalhes estiverem prontos, "
            "responda iniciando com 'ESPECIFICAÇÃO_CONCLUÍDA:' e o documento final de especificação."
        )

        response = await self.llm.complete(
            prompt=conversation_context,
            system_prompt=system_prompt,
            project_id=session.project_id,
        )
        session.history.append({"role": "assistant", "content": response})

        if "ESPECIFICAÇÃO_CONCLUÍDA:" in response:
            session.is_complete = True
            session.current_spec = response.replace("ESPECIFICAÇÃO_CONCLUÍDA:", "").strip()
            return response, True

        return response, False

    async def commit_backlog(self, session_id: str) -> list[Task]:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        prompt = (
            f"Com base na especificação técnica validada:\n\n{session.current_spec or session.history[-1]['content']}\n\n"
            "Decomponha este projeto em uma lista ordenada de tarefas atômicas independentes, prontas para execução por um agente de codificação (Aider). "
            "Cada tarefa deve ter critérios de aceitação testáveis e arquivos alvo definidos."
        )

        backlog: BacklogDraft = await self.llm.structured_output(
            prompt=prompt,
            response_model=BacklogDraft,
            system_prompt="Decomponha o projeto em tarefas atômicas em JSON.",
            project_id=session.project_id,
        )

        created_tasks: list[Task] = []
        # Title to ID mapping for resolving dependencies
        title_to_id: dict[str, str] = {}

        for draft in backlog.tasks:
            # Map dependency titles to created task IDs
            resolved_deps = [title_to_id[dep] for dep in draft.dependencies if dep in title_to_id]
            task = await self.tracker.create_task(
                project_id=session.project_id,
                title=draft.title,
                description=draft.description,
                target_files=draft.target_files,
                acceptance_criteria=draft.acceptance_criteria,
                dependencies=resolved_deps,
            )
            title_to_id[draft.title] = task.id
            created_tasks.append(task)

        # Mark the first task ready if created
        if created_tasks:
            first_task = await self.tracker.update_task_status(created_tasks[0].id, TaskStatus.READY)
            created_tasks[0] = first_task

        return created_tasks
