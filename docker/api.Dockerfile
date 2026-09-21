# =============================================================================
# Imagem da API do Painkiller: FastAPI + a SPA do SvelteKit ja construida.
#
# Estagio 1 constroi web/ com Node; estagio 2 e um runtime Python enxuto, sem
# Node nenhum. O build da SPA acontece aqui dentro, entao a imagem nao depende
# do conteudo commitado em painkiller/api/static/.
# =============================================================================

# ---------- estagio 1: SPA ----------
FROM node:22-slim AS web

WORKDIR /src/web

# Camada de dependencias separada: so invalida quando o lockfile muda.
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY web/ ./

# svelte.config.js emite em ../painkiller/api/static -> /src/painkiller/api/static
RUN npm run build


# ---------- estagio 2: runtime ----------
FROM python:3.11-slim

# git: o GitCliAdapter cria branches e commita nos repositorios dos projetos.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencias antes do codigo, pelo cache de camadas.
COPY pyproject.toml README.md ./
COPY painkiller/__init__.py ./painkiller/
RUN pip install --no-cache-dir -e . \
    # GitPort.run_tests roda `pytest` dentro do repositorio alvo, a partir
    # deste contentor.
    && pip install --no-cache-dir pytest

COPY painkiller/ ./painkiller/
COPY --from=web /src/painkiller/api/static/ ./painkiller/api/static/

# O orquestrador commita como o agente quando os testes passam.
ENV GIT_AUTHOR_NAME="Painkiller Engine" \
    GIT_AUTHOR_EMAIL="engine@painkiller.local" \
    GIT_COMMITTER_NAME="Painkiller Engine" \
    GIT_COMMITTER_EMAIL="engine@painkiller.local" \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" \
    || exit 1

CMD ["uvicorn", "painkiller.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
