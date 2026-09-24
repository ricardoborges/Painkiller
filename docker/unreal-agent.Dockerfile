# Imagem do agente de análise inicial: Unreal Agent + superpowers
# Compila o unreal-agent-runner em Go e mantém um processo vivo lendo a fila de stdin montada em /workspace/.painkiller/.

# O go.mod do unreal-agent exige Go 1.27 (encoding/json/v2, uuid da stdlib), e
# a imagem oficial fixa GOTOOLCHAIN=local: uma versão menor não compila.
FROM golang:1.27.1-trixie AS builder

ARG UNREAL_AGENT_REPO=https://github.com/unreallabsai/unreal-agent.git
# Commit fixado: a saída JSONL do runner não é um contrato estável, e é ela que
# `painkiller unreal-run` traduz. Atualize junto com os testes da ponte.
ARG UNREAL_AGENT_COMMIT=1b9f778453f411c029b39b85102aaefb95e7e48d

RUN git init -q /src/unreal-agent \
    && cd /src/unreal-agent \
    && git fetch -q --depth 1 "${UNREAL_AGENT_REPO}" "${UNREAL_AGENT_COMMIT}" \
    && git checkout -q FETCH_HEAD \
    && CGO_ENABLED=0 go build -trimpath -buildvcs=false -ldflags="-s -w" \
       -o /usr/local/bin/unreal-agent-runner ./cmd/unreal-agent-runner

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

# O runner só descobre skills em <workspace>/.harness/skills; `painkiller unreal-run`
# as publica lá a cada partida (e as tira do git via .git/info/exclude).

# A ferramenta Bash do runner usa $SHELL (padrão /bin/sh).
ENV SHELL=/bin/bash

# Instala o CLI do painkiller, que fornece `painkiller unreal-run` (ponte de stdin)
# e `painkiller ask` (protocolo de interrupção limpa).
COPY . /tmp/painkiller
RUN pip install --no-cache-dir --break-system-packages /tmp/painkiller && rm -rf /tmp/painkiller

RUN mkdir -p /workspace

WORKDIR /workspace

RUN git config --global user.name "Painkiller Agent" \
    && git config --global user.email "agent@painkiller.local" \
    && git config --global --add safe.directory /workspace

CMD ["painkiller", "unreal-run", "--stdin-file", "/workspace/.painkiller/agent-stdin.jsonl"]
