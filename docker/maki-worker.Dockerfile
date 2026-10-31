# Imagem do worker de execução de tarefas: Maki (maki.sh) + superpowers
FROM node:22-slim

ARG SUPERPOWERS_REPO=https://github.com/obra/superpowers
# Commit fixado: as skills mudam o comportamento do agente; atualize de propósito.
ARG SUPERPOWERS_REF=8ca22dba9a94f28898bbce59f2537ff4d87c747d
ARG MAKI_VERSION=v0.5.6

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

# Binário estático (musl) da release fixada, conferido contra o sha256sums.txt
# publicado na mesma release — em vez de executar o install.sh remoto.
RUN set -eux; \
    case "$(uname -m)" in \
      x86_64) target=x86_64-unknown-linux-musl ;; \
      aarch64) target=aarch64-unknown-linux-musl ;; \
      *) echo "arquitetura não suportada: $(uname -m)"; exit 1 ;; \
    esac; \
    asset="maki-${MAKI_VERSION}-${target}.tar.gz"; \
    base="https://github.com/tontinton/maki/releases/download/${MAKI_VERSION}"; \
    cd /tmp; \
    curl -fsSLO "${base}/${asset}"; \
    curl -fsSLO "${base}/sha256sums.txt"; \
    grep " ${asset}\$" sha256sums.txt | sha256sum -c -; \
    tar -xzf "${asset}"; \
    install -m 0755 "$(find /tmp -type f -name maki -perm -u+x | head -1)" /usr/local/bin/maki; \
    rm -rf /tmp/*; \
    maki --version

# Clona o repositório superpowers e publica as skills onde o maki as procura
# (~/.agents/skills/<nome>/SKILL.md, o mesmo formato do repo).
RUN git init -q /opt/superpowers \
    && git -C /opt/superpowers fetch -q --depth 1 "${SUPERPOWERS_REPO}" "${SUPERPOWERS_REF}" \
    && git -C /opt/superpowers checkout -q FETCH_HEAD \
    && rm -rf /opt/superpowers/.git \
    && mkdir -p /root/.agents \
    && ln -s /opt/superpowers/skills /root/.agents/skills

# Instala o CLI do painkiller (`painkiller ask`, protocolo de interrupção limpa)
# e pytest para verificação de testes no repo target.
COPY . /tmp/painkiller
RUN pip install --no-cache-dir --break-system-packages pytest pytest-asyncio lxml uv /tmp/painkiller && rm -rf /tmp/painkiller

RUN mkdir -p /workspace

WORKDIR /workspace

RUN git config --global user.name "Painkiller Agent" \
    && git config --global user.email "agent@painkiller.local" \
    && git config --global --add safe.directory /workspace

CMD ["maki", "--help"]
