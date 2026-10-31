# Imagem do worker de execução de tarefas: Unreal Agent + superpowers

# O go.mod do unreal-agent exige Go 1.27 (encoding/json/v2, uuid da stdlib), e
# a imagem oficial fixa GOTOOLCHAIN=local: uma versão menor não compila.
FROM golang:1.27.1-trixie AS builder

ARG UNREAL_AGENT_REPO=https://github.com/unreallabsai/unreal-agent.git
# Commit fixado: a saída JSONL do runner não é um contrato estável, e é ela que
# `painkiller unreal-run` traduz. Atualize junto com os testes da ponte.
ARG UNREAL_AGENT_COMMIT=1b9f778453f411c029b39b85102aaefb95e7e48d

# O DeepSeek recusa dois function_call_output com o mesmo call_id ("Duplicate
# tool output"), que o runner manda quando uma ferramenta ainda rodava ao fim
# de um turno. O patch manda o resultado tardio como mensagem do usuário e põe
# o primeiro resultado de cada chamada logo depois dela: o DeepSeek também
# recusa uma mensagem entre as duas ("No tool output found for tool call").
# Ao atualizar o commit, confira se ele ainda se aplica.
COPY docker/unreal-agent-late-tool-result.patch /tmp/late-tool-result.patch

RUN git init -q /src/unreal-agent \
    && cd /src/unreal-agent \
    && git fetch -q --depth 1 "${UNREAL_AGENT_REPO}" "${UNREAL_AGENT_COMMIT}" \
    && git checkout -q FETCH_HEAD \
    && git apply /tmp/late-tool-result.patch \
    && CGO_ENABLED=0 go build -trimpath -buildvcs=false -ldflags="-s -w" \
       -o /usr/local/bin/unreal-agent-runner ./cmd/unreal-agent-runner

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

# Android: JDK 21 (Temurin, independente da versão do Debian da base; o
# Capacitor 8 exige 21, e o app Kotlin compila com ele também) e o SDK com
# cmdline-tools, platform e build-tools fixados — o agente compila o app e a
# verificação roda o Gradle. Atualize junto com o compileSdk dos arcabouços
# embutidos (painkiller/scaffolds/android-kotlin e capacitor-react).
ARG ANDROID_CMDLINE_TOOLS=13114758
ARG ANDROID_PLATFORM=android-36
ARG ANDROID_BUILD_TOOLS=36.0.0
# O AGP do Capacitor 8 (8.13) pede o build-tools 35; sem ele aqui, cada
# verificação o baixaria de novo num contêiner que é descartado.
ARG ANDROID_CAPACITOR_BUILD_TOOLS=35.0.0
COPY --from=eclipse-temurin:21-jdk /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk \
    ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk
ENV PATH=/opt/java/openjdk/bin:/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends unzip && rm -rf /var/lib/apt/lists/* \
    && mkdir -p "$ANDROID_HOME/cmdline-tools" \
    && curl -fsSL -o /tmp/cmdline-tools.zip \
        "https://dl.google.com/android/repository/commandlinetools-linux-${ANDROID_CMDLINE_TOOLS}_latest.zip" \
    && unzip -q /tmp/cmdline-tools.zip -d "$ANDROID_HOME/cmdline-tools" \
    && mv "$ANDROID_HOME/cmdline-tools/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest" \
    && rm /tmp/cmdline-tools.zip \
    && yes | sdkmanager --licenses > /dev/null \
    && sdkmanager --install "platform-tools" "platforms;${ANDROID_PLATFORM}" "build-tools;${ANDROID_BUILD_TOOLS}" "build-tools;${ANDROID_CAPACITOR_BUILD_TOOLS}" > /dev/null

COPY --from=builder /usr/local/bin/unreal-agent-runner /usr/local/bin/unreal-agent-runner

# Clona o repositório superpowers
RUN git init -q /opt/superpowers \
    && git -C /opt/superpowers fetch -q --depth 1 "${SUPERPOWERS_REPO}" "${SUPERPOWERS_REF}" \
    && git -C /opt/superpowers checkout -q FETCH_HEAD \
    && rm -rf /opt/superpowers/.git

# O runner só descobre skills em <workspace>/.harness/skills; `painkiller unreal-run`
# as publica lá a cada partida (e as tira do git via .git/info/exclude).

# A ferramenta Bash do runner usa $SHELL (padrão /bin/sh).
ENV SHELL=/bin/bash

# Instala o CLI do painkiller (`painkiller unreal-run`, a ponte, e `painkiller ask`,
# protocolo de interrupção limpa) e pytest para verificação de testes no repo target.
COPY . /tmp/painkiller
RUN pip install --no-cache-dir --break-system-packages pytest pytest-asyncio lxml uv /tmp/painkiller && rm -rf /tmp/painkiller

RUN mkdir -p /workspace

WORKDIR /workspace

RUN git config --global user.name "Painkiller Agent" \
    && git config --global user.email "agent@painkiller.local" \
    && git config --global --add safe.directory /workspace

CMD ["painkiller", "unreal-run", "--help"]
