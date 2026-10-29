# Imagem do worker de execução de tarefas: Antigravity CLI (agy) + superpowers + Gemini 3.8 Flash.
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

# Instala o Antigravity CLI (agy) nativo
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash -s -- -d /usr/local/bin \
    && chmod +x /usr/local/bin/agy

# Clona o repositório superpowers
RUN git init -q /opt/superpowers \
    && git -C /opt/superpowers fetch -q --depth 1 "${SUPERPOWERS_REPO}" "${SUPERPOWERS_REF}" \
    && git -C /opt/superpowers checkout -q FETCH_HEAD \
    && rm -rf /opt/superpowers/.git

# Assegura que plugin.json existe para conformidade com o agy
RUN if [ ! -f /opt/superpowers/plugin.json ]; then echo '{"name": "superpowers"}' > /opt/superpowers/plugin.json; fi

# Instala o CLI do painkiller, pytest para verificação e uv (o prompt da tarefa promete o uv)
COPY . /tmp/painkiller
RUN pip install --no-cache-dir --break-system-packages pytest pytest-asyncio lxml uv /tmp/painkiller && rm -rf /tmp/painkiller

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
