import pytest
from painkiller.core.domain.models import IterationSession, SessionStatus, Task, TaskStatus


def test_iteration_session_creation():
    session = IterationSession(
        id="sess-1",
        project_id="proj-1",
        number=1,
        title="Sessão 1",
    )
    assert session.status == SessionStatus.PLANNING
    assert session.number == 1
    assert session.analysis_session_id is None
    assert session.spec_path is None


def test_task_has_session_id():
    task = Task(
        id="t-1",
        project_id="proj-1",
        title="Implementar autenticação",
        description="Criar fluxo de login",
        session_id="sess-1",
    )
    assert task.session_id == "sess-1"
