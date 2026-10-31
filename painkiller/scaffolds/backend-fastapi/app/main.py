"""Backend do app: guarda os segredos e fala com os serviços externos.

O app Android nunca recebe uma chave paga; ele chama este backend, que chama o
serviço. Por isso toda rota que gasta uma chave precisa de autenticação do
usuário do app ou, no mínimo, do limite de requisições abaixo — senão vira um
proxy aberto para a conta do dono.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.rate_limit import RateLimitMiddleware


def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "*")
    return [o.strip() for o in raw.split(",") if o.strip()] or ["*"]


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="Backend")
    # A prévia do app roda numa origem opaca ("null") e o APK em
    # https://localhost: em produção, restrinja a essas origens.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        RateLimitMiddleware,
        per_minute=int(os.environ.get("RATE_LIMIT_PER_MINUTE", "60") or 0),
        exempt=("/health",),
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
