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

# Android: JDK 17 (Temurin, independente da versão do Debian da base) e o SDK
# com cmdline-tools, platform e build-tools fixados — o agente compila o app e
# a verificação roda ./gradlew testDebugUnitTest assembleDebug. Atualize junto
# com o compileSdk do arcabouço embutido (painkiller/scaffolds/android-kotlin).
ARG ANDROID_CMDLINE_TOOLS=13114758
ARG ANDROID_PLATFORM=android-36
ARG ANDROID_BUILD_TOOLS=36.0.0
COPY --from=eclipse-temurin:17-jdk /opt/java/openjdk /opt/java/openjdk
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
    && sdkmanager --install "platform-tools" "platforms;${ANDROID_PLATFORM}" "build-tools;${ANDROID_BUILD_TOOLS}" > /dev/null

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
RUN pip install --no-cache-dir --break-system-packages pytest pytest-asyncio lxml uv /tmp/painkiller && rm -rf /tmp/painkiller

RUN mkdir -p /workspace

WORKDIR /workspace

RUN git config --global user.name "Painkiller Agent" \
    && git config --global user.email "agent@painkiller.local" \
    && git config --global --add safe.directory /workspace

CMD ["painkiller", "acp-run", "--help"]
