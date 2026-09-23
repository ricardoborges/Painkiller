FROM docker:cli

# git, curl e jq sao os pre-requisitos que o Coolify valida (ValidatePrerequisites).
# Faltando algum, ele tenta instalar sozinho, e o instalador dele nao conhece
# Alpine: "Unsupported OS type for prerequisites installation".
RUN apk add --no-cache openssh bash curl wget git jq docker-cli-compose && \
    ssh-keygen -A && \
    mkdir -p /root/.ssh && \
    chmod 700 /root/.ssh && \
    echo "PermitRootLogin yes" >> /etc/ssh/sshd_config && \
    echo "PubkeyAuthentication yes" >> /etc/ssh/sshd_config && \
    echo "GatewayPorts yes" >> /etc/ssh/sshd_config

# A chave autorizada nao e embutida na imagem: o docker-compose.yml a gera por
# maquina (servico coolify-ssh-init) e a instala ao subir o contêiner.

EXPOSE 22

CMD ["/usr/sbin/sshd", "-D", "-e"]
