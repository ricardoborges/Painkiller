"""Idiomas: catálogo, tradução na borda HTTP e idioma do projeto para os agentes."""

import ast
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from painkiller.api.server import create_app
from painkiller.core.domain.models import (
    ClarificationRequest,
    ClarificationStatus,
    Project,
    Task,
)
from painkiller.core.i18n import (
    EN_US,
    get_locale,
    normalize_locale,
    parse_accept_language,
    project_language,
    tr,
    translate,
    use_locale,
)
from painkiller.engine.analysis import build_analysis_prompt, with_attachments
from painkiller.engine.orchestrator import PainkillerOrchestrator
from tests.auth_helpers import admin_headers

ROOT = Path(__file__).resolve().parents[2] / "painkiller"


# ---- núcleo ------------------------------------------------------------------


def test_normalize_and_accept_language():
    assert normalize_locale("en") == "en-US"
    assert normalize_locale("en_GB") == "en-US"
    assert normalize_locale("pt-PT") == "pt-BR"
    assert normalize_locale("fr") is None
    assert normalize_locale(None) is None
    assert parse_accept_language("fr-FR, en;q=0.8, pt;q=0.9") == "pt-BR"
    assert parse_accept_language("en-US,en;q=0.9") == "en-US"
    assert parse_accept_language("de, fr") is None


def test_translate_exact_pattern_and_passthrough():
    assert translate("Projeto não encontrado", "en-US") == "Project not found"
    assert translate("Projeto não encontrado", "pt-BR") == "Projeto não encontrado"
    # Padrão com placeholder, inclusive aninhado.
    assert (
        translate("Falha ao iniciar o agente: Sessão x1 não encontrada", "en-US")
        == "Failed to start the agent: Session x1 not found"
    )
    assert translate("texto sem entrada", "en-US") == "texto sem entrada"
    assert translate(None, "en-US") is None
    assert translate({"x": 1}, "en-US") == {"x": 1}


def test_tr_uses_context_locale():
    assert get_locale() == "pt-BR"
    with use_locale("en-US"):
        assert tr("Agente encerrou com código {code}", code=3) == "Agent exited with code 3"
    assert tr("Agente encerrou com código {code}", code=3) == "Agente encerrou com código 3"


def test_project_language_defaults_to_pt():
    assert project_language(Project(id="p", name="x", repo_path=".")) == "pt-BR"
    assert project_language(Project(id="p", name="x", repo_path=".", language="en-US")) == "en-US"
    assert project_language(object()) == "pt-BR"


def _http_details() -> list[tuple[str, str]]:
    """Every literal HTTPException detail in the API, formatted with dummy values."""
    found = []
    for path in (ROOT / "api").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "HTTPException"):
                continue
            for kw in node.keywords:
                if kw.arg != "detail":
                    continue
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    found.append((path.name, kw.value.value))
                elif isinstance(kw.value, ast.JoinedStr):
                    text = "".join(
                        part.value if isinstance(part, ast.Constant) else "VALUE"
                        for part in kw.value.values
                    )
                    found.append((path.name, text))
    return found


def test_every_http_error_message_has_an_english_translation():
    missing = [
        (where, text)
        for where, text in _http_details()
        # Mensagens que já nascem em inglês não precisam de entrada.
        if text not in ("Not Found",) and translate(text, "en-US") == text
    ]
    assert not missing, missing


def test_catalog_placeholders_match():
    import string

    fields = lambda s: {f for _, f, _, _ in string.Formatter().parse(s) if f}  # noqa: E731
    for source, target in EN_US.items():
        assert fields(source) == fields(target), source


# ---- API ---------------------------------------------------------------------


@pytest.fixture
async def client(tmp_path):
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


async def test_error_detail_follows_accept_language(client):
    headers = admin_headers()
    pt = await client.get("/api/projects/nope", headers=headers)
    en = await client.get("/api/projects/nope", headers={**headers, "Accept-Language": "en-US"})
    q = await client.get("/api/projects/nope?lang=en-US", headers=headers)
    assert pt.status_code == en.status_code == 404
    assert pt.json()["detail"] == "Projeto não encontrado"
    assert en.json()["detail"] == "Project not found"
    assert q.json()["detail"] == "Project not found"


async def test_project_language_defaults_to_request_and_is_validated(client):
    headers = {**admin_headers(), "Accept-Language": "en-US,en;q=0.9"}
    body = {"name": "Lang", "purpose": "p", "solution_description": "s", "api_key": "AIzaSyTest1234"}
    res = await client.post("/api/projects", json=body, headers=headers)
    assert res.status_code == 200, res.text
    project = res.json()
    assert project["language"] == "en-US"

    bad = await client.put(f"/api/projects/{project['id']}", json={"language": "fr-FR"}, headers=headers)
    assert bad.status_code == 400
    assert bad.json()["detail"].startswith("Invalid language")

    ok = await client.put(f"/api/projects/{project['id']}", json={"language": "pt-BR"}, headers=headers)
    assert ok.status_code == 200
    assert ok.json()["language"] == "pt-BR"


# ---- agentes -----------------------------------------------------------------


def test_analysis_prompt_in_project_language():
    pt = build_analysis_prompt(Project(id="p", name="Loja", repo_path="."))
    en = build_analysis_prompt(Project(id="p", name="Shop", repo_path=".", language="en-US"))
    assert "português do Brasil" in pt
    assert "US English" in en and "português" not in en
    assert "Go to backlog" in en
    chat = build_analysis_prompt(Project(id="p", name="Shop", repo_path=".", language="en-US"), session_number=2)
    assert "conversation mode" in chat


def test_attachment_block_in_project_language():
    block = with_attachments("hi", [".painkiller/uploads/a/x.png"], "en-US")
    assert "Attachments sent by the analyst" in block and "(image)" in block
    assert "Anexos enviados pelo analista" in with_attachments("oi", ["a.txt"])


def test_task_instructions_in_project_language():
    orch = PainkillerOrchestrator(tracker=None, sandbox=None, git=None)
    task = Task(id="t1", project_id="p", title="Login", description="Build it", acceptance_criteria=["works"])
    clar = ClarificationRequest(
        id="c", task_id="t1", question="JWT?", context_summary="auth.py",
        status=ClarificationStatus.ANSWERED, answer="PyJWT",
    )
    en = orch._build_task_instructions(
        task, Project(id="p", name="x", repo_path=".", language="en-US"), clarifications=[clar]
    )
    assert "# Task: Login" in en and "Acceptance Criteria" in en
    assert "Do NOT ask again" in en and "Answer: PyJWT" in en
    pt = orch._build_task_instructions(task, Project(id="p", name="x", repo_path="."))
    assert "# Tarefa: Login" in pt and "Protocolo de Dúvidas" in pt
