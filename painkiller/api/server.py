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
from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker
from painkiller.adapters.git.git_adapter import GitCliAdapter
from painkiller.adapters.vcs.gitea_adapter import GiteaAdapter
from painkiller.adapters.identity.google_oauth import GoogleOAuthClient
from painkiller.adapters.sandbox.docker_runner import DockerSandboxRunner
from painkiller.adapters.sandbox.docker_agent_session import DockerAgentSession
from painkiller.adapters.llm.litellm_adapter import LiteLLMAdapter
from painkiller.adapters.llm.pricing import litellm_price
from painkiller.adapters.llm.balance import fetch_balances
from painkiller.engine.orchestrator import PainkillerOrchestrator
from painkiller.engine.analysis import AnalysisOrchestrator
from painkiller.interrogation.wizard import InterrogationWizard
from painkiller.api.security import current_user
from painkiller.api.routes.auth import router as auth_router
from painkiller.api.routes.projects import router as projects_router
from painkiller.api.routes.tasks import router as tasks_router
from painkiller.api.routes.interrogation import router as interrogation_router
from painkiller.api.routes.analysis import router as analysis_router
from painkiller.api.routes.usage import project_router as project_usage_router
from painkiller.api.routes.usage import router as usage_router
from painkiller.api.routes.sessions import router as sessions_router


def create_app(
    db_url: str = "sqlite+aiosqlite:///painkiller.db",
    docker_image: str = "painkiller-worker:latest",
    agent_image: str = "painkiller-agent:latest",
) -> FastAPI:
    """Application factory initializing hexagonal adapters and state."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        tracker: SQLiteIssueTracker = app.state.tracker
        await tracker.init_db()
        # Initialize Gitea admin user in background if service is reachable
        vcs: GiteaAdapter = app.state.vcs
        asyncio.create_task(vcs.ensure_admin_user())

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
    tracker = SQLiteIssueTracker(db_url=db_url)
    git = GitCliAdapter()
    vcs = GiteaAdapter()
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
    # Injetáveis para os testes não dependerem do catálogo do LiteLLM nem da rede.
    app.state.price_lookup = litellm_price
    app.state.balance_lookup = fetch_balances
    app.state.google_oauth = GoogleOAuthClient()

    # Register routers. Só /api/auth é público; o resto exige sessão, e cada
    # router ainda confere se o projeto/tarefa/sessão é do usuário.
    app.include_router(auth_router)
    signed_in = [Depends(current_user)]
    app.include_router(projects_router, dependencies=signed_in)
    app.include_router(tasks_router, dependencies=signed_in)
    app.include_router(interrogation_router, dependencies=signed_in)
    app.include_router(analysis_router, dependencies=signed_in)
    app.include_router(sessions_router, dependencies=signed_in)
    app.include_router(usage_router, dependencies=signed_in)
    app.include_router(project_usage_router, dependencies=signed_in)

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
            if resource == "api" or resource.startswith("api/"):
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
