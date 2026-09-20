# Painkiller

Plataforma automatizada de criação de software via orquestração de agentes.

## Arquitetura
- **Hexagonal / Ports & Adapters**: Domínio independente de infraestrutura.
- **Worker Harness (Aider Headless)**: Execução segura em contêineres Docker efêmeros.
- **Protocolo de Interrupção Limpa**: `painkiller ask` pausa tarefas com dúvidas sem perda de WIP.
- **Interrogação Ativa**: Elicitação guiada de requisitos com o analista.
