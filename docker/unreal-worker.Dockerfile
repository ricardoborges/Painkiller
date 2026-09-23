# Imagem do worker de execução de tarefas: Unreal Agent + superpowers
FROM golang:1.24-bookworm AS builder

ARG UNREAL_AGENT_REPO=https://github.com/unreallabsai/unreal-agent.git
ARG UNREAL_AGENT_REF=main

RUN git clone --depth 1 --branch "${UNREAL_AGENT_REF}" "${UNREAL_AGENT_REPO}" /src/unreal-agent \
    && cd /src/unreal-agent \
    && CGO_ENABLED=0 go build -ldflags="-s -w" -o /usr/local/bin/unreal-agent-runner ./cmd/unreal-agent-runner

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

COPY --from=builder /usr/local/bin/unreal-agent-runner /usr/local/bin/unreal-agent-runner

# Clona o repositório superpowers
RUN git clone --depth 1 --branch "${SUPERPOWERS_REF}" "${SUPERPOWERS_REPO}" /opt/superpowers \
    && rm -rf /opt/superpowers/.git

# Publica as skills para que estejam disponíveis tanto em /root/.agents quanto para o unreal-agent
RUN mkdir -p /root/.agents && ln -s /opt/superpowers/skills /root/.agents/skills

# Instala o CLI do painkiller (`painkiller ask`, protocolo de interrupção limpa)
# e pytest para verificação de testes no repo target.
COPY . /tmp/painkiller
RUN pip install --no-cache-dir --break-system-packages pytest pytest-asyncio lxml /tmp/painkiller && rm -rf /tmp/painkiller

RUN mkdir -p /workspace

WORKDIR /workspace

RUN git config --global user.name "Painkiller Agent" \
    && git config --global user.email "agent@painkiller.local" \
    && git config --global --add safe.directory /workspace

CMD ["unreal-agent-runner", "--help"]
