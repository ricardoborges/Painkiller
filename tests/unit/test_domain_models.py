"""Unit tests for core domain models and status transitions."""

import pytest
from datetime import datetime
from painkiller.core.domain.models import (
    TaskStatus,
    ClarificationStatus,
    Project,
    Task,
    ClarificationRequest,
    ExecutionResult,
)

def test_task_lifecycle_status_transitions():
    task = Task(
        id="task-1",
        project_id="proj-1",
        title="Criar endpoint de login",
        description="Implementar autenticação JWT",
        target_files=["auth.py"],
        acceptance_criteria=["Deve retornar 200 e token"],
    )
    assert task.status == TaskStatus.BACKLOG

    task.mark_ready()
    assert task.status == TaskStatus.READY

    task.mark_running()
    assert task.status == TaskStatus.RUNNING

    task.mark_awaiting_analyst()
    assert task.status == TaskStatus.AWAITING_ANALYST

    task.mark_in_review()
    assert task.status == TaskStatus.IN_REVIEW

    task.mark_completed()
    assert task.status == TaskStatus.COMPLETED

def test_clarification_request_defaults():
    req = ClarificationRequest(
        id="clar-1",
        task_id="task-1",
        question="Qual o algoritmo de hash?",
        context_summary="auth.py linha 20",
    )
    assert req.status == ClarificationStatus.PENDING
    assert req.answer is None
    assert req.created_at is not None

def test_execution_result_model():
    result = ExecutionResult(
        exit_code=42,
        logs="Agent paused for clarification",
        clarification=ClarificationRequest(
            id="c-1",
            task_id="t-1",
            question="Qual o framework?",
            context_summary="setup",
        ),
    )
    assert result.exit_code == 42
    assert result.clarification is not None
    assert result.clarification.question == "Qual o framework?"
