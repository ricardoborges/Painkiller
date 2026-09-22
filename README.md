# Painkiller

Plataforma automatizada de criação de software via orquestração de agentes.

## Arquitetura
- **Hexagonal / Ports & Adapters**: Domínio independente de infraestrutura.
- **Multi-Harness com Superpowers**:
  - **Antigravity CLI (`agy`) + Superpowers**: Google Gemini (3.8 Flash / Thinking) via CLI oficial.
  - **DeepSeek Harness (`dsh`) + Superpowers**: DeepSeek V3 / R1 via `@deepseek-ai/dsh` oficial.
  - Chave de API configurável por projeto com fallback seguro para variáveis globais do `.env`.
- **Protocolo de Interrupção Limpa**: `painkiller ask` pausa tarefas com dúvidas sem perda de WIP (código de saída 42).
- **Interrogação Ativa**: Elicitação guiada de requisitos com o analista.
