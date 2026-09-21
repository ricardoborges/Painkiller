# Imagem do worker de execução de tarefas: Antigravity CLI (agy) + superpowers + Gemini 3.8 Flash.
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

# Instala o CLI do painkiller e pytest para verificação
COPY . /tmp/painkiller
RUN pip install --no-cache-dir --break-system-packages pytest /tmp/painkiller && rm -rf /tmp/painkiller

# Prepara diretórios, configura autenticação direta via GEMINI_API_KEY e copia o plugin para o Antigravity
RUN mkdir -p /workspace /root/.gemini/config/plugins /root/.gemini/antigravity-cli \
    && echo '{"modelProvider": "gemini"}' > /root/.gemini/antigravity-cli/settings.json \
    && cp -r /opt/superpowers /root/.gemini/config/plugins/superpowers

WORKDIR /workspace

# Registra o plugin para o Antigravity CLI
RUN agy plugin install /opt/superpowers || true

RUN git config --global user.name "Painkiller Agent" \
    && git config --global user.email "agent@painkiller.local" \
    && git config --global --add safe.directory /workspace

CMD ["agy", "--dangerously-skip-permissions"]
