# Imagem do agente de análise inicial: DeepSeek Harness (dsh) + superpowers
# Mantém um processo vivo lendo a fila de stdin montada em /workspace/.painkiller/.
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
RUN npm install -g @deepseek-ai/dsh || true

# Clona o repositório superpowers
RUN git clone --depth 1 --branch "${SUPERPOWERS_REF}" "${SUPERPOWERS_REPO}" /opt/superpowers \
    && rm -rf /opt/superpowers/.git

# Assegura que plugin.json existe para conformidade com o dsh / cordis
RUN if [ ! -f /opt/superpowers/plugin.json ]; then echo '{"name": "superpowers"}' > /opt/superpowers/plugin.json; fi

# Instala o CLI do painkiller, que fornece `painkiller agent-run` (ponte de stdin)
# e `painkiller ask` (protocolo de interrupção limpa).
COPY . /tmp/painkiller
RUN pip install --no-cache-dir --break-system-packages /tmp/painkiller && rm -rf /tmp/painkiller

RUN mkdir -p /workspace

WORKDIR /workspace

RUN git config --global user.name "Painkiller Agent" \
    && git config --global user.email "agent@painkiller.local" \
    && git config --global --add safe.directory /workspace

CMD ["painkiller", "agent-run", "--agent-bin", "dsh", "--stdin-file", "/workspace/.painkiller/agent-stdin.jsonl", "--", "--profile", "headless", "--json"]
