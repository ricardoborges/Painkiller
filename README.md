# Painkiller

Plataforma automatizada de criação de software via orquestração de agentes.

## Arquitetura
- **Hexagonal / Ports & Adapters**: Domínio independente de infraestrutura.
- **Worker Harness (Antigravity CLI + Superpowers)**: Execução autônoma segura em contêineres Docker efêmeros.
- **Protocolo de Interrupção Limpa**: `painkiller ask` pausa tarefas com dúvidas sem perda de WIP.
- **Interrogação Ativa**: Elicitação guiada de requisitos com o analista.
