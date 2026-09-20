"""Unit tests for InterrogationWizard and structured backlog generation."""

import pytest
from unittest.mock import AsyncMock
from painkiller.core.domain.models import Project, TaskStatus
from painkiller.interrogation.wizard import (
    InterrogationWizard,
    AtomicTaskDraft,
    BacklogDraft,
)


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def mock_tracker():
    tracker = AsyncMock()
    tracker.create_task.side_effect = lambda project_id, title, description, target_files, acceptance_criteria, dependencies: AsyncMock(
        id="t-new",
        project_id=project_id,
        title=title,
        description=description,
        status=TaskStatus.BACKLOG,
    )
    return tracker


@pytest.mark.asyncio
async def test_interrogation_flow_and_backlog_generation(mock_llm, mock_tracker):
    wizard = InterrogationWizard(llm=mock_llm, tracker=mock_tracker)

    # 1. Start session
    mock_llm.complete.return_value = "Qual banco de dados será utilizado?"
    session = await wizard.start_session(project_id="p1", initial_goal="Criar sistema de blog")
    assert session.session_id is not None
    assert len(session.history) == 2  # user prompt + assistant question

    # 2. Answer question
    mock_llm.complete.return_value = "ESPECIFICAÇÃO_CONCLUÍDA:\nArquitetura com FastAPI e SQLite definida."
    reply, is_complete = await wizard.reply(session.session_id, "Usaremos SQLite com SQLAlchemy 2.0")
    assert is_complete is True

    # 3. Generate backlog
    backlog_draft = BacklogDraft(
        spec_summary="Sistema de blog simples",
        tasks=[
            AtomicTaskDraft(
                title="Modelos de Post",
                description="Criar Post model",
                target_files=["models.py"],
                acceptance_criteria=["Campos id, title, body"],
            ),
            AtomicTaskDraft(
                title="Endpoint de Listagem",
                description="GET /posts",
                target_files=["routes.py"],
                acceptance_criteria=["Retorna lista de posts"],
                dependencies=["Modelos de Post"],
            ),
        ],
    )
    mock_llm.structured_output.return_value = backlog_draft

    created_tasks = await wizard.commit_backlog(session.session_id)
    assert len(created_tasks) == 2
    mock_tracker.create_task.assert_called()
