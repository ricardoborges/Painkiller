# Imagem do agente de análise inicial: Claude Code + superpowers.
# Diferente de worker.Dockerfile (Aider, one-shot), esta imagem mantém um
# processo vivo lendo a fila de stdin montada em /workspace/.painkiller/.
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

RUN npm install -g @anthropic-ai/claude-code

# O plugin é carregado por --plugin-dir, que aceita um diretório contendo
# .claude-plugin/plugin.json — ou seja, a raiz do clone.
RUN git clone --depth 1 --branch "${SUPERPOWERS_REF}" "${SUPERPOWERS_REPO}" /opt/superpowers \
    && rm -rf /opt/superpowers/.git

# Instala o CLI do painkiller, que fornece `painkiller agent-run` (a ponte de
# stdin) e `painkiller ask` (o protocolo de interrupção limpa).
COPY . /tmp/painkiller
RUN pip install --no-cache-dir --break-system-packages /tmp/painkiller && rm -rf /tmp/painkiller

# O Claude Code recusa --permission-mode bypassPermissions quando roda como
# root, então o agente precisa de um usuário sem privilégio. A imagem node já
# traz `node` em uid 1000.
RUN mkdir -p /workspace && chown -R node:node /workspace /home/node

USER node
WORKDIR /workspace

RUN git config --global user.name "Painkiller Agent" \
    && git config --global user.email "agent@painkiller.local" \
    && git config --global --add safe.directory /workspace

CMD ["painkiller", "agent-run", "--stdin-file", "/workspace/.painkiller/agent-stdin.jsonl", "--", "--print", "--verbose", "--input-format", "stream-json", "--output-format", "stream-json", "--plugin-dir", "/opt/superpowers", "--permission-mode", "bypassPermissions"]
