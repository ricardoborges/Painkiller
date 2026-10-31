"""The app's optional backend: a FastAPI service under ``backend/`` in the same repo.

O app Android não pode guardar segredo (tudo no bundle é legível dentro do
APK), então chaves pagas ficam num backend que nasce e evolui pelo mesmo fluxo
de tarefas, no mesmo repositório. O repositório decide: "o projeto tem backend"
é "existe ``backend/Dockerfile``", sem flag no banco.
"""

import asyncio
import logging
import os
from typing import Any, Optional

from painkiller.core.domain.models import DeploymentComponent, EnvironmentType, ProjectType, TaskStatus
from painkiller.core.ports.git import GitPort
from painkiller.core.scaffold import copy_scaffold_dir
from painkiller.core.templates import SCAFFOLDS_DIR, project_type_of

logger = logging.getLogger(__name__)

#: Pasta do backend na raiz do repositório do app.
BACKEND_DIR = "backend"

#: Arcabouço embutido copiado para ``backend/``.
BACKEND_SCAFFOLD_DIR = os.path.join(SCAFFOLDS_DIR, "backend-fastapi")


class BackendError(Exception):
    """The backend cannot be added; the message is pt-BR, like the API's."""


class BackendExistsError(BackendError):
    pass


def has_backend(repo_path: Optional[str]) -> bool:
    return bool(repo_path) and os.path.isfile(os.path.join(repo_path, BACKEND_DIR, "Dockerfile"))


async def add_backend(git: GitPort, tracker: Any, project: Any) -> Optional[str]:
    """Copy the backend scaffold into ``backend/`` on the default branch, commit and push it.

    Recusa projeto nativo (Kotlin), ``backend/`` já existente e projeto com
    tarefa rodando — a árvore de trabalho estaria na ``feature/`` dela. Devolve
    o SHA do commit; falha de push só é registrada, como no resto do fluxo.
    """
    repo_path = project.repo_path
    if project_type_of(project) is not ProjectType.CAPACITOR_REACT:
        raise BackendError("Só apps Capacitor podem ter backend.")
    if not repo_path or not os.path.isdir(repo_path):
        raise BackendError("O repositório do projeto não existe.")
    target = os.path.join(repo_path, BACKEND_DIR)
    if os.path.isdir(target) and os.listdir(target):
        raise BackendExistsError("O projeto já tem a pasta backend/.")
    tasks = await tracker.list_tasks(project.id)
    if any(t.status == TaskStatus.RUNNING for t in tasks or []):
        raise BackendError("Há uma tarefa em execução: adicione o backend quando ela terminar.")

    code, out = await git.switch_branch(repo_path, project.default_branch)
    if code != 0:
        raise BackendError(f"Não foi possível trocar para {project.default_branch}: {out}")

    await asyncio.to_thread(copy_scaffold_dir, BACKEND_SCAFFOLD_DIR, target)
    sha = await git.commit_paths(repo_path, [BACKEND_DIR], "chore: adiciona backend (FastAPI)")
    if project.repo_url:
        try:
            code, out = await git.push(repo_path, project.default_branch)
            if code != 0:
                logger.warning(f"Push do backend falhou em {repo_path}: {out}")
        except Exception as e:
            logger.warning(f"Push do backend falhou em {repo_path}: {e}")
    return sha


#: Variável que o app lê (``import.meta.env.VITE_API_URL``) para achar o backend.
API_URL_ENV = "VITE_API_URL"


def backend_build_env(project: Any, deployment: Any, environment: EnvironmentType) -> dict[str, str]:
    """``{VITE_API_URL: …}`` for a build of the app talking to the backend of ``environment``.

    Vazio sem backend ou sem adapter de deploy: o app simplesmente não recebe a URL.
    """
    if deployment is None or not has_backend(project.repo_path):
        return {}
    url = deployment.environment_url(project, environment, DeploymentComponent.BACKEND)
    return {API_URL_ENV: url} if url else {}
