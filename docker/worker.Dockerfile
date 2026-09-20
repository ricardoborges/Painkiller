FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install aider-chat
RUN pip install --no-cache-dir aider-chat

# Install painkiller CLI
COPY . /tmp/painkiller
RUN pip install --no-cache-dir /tmp/painkiller && rm -rf /tmp/painkiller

WORKDIR /workspace

ENV GIT_AUTHOR_NAME="Painkiller Agent"
ENV GIT_AUTHOR_EMAIL="agent@painkiller.local"
ENV GIT_COMMITTER_NAME="Painkiller Agent"
ENV GIT_COMMITTER_EMAIL="agent@painkiller.local"

CMD ["aider", "--yes"]
