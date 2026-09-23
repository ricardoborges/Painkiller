# Imagem do worker de execução de tarefas: Maki (maki.sh) + superpowers
FROM node:22-slim

ARG SUPERPOWERS_REPO=https://github.com/obra/superpowers
ARG SUPERPOWERS_REF=main
ARG MAKI_VERSION=v0.5.6

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

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
RUN git clone --depth 1 --branch "${SUPERPOWERS_REF}" "${SUPERPOWERS_REPO}" /opt/superpowers \
    && rm -rf /opt/superpowers/.git \
    && mkdir -p /root/.agents \
    && ln -s /opt/superpowers/skills /root/.agents/skills

# Instala o CLI do painkiller (`painkiller ask`, protocolo de interrupção limpa)
# e pytest para verificação de testes no repo target.
COPY . /tmp/painkiller
RUN pip install --no-cache-dir --break-system-packages pytest pytest-asyncio lxml /tmp/painkiller && rm -rf /tmp/painkiller

RUN mkdir -p /workspace

WORKDIR /workspace

RUN git config --global user.name "Painkiller Agent" \
    && git config --global user.email "agent@painkiller.local" \
    && git config --global --add safe.directory /workspace

CMD ["maki", "--help"]
