# Design: Suporte ao Harness Unreal Agent com Superpowers e DeepSeek

**Data**: 2026-09-23  
**Status**: Aprovado  
**Versão**: 1.0.0  

---

## 1. Contexto e Objetivos

O Painkiller orquestra agentes de inteligência artificial em contêineres Docker efêmeros para:
1. **Análise Inicial e Elicitação**: Conversa socrática/brainstorming interativa entre o analista e o agente (`superpowers:brainstorming`).
2. **Execução Atômica de Tarefas**: Execução one-shot de tarefas do backlog em branches Git dedicadas (`feature/{task_id}`).

Atualmente, o sistema suporta três harnesses:
- `agy_superpowers`: Google Antigravity CLI (`agy`) com Gemini 3.8 Flash e `GEMINI_API_KEY`.
- `deepseek_superpowers`: DeepSeek Harness oficial (`@deepseek-ai/dsh` / Cordis) via ACP com `DEEPSEEK_API_KEY`.
- `maki_superpowers`: Maki CLI (`maki.sh`) com `DEEPSEEK_API_KEY`.

**Objetivo:** Adicionar uma nova opção de harness baseada no [Unreal Agent](https://github.com/unreallabsai/unreal-agent) (`unreal_superpowers`), utilizando o provedor **DeepSeek**, compartilhando as credenciais `DEEPSEEK_API_KEY`, suportando as skills do Superpowers e os mesmos presets de modelos do Maki.

---

## 2. Arquitetura da Solução

### 2.1 Modelo de Dados e Domínio

- **`HarnessType` (`painkiller/core/domain/models.py`)**:
  - Novo valor de enumeração: `UNREAL_SUPERPOWERS = "unreal_superpowers"`.
- **Autenticação**:
  - `unreal_superpowers` pertence ao conjunto `DEEPSEEK_KEY_HARNESSES`.
  - O projeto pode definir uma `api_key` personalizada ou recorrer por padrão à variável global `DEEPSEEK_API_KEY` do ambiente (`.env`).
- **Persistência SQLite**:
  - A coluna `harness` na tabela `projects` aceita `"unreal_superpowers"`, com migração retrocompatível já existente.

### 2.2 Provedor LLM e Configuração do Unreal Agent

O `unreal-agent-runner` suporta configuração por variáveis de ambiente:
- `UNREAL_HARNESS_LLM_PROVIDER`: `"openai"` (ou configurado para apontar para `https://api.deepseek.com` via endpoint compatível).
- `UNREAL_HARNESS_LLM_BASE_URL`: `"https://api.deepseek.com"`.
- `UNREAL_HARNESS_LLM_API_KEY`: Injetada a partir da chave do projeto ou de `DEEPSEEK_API_KEY`.
- `UNREAL_HARNESS_LLM_MODEL`: Modelo selecionado (default: `deepseek/deepseek-v4-pro` ou `deepseek-chat`).

Modelos padrão recomendados:
- `deepseek/deepseek-v4-pro` (Padrão)
- `deepseek/deepseek-v4-flash`
- `deepseek/deepseek-flash`
- Custom model (modelo personalizado inserido pelo usuário).

### 2.3 Integração com Superpowers e Skills

O `unreal-agent` possui detecção nativa de skills no diretório `.harness/skills` relativo ao workspace (`filepath.Join(workspace, ".harness", "skills")`).
- Cada skill contém seu arquivo de metadados e instruções `SKILL.md`.
- No contêiner, o repositório `obra/superpowers` é clonado em `/opt/superpowers`.
- Ao inicializar o workspace em `/workspace`, é assegurado o symlink `/workspace/.harness/skills -> /opt/superpowers/skills` (ou montagem gerenciada), permitindo que a ferramenta nativa `SkillUse` do `unreal-agent` encontre e invoque qualquer skill do Superpowers (`brainstorming`, `test-driven-development`, etc.).

### 2.4 Bridge de Execução: `painkiller unreal-run`

Para a sessão interativa de análise, o contêiner precisa manter um ciclo de vida contínuo respondendo a mensagens sucessivas do analista.
Criamos o utilitário CLI `painkiller unreal-run` em `painkiller/cli/unreal_run.py`:
- Lê a fila `.painkiller/agent-stdin.jsonl` montada em `/workspace/.painkiller/`.
- A cada mensagem do analista, executa o `unreal-agent-runner` com:
  - `-workspace /workspace`
  - `-session-directory /root/.local/state/unreal-agent/sessions`
  - `--session-id <claude_session_id>`
- Captura os eventos emitidos pelo `unreal-agent-runner` no stdout (em formato JSONL com `sessionstore.Item`: `model_response`, `tool_call_status`, `turn`) e emite eventos no envelope padrão do Painkiller (`AgentEvent`: `ASSISTANT_DELTA`, `ASSISTANT`, `TOOL_USE`, `TOOL_RESULT`, `RESULT`), assegurando que a UI e a contabilidade de tokens (`core/usage.py`) funcionem de forma idêntica aos outros harnesses.
- Para interrupção limpa por clarificação, o script `painkiller ask` é executado pelo `unreal-agent` via ferramenta `Bash`, saindo com exit code `42` e salvando `.painkiller/clarification.json`.

### 2.5 Contêineres Docker

São adicionados dois Dockerfiles em `docker/`:
1. **`docker/unreal-agent.Dockerfile`** (`painkiller-agent-unreal:latest`):
   - Multi-stage build com `golang:1.24` compilando `cmd/unreal-agent-runner` do repositório `unreallabsai/unreal-agent`.
   - Imagem runtime Debian com git, curl, python3, pip.
   - Instalação do pacote Painkiller e clone do repositório Superpowers.
   - Entrypoint: `painkiller unreal-run --stdin-file /workspace/.painkiller/agent-stdin.jsonl`.
2. **`docker/unreal-worker.Dockerfile`** (`painkiller-worker-unreal:latest`):
   - Mesma imagem base com `unreal-agent-runner`, Superpowers, pytest e CLI do Painkiller.
   - Entrypoint para execução direta de tarefas: `unreal-agent-runner -workspace /workspace -p <instruções>`.

### 2.6 Adaptadores Sandbox (`DockerAgentSession` e `DockerSandboxRunner`)

- **`DockerAgentSession`**:
  - Quando `harness == "unreal_superpowers"`:
    - Seleciona a imagem `painkiller-agent-unreal:latest`.
    - Injeta `DEEPSEEK_API_KEY`, `UNREAL_HARNESS_LLM_API_KEY`, `UNREAL_HARNESS_LLM_BASE_URL` e `UNREAL_HARNESS_LLM_PROVIDER`.
    - Monta o volume de estado persistente `.painkiller/unreal_home` em `/root/.local/state/unreal-agent`.
- **`DockerSandboxRunner`**:
  - Quando `harness == "unreal_superpowers"`:
    - Seleciona a imagem `painkiller-worker-unreal:latest`.
    - Executa tarefas one-shot via `unreal-agent-runner`.

### 2.7 Frontend SvelteKit

- **`web/src/lib/types.ts`**:
  - Atualização do tipo `HarnessType`: `'agy_superpowers' | 'deepseek_superpowers' | 'maki_superpowers' | 'unreal_superpowers'`.
  - Inclusão em `DEEPSEEK_KEY_HARNESSES`.
- **`web/src/lib/components/ProjectDialog.svelte`**:
  - Novo card de opção: `Unreal Agent + Superpowers`.
  - Presets de modelo compartilhados com o Maki.
- **Telas de listagem e detalhes de projeto**:
  - Badge `unreal` em `/projetos` e `/projetos/[id]`.

---

## 3. Protocolo de Erros e Clarificação

- Erros de autenticação ou falta de créditos (401/402/QUOTA) são classificados e apresentados na interface de forma amigável ao usuário.
- Se o agente invocar `painkiller ask "<pergunta>"`, o processo termina com exit code 42 e transiciona a tarefa para `AWAITING_ANALYST`.

---

## 4. Plano de Validação e Testes

1. **Testes Unitários Python**:
   - `tests/unit/test_unreal_harness.py`:
     - Testes de comando e parâmetros em `DockerAgentSession.start()` com `unreal_superpowers`.
     - Teste de injeção de variáveis de ambiente (`DEEPSEEK_API_KEY`, `UNREAL_HARNESS_LLM_PROVIDER`, etc.).
     - Teste de conversão dos eventos do `unreal-agent` em `AgentEvent`.
     - Teste do runner one-shot `DockerSandboxRunner` com tarefas normais e com `painkiller ask`.
   - `tests/unit/test_project_model.py`:
     - Criação de projeto com `HarnessType.UNREAL_SUPERPOWERS`.
2. **Checagem do Frontend**:
   - Validação de tipos do SvelteKit com `npm run check`.
