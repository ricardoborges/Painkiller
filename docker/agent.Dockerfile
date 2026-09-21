# Imagem do agente de análise inicial: Antigravity CLI (agy) + superpowers + Gemini 3.8 Flash.
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

# Instala o Antigravity CLI (agy) nativo
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash -s -- -d /usr/local/bin \
    && chmod +x /usr/local/bin/agy

# Clona o repositório superpowers
RUN git clone --depth 1 --branch "${SUPERPOWERS_REF}" "${SUPERPOWERS_REPO}" /opt/superpowers \
    && rm -rf /opt/superpowers/.git

# Assegura que plugin.json existe para conformidade com o agy
RUN if [ ! -f /opt/superpowers/plugin.json ]; then echo '{"name": "superpowers"}' > /opt/superpowers/plugin.json; fi

# Instala o CLI do painkiller, que fornece `painkiller agent-run` (a ponte de
# stdin) e `painkiller ask` (o protocolo de interrupção limpa).
COPY . /tmp/painkiller
RUN pip install --no-cache-dir --break-system-packages /tmp/painkiller && rm -rf /tmp/painkiller

# Prepara diretórios e copia o plugin para o diretório padrão de plugins do Antigravity
RUN mkdir -p /workspace /home/node/.gemini/config/plugins \
    && cp -r /opt/superpowers /home/node/.gemini/config/plugins/superpowers \
    && chown -R node:node /workspace /home/node

USER node
WORKDIR /workspace

# Registra o plugin para o usuário node
RUN agy plugin install /opt/superpowers || true

RUN git config --global user.name "Painkiller Agent" \
    && git config --global user.email "agent@painkiller.local" \
    && git config --global --add safe.directory /workspace

CMD ["painkiller", "agent-run", "--agent-bin", "agy", "--stdin-file", "/workspace/.painkiller/agent-stdin.jsonl", "--", "--model", "gemini-3.8-flash", "--effort", "medium", "--dangerously-skip-permissions", "--input-format", "stream-json", "--output-format", "stream-json", "--print=\"\""]
