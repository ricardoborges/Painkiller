"""The app preview: the web build of a Capacitor project, shown in a phone frame.

A verificação pós-tarefa (``test_plan.build_capacitor_script``) monta, além do
build normal, uma cópia com caminhos relativos em ``PREVIEW_STAGING_RELATIVE``.
Só quando a tarefa conclui (testes verdes e merge feito) o orquestrador a
promove para ``PREVIEW_RELATIVE``: a prévia mostra sempre o último app
incorporado, nunca o de uma tarefa que falhou. As duas pastas ficam em
``.painkiller/``, fora do git.
"""

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

PREVIEW_RELATIVE = ".painkiller/preview"
PREVIEW_STAGING_RELATIVE = ".painkiller/preview-build"
PREVIEW_META_RELATIVE = ".painkiller/preview.json"


def _path(repo_path: str, relative: str) -> str:
    return os.path.join(repo_path, *relative.split("/"))


def preview_dir(repo_path: str) -> str:
    return _path(repo_path, PREVIEW_RELATIVE)


def promote_preview(repo_path: str, task_id: str, task_title: str) -> Optional[dict]:
    """Make the staged build the project's preview; None when there is nothing to promote.

    Nunca levanta: a prévia é um extra, a tarefa já concluiu.
    """
    staged = _path(repo_path, PREVIEW_STAGING_RELATIVE)
    if not os.path.isfile(os.path.join(staged, "index.html")):
        return None
    target = preview_dir(repo_path)
    try:
        if os.path.exists(target):
            shutil.rmtree(target)
        os.replace(staged, target)
        meta = {
            "task_id": task_id,
            "task_title": task_title,
            "built_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(_path(repo_path, PREVIEW_META_RELATIVE), "w", encoding="utf-8") as f:
            json.dump(meta, f)
        return meta
    except OSError as e:
        logger.warning(f"Não foi possível atualizar a prévia em {repo_path}: {e}")
        return None


def read_preview(repo_path: str) -> Optional[dict]:
    """The metadata of the current preview, or None when the project has none."""
    if not os.path.isfile(os.path.join(preview_dir(repo_path), "index.html")):
        return None
    try:
        with open(_path(repo_path, PREVIEW_META_RELATIVE), "r", encoding="utf-8") as f:
            meta = json.load(f)
        return meta if isinstance(meta, dict) else {}
    except (OSError, ValueError):
        return {}
