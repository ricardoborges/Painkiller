"""FastAPI server application for Painkiller."""

import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Ensure .env is loaded with priority
load_dotenv(override=True)

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker
from painkiller.adapters.git.git_adapter import GitCliAdapter
from painkiller.adapters.sandbox.docker_runner import DockerSandboxRunner
from painkiller.adapters.llm.litellm_adapter import LiteLLMAdapter
from painkiller.engine.orchestrator import PainkillerOrchestrator
from painkiller.interrogation.wizard import InterrogationWizard
from painkiller.api.routes.auth import router as auth_router
from painkiller.api.routes.projects import router as projects_router
from painkiller.api.routes.tasks import router as tasks_router
from painkiller.api.routes.interrogation import router as interrogation_router


def create_app(
    db_url: str = "sqlite+aiosqlite:///painkiller.db",
    docker_image: str = "painkiller-worker:latest",
) -> FastAPI:
    """Application factory initializing hexagonal adapters and state."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        tracker: SQLiteIssueTracker = app.state.tracker
        await tracker.init_db()
        yield
        # Shutdown
        await tracker.close()

    app = FastAPI(title="Painkiller Engine", version="0.1.0", lifespan=lifespan)

    # Instantiate adapters
    tracker = SQLiteIssueTracker(db_url=db_url)
    git = GitCliAdapter()
    sandbox = DockerSandboxRunner(image_name=docker_image)
    llm = LiteLLMAdapter()

    orchestrator = PainkillerOrchestrator(tracker=tracker, sandbox=sandbox, git=git)
    wizard = InterrogationWizard(llm=llm, tracker=tracker)

    # Attach to application state
    app.state.tracker = tracker
    app.state.git = git
    app.state.sandbox = sandbox
    app.state.llm = llm
    app.state.orchestrator = orchestrator
    app.state.wizard = wizard

    # Register routers
    app.include_router(auth_router)
    app.include_router(projects_router)
    app.include_router(tasks_router)
    app.include_router(interrogation_router)

    # Static assets and dashboard
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/", include_in_schema=False)
        async def serve_dashboard():
            return FileResponse(os.path.join(static_dir, "index.html"))

    return app


app = create_app()
