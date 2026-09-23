# Imagem do worker de execução de tarefas: DeepSeek Harness (dsh) + superpowers
FROM node:22-slim

ARG SUPERPOWERS_REPO=https://github.com/obra/superpowers
ARG SUPERPOWERS_REF=main

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Instala o DeepSeek Harness nativo (dsh)
RUN npm install -g @deepseek-ai/dsh

# Corrige conflito de tipo duplicado no koffi do dsh-win32-process (bug de colisão FFI em ambientes Linux)
COPY docker/patch_dsh.py /tmp/patch_dsh.py
RUN python3 /tmp/patch_dsh.py && rm -f /tmp/patch_dsh.py

# Clona o repositório superpowers
RUN git clone --depth 1 --branch "${SUPERPOWERS_REF}" "${SUPERPOWERS_REPO}" /opt/superpowers \
    && rm -rf /opt/superpowers/.git

# Publica as skills do superpowers no catálogo de sessão do dsh: o
# dsh-skill-filesystem lê ~/.agents/skills/<nome>/SKILL.md, o mesmo formato do repo.
RUN mkdir -p /root/.agents && ln -s /opt/superpowers/skills /root/.agents/skills

# Instala o CLI do painkiller e pytest para verificação de testes no repo target
COPY . /tmp/painkiller
RUN pip install --no-cache-dir --break-system-packages pytest pytest-asyncio lxml /tmp/painkiller && rm -rf /tmp/painkiller

RUN mkdir -p /workspace

WORKDIR /workspace

RUN git config --global user.name "Painkiller Agent" \
    && git config --global user.email "agent@painkiller.local" \
    && git config --global --add safe.directory /workspace

CMD ["painkiller", "acp-run", "--help"]
