"""Tests for the brainstorming Q&A document generator."""

import os
from datetime import datetime, timezone
import pytest

from painkiller.core.domain.models import AgentEvent, AgentEventType
from painkiller.engine.brainstorming_doc import (
    BRAINSTORMING_DIR,
    brainstorming_doc_relative,
    parse_choices,
    render_brainstorming_markdown,
    update_brainstorming_document,
)


def test_brainstorming_doc_relative():
    assert brainstorming_doc_relative(1) == "docs/brainstorming/sessao-1.md"
    assert brainstorming_doc_relative(3) == "docs/brainstorming/sessao-3.md"


def test_parse_choices():
    raw_text = (
        "Qual banco de dados devemos usar?\n\n"
        "```painkiller-choices\n"
        '{"multiple": false, "options": [\n'
        '  {"label": "PostgreSQL", "description": "Robusto e relacional"},\n'
        '  {"label": "SQLite", "description": "Simples e embutido"}\n'
        "]}\n"
        "```"
    )
    cleaned, choices = parse_choices(raw_text)
    assert cleaned.strip() == "Qual banco de dados devemos usar?"
    assert choices is not None
    assert len(choices["options"]) == 2
    assert choices["options"][0]["label"] == "PostgreSQL"


def test_render_brainstorming_markdown_basic():
    t1 = datetime(2026, 9, 27, 22, 30, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 27, 22, 31, 0, tzinfo=timezone.utc)

    events = [
        AgentEvent(
            type=AgentEventType.ASSISTANT,
            text=(
                "Como você imagina a aplicação?\n\n"
                "```painkiller-choices\n"
                '{"multiple": false, "options": ['
                '  {"label": "Web App", "description": "Acesso pelo navegador"},'
                '  {"label": "CLI", "description": "Linha de comando"}'
                "]}\n"
                "```"
            ),
            timestamp=t1,
        ),
        AgentEvent(
            type=AgentEventType.USER,
            text="Web App",
            timestamp=t2,
        ),
    ]

    md = render_brainstorming_markdown(
        project_name="Painkiller App",
        session_number=1,
        events=events,
        status="Em andamento",
        language="pt-BR",
    )

    assert "# Brainstorming: Sessão 1" in md
    assert "**Projeto:** Painkiller App" in md
    assert "Como você imagina a aplicação?" in md
    assert "[x] **Web App**" in md
    assert "[ ] CLI" in md
    assert "**Resposta do Analista:**" in md
    assert "Web App" in md


def test_render_brainstorming_markdown_with_attachments():
    t1 = datetime(2026, 9, 27, 22, 30, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 27, 22, 31, 0, tzinfo=timezone.utc)

    user_text_with_att = (
        "Quero uma tela parecida com esta imagem\n\n"
        "Anexos enviados pelo analista (caminhos relativos à raiz do repositório; "
        "abra cada um com sua ferramenta de leitura de arquivos antes de responder):\n"
        "- `.painkiller/uploads/analysis-123/mockup.png` (imagem)"
    )

    events = [
        AgentEvent(
            type=AgentEventType.ASSISTANT,
            text="Você tem alguma referência visual?",
            timestamp=t1,
        ),
        AgentEvent(
            type=AgentEventType.USER,
            text=user_text_with_att,
            timestamp=t2,
        ),
    ]

    md = render_brainstorming_markdown(
        project_name="Painkiller App",
        session_number=1,
        events=events,
        status="Em andamento",
        language="pt-BR",
    )

    assert "Você tem alguma referência visual?" in md
    assert "Quero uma tela parecida com esta imagem" in md
    assert "Anexos:" in md or "Anexo" in md
    assert "mockup.png" in md


def test_update_brainstorming_document_file_io(tmp_path):
    repo_path = str(tmp_path)
    t1 = datetime(2026, 9, 27, 22, 30, 0, tzinfo=timezone.utc)

    events = [
        AgentEvent(
            type=AgentEventType.ASSISTANT,
            text="Qual é o público-alvo?",
            timestamp=t1,
        ),
    ]

    rel_path = update_brainstorming_document(
        repo_path=repo_path,
        session_number=1,
        events=events,
        project_name="Meu Projeto",
        status="Em andamento",
        language="pt-BR",
    )

    assert rel_path == "docs/brainstorming/sessao-1.md"
    file_full = tmp_path / "docs" / "brainstorming" / "sessao-1.md"
    assert file_full.exists()
    content = file_full.read_text(encoding="utf-8")
    assert "Qual é o público-alvo?" in content
