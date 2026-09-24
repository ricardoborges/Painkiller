"""FastAPI server application for Painkiller."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

# Ensure .env is loaded with priority
load_dotenv(override=True)

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import asyncio
import logging
from typing import Optional, Any
from painkiller.adapters.issue_trackers.gitea_mirror import GiteaIssueMirror
from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker
from painkiller.adapters.git.git_adapter import GitCliAdapter
from painkiller.adapters.vcs.gitea_adapter import GiteaAdapter
from painkiller.adapters.identity.google_oauth import GoogleOAuthClient
from painkiller.adapters.sandbox.docker_runner import DockerSandboxRunner
from painkiller.adapters.sandbox.docker_agent_session import DockerAgentSession
from painkiller.adapters.llm.litellm_adapter import LiteLLMAdapter
from painkiller.adapters.llm.pricing import litellm_price
from painkiller.adapters.llm.balance import fetch_balances, validate_key
from painkiller.adapters.deployment.coolify_adapter import CoolifyAdapter
from painkiller.adapters.deployment.coolify_bootstrap import CoolifyBootstrap
from painkiller.engine.orchestrator import PainkillerOrchestrator
from painkiller.engine.analysis import AnalysisOrchestrator
from painkiller.engine.deployment_service import DeploymentService
from painkiller.interrogation.wizard import InterrogationWizard
from painkiller.api.platform import PlatformConfig
from painkiller.api.security import current_user
from painkiller.api.routes.auth import router as auth_router
from painkiller.api.routes.projects import router as projects_router
from painkiller.api.routes.tasks import router as tasks_router
from painkiller.api.routes.interrogation import router as interrogation_router
from painkiller.api.routes.analysis import router as analysis_router
from painkiller.api.routes.usage import project_router as project_usage_router
from painkiller.api.routes.usage import router as usage_router
from painkiller.api.routes.sessions import router as sessions_router
from painkiller.api.routes.deployments import router as deployments_router
from painkiller.api.routes.gitea_proxy import router as gitea_proxy_router
from painkiller.api.routes.admin_templates import router as admin_templates_router, public_router as templates_router
from painkiller.api.routes.setup import router as setup_router


logger = logging.getLogger(__name__)


async def _align_project_repo_urls(tracker: SQLiteIssueTracker, vcs: GiteaAdapter) -> None:
    """Update repo_url on existing projects if pointing to legacy localhost:3300."""
    try:
        projects = await tracker.list_projects()
        target_base = vcs.external_base_url.rstrip("/")
        for p in projects:
            if p.repo_url and ("localhost:3300" in p.repo_url or "gitea:3000" in p.repo_url):
                import re
                new_url = re.sub(r"^https?://[^/]+", target_base, p.repo_url)
                if new_url != p.repo_url:
                    await tracker.update_project(p.id, repo_url=new_url)
                    logger.info(f"Updated repo_url for project {p.id}: {new_url}")
    except Exception as e:
        logger.debug(f"Could not align project repo URLs: {e}")


async def _scrub_remote_credentials(tracker: SQLiteIssueTracker, git: GitCliAdapter) -> None:
    """Remove the service-account password from remotes written by older versions."""
    try:
        projects = await tracker.list_projects()
    except Exception as e:
        logger.warning(f"Could not list projects to scrub git remotes: {e}")
        return
    for project in projects:
        if not project.repo_path or not os.path.isdir(os.path.join(project.repo_path, ".git")):
            continue
        try:
            await git.scrub_remote_credentials(project.repo_path)
        except Exception as e:
            logger.warning(f"Could not scrub git remote of {project.id}: {e}")


def create_app(
    db_url: str = "sqlite+aiosqlite:///painkiller.db",
    docker_image: str = "painkiller-worker:latest",
    agent_image: str = "painkiller-agent:latest",
    deployment_adapter: Optional[Any] = None,
) -> FastAPI:
    """Application factory initializing hexagonal adapters and state."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        tracker: SQLiteIssueTracker = app.state.tracker
        await tracker.init_db()
        # O que o admin salvou no wizard vence o .env; aplicado antes do 1º request.
        try:
            await app.state.platform.load()
        except Exception as e:
            logger.warning(f"Could not load platform settings: {e}")
        # Initialize Gitea admin user in background if service is reachable
        vcs: GiteaAdapter = app.state.vcs
        asyncio.create_task(vcs.ensure_admin_user())
        asyncio.create_task(_align_project_repo_urls(tracker, vcs))
        asyncio.create_task(_scrub_remote_credentials(tracker, app.state.git))

        # Limpeza de contêineres órfãos deixados por execuções anteriores
        agent = getattr(app.state, "agent", None)
        sandbox = getattr(app.state, "sandbox", None)
        try:
            if agent and hasattr(agent, "cleanup_orphaned_containers"):
                asyncio.create_task(agent.cleanup_orphaned_containers())
            if sandbox and hasattr(sandbox, "cleanup_orphaned_containers"):
                asyncio.create_task(sandbox.cleanup_orphaned_containers())
        except Exception:
            pass

        yield
        # Shutdown
        try:
            if agent and hasattr(agent, "stop_all"):
                await agent.stop_all()
        except Exception:
            pass
        await tracker.close()

    app = FastAPI(title="Painkiller Engine", version="0.1.0", lifespan=lifespan)

    # Instantiate adapters
    vcs = GiteaAdapter()
    # Toda escrita de tarefa passa pelo tracker: embrulhá-lo espelha o backlog
    # em issues do Gitea sem que o engine saiba que o Gitea existe.
    tracker = GiteaIssueMirror(SQLiteIssueTracker(db_url=db_url), vcs)
    # A senha da conta de serviço vai só para o ambiente do `git push`.
    git = GitCliAdapter(http_credentials=vcs.push_credentials())
    sandbox = DockerSandboxRunner(image_name=docker_image)
    # O mesmo SQLite guarda o razão de uso; a porta é separada para que o
    # tracker possa um dia ir para Redmine/GitHub sem levar os custos junto.
    usage = tracker
    llm = LiteLLMAdapter(usage=usage)
    agent = DockerAgentSession(image_name=agent_image)

    orchestrator = PainkillerOrchestrator(
        tracker=tracker, sandbox=sandbox, git=git, vcs=vcs, usage=usage
    )
    wizard = InterrogationWizard(llm=llm, tracker=tracker)
    analysis = AnalysisOrchestrator(agent=agent, tracker=tracker, usage=usage, git=git)

    deployment = deployment_adapter or CoolifyAdapter(vcs=vcs)
    deployment_service = DeploymentService(tracker=tracker, deployment=deployment)

    # Attach to application state
    app.state.tracker = tracker
    app.state.git = git
    app.state.vcs = vcs
    app.state.sandbox = sandbox
    app.state.llm = llm
    app.state.orchestrator = orchestrator
    app.state.wizard = wizard
    app.state.agent = agent
    app.state.analysis = analysis
    app.state.usage = usage
    app.state.deployment = deployment
    app.state.deployment_service = deployment_service
    # Injetáveis para os testes não dependerem do catálogo do LiteLLM nem da rede.
    app.state.price_lookup = litellm_price
    app.state.balance_lookup = fetch_balances
    app.state.key_validator = validate_key
    app.state.google_oauth = GoogleOAuthClient()
    app.state.coolify_bootstrap = CoolifyBootstrap()
    app.state.platform = PlatformConfig(store=tracker, state=app.state)

    # Register routers. Só /api/auth é público; o resto exige sessão, e cada
    # router ainda confere se o projeto/tarefa/sessão é do usuário.
    app.include_router(auth_router)
    app.include_router(gitea_proxy_router)
    signed_in = [Depends(current_user)]
    app.include_router(projects_router, dependencies=signed_in)
    app.include_router(tasks_router, dependencies=signed_in)
    app.include_router(interrogation_router, dependencies=signed_in)
    app.include_router(analysis_router, dependencies=signed_in)
    app.include_router(sessions_router, dependencies=signed_in)
    app.include_router(deployments_router, dependencies=signed_in)
    app.include_router(usage_router, dependencies=signed_in)
    app.include_router(project_usage_router, dependencies=signed_in)
    app.include_router(admin_templates_router, dependencies=signed_in)
    app.include_router(templates_router, dependencies=signed_in)
    app.include_router(setup_router, dependencies=signed_in)

    @app.get("/api/health")
    async def health_check():
        return {"status": "ok"}

    # SvelteKit SPA. Source lives in web/; `npm run build` emits here.
    static_dir = (Path(__file__).parent / "static").resolve()
    index_file = static_dir / "index.html"

    if index_file.is_file():
        # Hashed, immutable bundles get the StaticFiles fast path.
        app_assets = static_dir / "_app"
        if app_assets.is_dir():
            app.mount("/_app", StaticFiles(directory=app_assets), name="app_assets")

        # Registered last so every /api route and /docs match first. Anything
        # else is a client-side route and falls back to the SPA shell.
        @app.get("/{resource:path}", include_in_schema=False)
        async def serve_spa(resource: str):
            if (
                resource == "api"
                or resource.startswith("api/")
                or resource == "gitea"
                or resource.startswith("gitea/")
            ):
                raise HTTPException(status_code=404, detail="Not Found")

            if resource:
                candidate = (static_dir / resource).resolve()
                if candidate.is_file() and candidate.is_relative_to(static_dir):
                    return FileResponse(candidate)

            return FileResponse(index_file)

    return app


# Configuráveis por ambiente para que o contêiner possa apontar o banco para um
# volume e escolher a tag da imagem do worker. Os padrões mantêm o
# comportamento de execução local inalterado.
app = create_app(
    db_url=os.environ.get("PAINKILLER_DB_URL", "sqlite+aiosqlite:///painkiller.db"),
    docker_image=os.environ.get("PAINKILLER_WORKER_IMAGE", "painkiller-worker:latest"),
    agent_image=os.environ.get("PAINKILLER_AGENT_IMAGE", "painkiller-agent:latest"),
)
