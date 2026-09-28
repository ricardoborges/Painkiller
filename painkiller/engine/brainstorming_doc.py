"""Generates and updates clean Markdown artifacts recording brainstorming Q&A turns."""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

from painkiller.core.domain.models import AgentEvent, AgentEventType

BRAINSTORMING_DIR = "docs/brainstorming"
CHOICES_FENCE = "painkiller-choices"
CHOICES_REGEX = re.compile(r"```" + re.escape(CHOICES_FENCE) + r"\s*\n(.*?)\n```", re.DOTALL)
ATTACHMENTS_PATTERN = re.compile(
    r"(?:Anexos enviados pelo analista|Attachments sent by the analyst).*?(?=(?:\Z|\n\n))",
    re.DOTALL | re.IGNORECASE,
)


def brainstorming_doc_relative(session_number: int) -> str:
    """Repo-relative path of the brainstorming Q&A document for a session."""
    return f"{BRAINSTORMING_DIR}/sessao-{session_number}.md"


def parse_choices(text: str) -> tuple[str, Optional[dict[str, Any]]]:
    """Extract choices JSON block from text, returning (cleaned_text, choices_dict)."""
    match = CHOICES_REGEX.search(text)
    if not match:
        return text, None
    raw_json = match.group(1).strip()
    try:
        choices = json.loads(raw_json)
    except Exception:
        choices = None
    cleaned = CHOICES_REGEX.sub("", text).strip()
    return cleaned, choices


def _extract_attachments(text: str) -> tuple[str, list[str]]:
    """Separate the main answer text from the appended attachments block."""
    match = ATTACHMENTS_PATTERN.search(text)
    if not match:
        return text.strip(), []

    block = match.group(0)
    cleaned = text[:match.start()] + text[match.end():]
    cleaned = cleaned.strip()

    paths: list[str] = []
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("- `") and "`" in line[3:]:
            path = line[3:].split("`")[0]
            paths.append(path)

    return cleaned, paths


def _format_time(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%H:%M")


def render_brainstorming_markdown(
    project_name: str,
    session_number: int,
    events: list[AgentEvent],
    status: str = "Em andamento",
    language: str = "pt-BR",
) -> str:
    """Render the full sequence of brainstorming questions and answers to Markdown."""
    english = language == "en-US"

    title = f"# Brainstorming: {'Session' if english else 'Sessão'} {session_number}"
    proj_label = "Project" if english else "Projeto"
    sess_label = "Session" if english else "Sessão"
    stat_label = "Status" if english else "Status"
    intro = (
        "> *This document records questions asked by the agent and analyst responses "
        "during the requirements brainstorming session.*"
        if english
        else "> *Este documento registra as perguntas feitas pelo agente e as respostas "
        "do analista durante a sessão de brainstorming e elicitação de requisitos.*"
    )

    header = [
        title,
        "",
        f"**{proj_label}:** {project_name}  ",
        f"**{sess_label}:** #{session_number}  ",
        f"**{stat_label}:** {status}  ",
        "",
        intro,
        "",
        "---",
        "",
        f"## {'Session Dialogue' if english else 'Diálogo da Sessão'}",
        "",
    ]

    lines = list(header)

    # Pair events into turns: ASSISTANT questions followed by USER answers
    turns: list[dict[str, Any]] = []
    current_agent_texts: list[tuple[str, Optional[datetime]]] = []

    for ev in events:
        if ev.type == AgentEventType.ASSISTANT:
            if ev.text and ev.text.strip():
                current_agent_texts.append((ev.text.strip(), ev.timestamp))
        elif ev.type == AgentEventType.USER:
            if ev.text and ev.text.strip():
                turns.append({
                    "agent": list(current_agent_texts),
                    "user": (ev.text.strip(), ev.timestamp),
                })
                current_agent_texts = []

    # If there is a pending question from the agent that hasn't been answered yet
    if current_agent_texts:
        turns.append({
            "agent": list(current_agent_texts),
            "user": None,
        })

    q_idx = 1
    for turn in turns:
        agent_entries = turn["agent"]
        user_entry = turn["user"]

        for raw_agent_text, agent_time in agent_entries:
            time_str = f" *({_format_time(agent_time)})*" if agent_time else ""
            q_label = f"### {'Question' if english else 'Pergunta'} {q_idx}{time_str}"
            lines.append(q_label)

            cleaned_q, choices = parse_choices(raw_agent_text)
            q_lines = [f"> {line}" if line.strip() else ">" for line in cleaned_q.splitlines()]
            lines.extend(q_lines)

            # If user has answered, check which choices matched
            user_text_raw = user_entry[0] if user_entry else ""
            user_cleaned, _ = _extract_attachments(user_text_raw) if user_text_raw else ("", [])

            if choices and "options" in choices and isinstance(choices["options"], list):
                opt_title = "**Options:**" if english else "**Opções apresentadas:**"
                lines.append(">")
                lines.append(f"> {opt_title}")
                for opt in choices["options"]:
                    lbl = opt.get("label", "")
                    desc = opt.get("description", "")
                    is_selected = False
                    if user_cleaned:
                        if lbl.lower() in user_cleaned.lower():
                            is_selected = True

                    box = "[x]" if is_selected else "[ ]"
                    desc_part = f" — *{desc}*" if desc else ""
                    if is_selected:
                        lines.append(f"> - {box} **{lbl}**{desc_part}")
                    else:
                        lines.append(f"> - {box} {lbl}{desc_part}")

            lines.append("")
            q_idx += 1

        if user_entry:
            user_raw, user_time = user_entry
            user_clean, attachments = _extract_attachments(user_raw)
            u_time_str = f" *({_format_time(user_time)})*" if user_time else ""
            ans_label = f"**{'Analyst Answer:' if english else 'Resposta do Analista:'}**{u_time_str}"
            lines.append(ans_label)
            lines.append("")
            lines.append(user_clean)
            lines.append("")

            if attachments:
                att_label = "*Attachments:*" if english else "*Anexos:*"
                lines.append(att_label)
                for att in attachments:
                    lines.append(f"- `{att}`")
                lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def update_brainstorming_document(
    repo_path: str,
    session_number: int,
    events: list[AgentEvent],
    project_name: str,
    status: str = "Em andamento",
    language: str = "pt-BR",
) -> str:
    """Generate and write the brainstorming Markdown document into the repository."""
    rel_path = brainstorming_doc_relative(session_number)
    target = os.path.join(repo_path, *rel_path.split("/"))
    os.makedirs(os.path.dirname(target), exist_ok=True)

    markdown_content = render_brainstorming_markdown(
        project_name=project_name,
        session_number=session_number,
        events=events,
        status=status,
        language=language,
    )

    with open(target, "w", encoding="utf-8") as f:
        f.write(markdown_content)

    return rel_path
