"""Project secrets: name rules, the build environment and log redaction."""

import logging
import re
from typing import Any, Iterable, Optional

from painkiller.core.domain.models import SecretScope

logger = logging.getLogger(__name__)

#: Nome de variável de ambiente, em maiúsculas.
NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

#: O Vite só põe no bundle o que começa com isto: o prefixo diz para onde o valor vai.
APP_PREFIX = "VITE_"

#: Nomes que o Painkiller define ele mesmo no build.
RESERVED_NAMES = {"VITE_API_URL"}

#: Valores curtos demais apagariam trechos comuns do log.
MIN_REDACTED_LENGTH = 4

REDACTED = "***"


class SecretNameError(ValueError):
    """The name does not fit its scope; the message is pt-BR, like the API's."""


def check_secret(name: str, scope: SecretScope) -> str:
    """Validate a secret's name against its scope and return it normalized."""
    name = (name or "").strip()
    if not NAME_PATTERN.match(name):
        raise SecretNameError(
            "Nome de segredo inválido: use letras maiúsculas, números e _ (ex.: OPENAI_API_KEY)."
        )
    if name in RESERVED_NAMES:
        raise SecretNameError(f"{name} é definido pelo Painkiller e não pode ser um segredo.")
    if scope == SecretScope.APP and not name.startswith(APP_PREFIX):
        raise SecretNameError("Segredos do app começam com VITE_: só assim o build os inclui.")
    if scope == SecretScope.SERVER and name.startswith(APP_PREFIX):
        raise SecretNameError("Segredos do backend não podem começar com VITE_: esse prefixo vai para o app.")
    return name


async def secret_values(tracker: Any, project_id: str, scope: Optional[SecretScope] = None) -> dict[str, str]:
    """The project's secret values, or {} when the tracker cannot give them.

    Como as dúvidas respondidas: um tracker sem suporte (ou um dublê de teste)
    não pode derrubar o build.
    """
    getter = getattr(tracker, "get_secret_values", None)
    if getter is None:
        return {}
    try:
        values = await getter(project_id, scope)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Segredos de {project_id} indisponíveis: {e}")
        return {}
    return values if isinstance(values, dict) else {}


async def secret_names(tracker: Any, project_id: str) -> list[Any]:
    """The project's secrets (names and scopes) for the agents' prompts, or []."""
    lister = getattr(tracker, "list_secrets", None)
    if lister is None:
        return []
    try:
        secrets = await lister(project_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Segredos de {project_id} indisponíveis: {e}")
        return []
    return list(secrets) if isinstance(secrets, list) else []


def redact(text: Optional[str], values: Iterable[str]) -> Optional[str]:
    """Replace every known secret value in ``text`` with ``***``."""
    if not text:
        return text
    # Os mais longos primeiro: um valor que contém outro some inteiro.
    for value in sorted({v for v in values if v and len(v) >= MIN_REDACTED_LENGTH}, key=len, reverse=True):
        text = text.replace(value, REDACTED)
    return text


def secrets_block(secrets: Iterable[Any], english: bool, in_task: bool = True) -> str:
    """Prompt block naming the project's secrets — names only, the agent never sees a value.

    Na tarefa o agente pede um segredo novo com ``painkiller ask``; na análise,
    que já é uma conversa, ele pede direto ao analista.
    """
    secrets = list(secrets)
    ask_en = "use painkiller ask to ask the analyst" if in_task else "ask the analyst"
    ask_pt = "use painkiller ask para pedir ao analista" if in_task else "peça ao analista"

    lines: list[str] = []
    if english:
        lines.append("\n## Project secrets (you only see the names):")
        for s in secrets:
            if s.scope == SecretScope.APP:
                lines.append(f"- {s.name} (app): import.meta.env.{s.name} at build time; readable inside the APK.")
            else:
                lines.append(f"- {s.name} (backend): os.environ[\"{s.name}\"], only in backend/.")
        if not secrets:
            lines.append("- None registered yet.")
        lines.append(
            "- Never write a secret value in code, tests, commits or messages, and never ask for one; "
            "mock them in tests and document the names in .env.example (backend/.env.example for the "
            "backend). If the work needs a new secret, " + ask_en + " to register it "
            "in Edit project → Secrets, giving only the name (VITE_* for the app, any other name for the backend)."
        )
    else:
        lines.append("\n## Segredos do projeto (você só vê os nomes):")
        for s in secrets:
            if s.scope == SecretScope.APP:
                lines.append(f"- {s.name} (app): import.meta.env.{s.name} no build; legível dentro do APK.")
            else:
                lines.append(f"- {s.name} (backend): os.environ[\"{s.name}\"], só em backend/.")
        if not secrets:
            lines.append("- Nenhum cadastrado ainda.")
        lines.append(
            "- Nunca escreva o valor de um segredo em código, testes, commits ou mensagens, nem peça um "
            "valor; simule-os nos testes e documente os nomes em .env.example (backend/.env.example para o "
            "backend). Se o trabalho precisar de um segredo novo, " + ask_pt + " "
            "que o cadastre em Editar projeto → Segredos, dizendo só o nome (VITE_* para o app, qualquer "
            "outro nome para o backend)."
        )
    return "\n".join(lines)
