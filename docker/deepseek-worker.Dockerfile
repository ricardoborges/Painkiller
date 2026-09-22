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
RUN npm install -g @deepseek-ai/dsh || true

# Clona o repositório superpowers
RUN git clone --depth 1 --branch "${SUPERPOWERS_REF}" "${SUPERPOWERS_REPO}" /opt/superpowers \
    && rm -rf /opt/superpowers/.git

# Assegura que plugin.json existe para conformidade com o dsh / cordis
RUN if [ ! -f /opt/superpowers/plugin.json ]; then echo '{"name": "superpowers"}' > /opt/superpowers/plugin.json; fi

# Instala o CLI do painkiller e pytest para verificação de testes no repo target
COPY . /tmp/painkiller
RUN pip install --no-cache-dir --break-system-packages pytest /tmp/painkiller && rm -rf /tmp/painkiller

RUN mkdir -p /workspace

WORKDIR /workspace

RUN git config --global user.name "Painkiller Agent" \
    && git config --global user.email "agent@painkiller.local" \
    && git config --global --add safe.directory /workspace

CMD ["dsh", "--profile", "headless", "--json"]
