# Imagem do worker de execução de tarefas: DeepSeek Harness (dsh) + superpowers
FROM node:22-slim

ARG SUPERPOWERS_REPO=https://github.com/obra/superpowers
# Commit fixado: as skills mudam o comportamento do agente; atualize de propósito.
ARG SUPERPOWERS_REF=8ca22dba9a94f28898bbce59f2537ff4d87c747d

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Instala o DeepSeek Harness nativo (dsh)
# Versão fixada: acp-run depende do protocolo ACP e do formato do log de sessão.
ARG DSH_VERSION=0.1.7-rc.2
RUN npm install -g "@deepseek-ai/dsh@${DSH_VERSION}"

# Corrige conflito de tipo duplicado no koffi do dsh-win32-process (bug de colisão FFI em ambientes Linux)
COPY docker/patch_dsh.py /tmp/patch_dsh.py
RUN python3 /tmp/patch_dsh.py && rm -f /tmp/patch_dsh.py

# Clona o repositório superpowers
RUN git init -q /opt/superpowers \
    && git -C /opt/superpowers fetch -q --depth 1 "${SUPERPOWERS_REPO}" "${SUPERPOWERS_REF}" \
    && git -C /opt/superpowers checkout -q FETCH_HEAD \
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
