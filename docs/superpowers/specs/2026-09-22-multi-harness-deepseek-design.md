# Design: Suporte a Múltiplos Harnesses (Antigravity CLI e DeepSeek Harness) com Superpowers

**Data**: 2026-09-22  
**Status**: Aprovado  
**Versão**: 1.0.0  

---

## 1. Contexto e Objetivos

O Painkiller orquestra agentes autônomos em contêineres Docker para elicitação de requisitos (análise inicial com `superpowers:brainstorming`) e para execução atômica de tarefas do backlog em branches dedicadas.

Atualmente, o sistema utiliza com exclusividade o **Antigravity CLI (`agy`)** acoplado ao modelo Gemini 3.8 Flash, autenticado via `GEMINI_API_KEY`.

**Objetivo:** Permitir que o usuário, ao criar ou editar um projeto, selecione o harness desejado e forneça opcionalmente a sua chave de API dedicada:
1. **`agy_superpowers`**: Antigravity CLI (`agy`) + plugin Superpowers (Gemini 3.8 Flash).
2. **`deepseek_superpowers`**: DeepSeek Harness nativo (`@deepseek-ai/dsh` / Cordis) + plugin Superpowers.

Se a chave de API não for informada no projeto, o sistema recorre de forma transparente às variáveis globais configuradas no ambiente do servidor (`.env`: `GEMINI_API_KEY` ou `DEEPSEEK_API_KEY`).

---

## 2. Arquitetura da Solução

### 2.1 Modelo de Dados e Domínio

- **`HarnessType` (`painkiller/core/domain/models.py`)**:
  Enum com os valores:
  - `AGY_SUPERPOWERS = "agy_superpowers"`
  - `DEEPSEEK_SUPERPOWERS = "deepseek_superpowers"`

- **Entidade `Project` (`painkiller/core/domain/models.py`)**:
  - `harness: HarnessType = HarnessType.AGY_SUPERPOWERS`
  - `api_key: Optional[str] = None`
  - Propriedade `masked_api_key`: mascara a chave para exibição pública na API (ex.: `sk-***abcd` ou `None`).

- **Persistência SQLite (`painkiller/adapters/issue_trackers/sqlite_tracker.py`)**:
  - Tabela `projects`: adiciona colunas `harness VARCHAR DEFAULT 'agy_superpowers'` e `api_key VARCHAR NULL`.
  - Migração retrocompatível automática via `PRAGMA table_info(projects)` caso as colunas não existam em bancos já criados.

### 2.2 Camada de API (`painkiller/api/routes/projects.py`)

- `CreateProjectRequest` e `UpdateProjectRequest`:
  - Aceitam os campos opcionais `harness: Optional[str]` e `api_key: Optional[str]`.
- Endpoints de consulta (`GET /api/projects`, `GET /api/projects/{id}`):
  - Retornam `harness` e o status da chave (`has_api_key: bool` ou `api_key` mascarado), garantindo que a credencial pura nunca seja exposta no payload HTTP.

### 2.3 Contêineres Docker e Imagens

São mantidas duas famílias de imagens isoladas na pasta `docker/`:

1. **Harness Antigravity (Existente)**:
   - `docker/agent.Dockerfile` (`painkiller-agent:latest`)
   - `docker/worker.Dockerfile` (`painkiller-worker:latest`)
   - Utiliza `agy` com Gemini 3.8 Flash e plugin Superpowers.

2. **Harness DeepSeek (Novo)**:
   - `docker/deepseek-agent.Dockerfile` (`painkiller-agent-deepseek:latest`):
     - Imagem base `node:22-slim` com Python 3, pip, curl, git.
     - Instalação do `@deepseek-ai/dsh` e montagem do plugin `superpowers`.
     - Instalação do CLI do painkiller (`painkiller agent-run` e `painkiller ask`).
     - Execução via streaming headless conectada à fila `.painkiller/agent-stdin.jsonl`.
   - `docker/deepseek-worker.Dockerfile` (`painkiller-worker-deepseek:latest`):
     - Imagem base com `@deepseek-ai/dsh`, plugin `superpowers`, pytest e CLI do painkiller.
     - Execução one-shot via `dsh --profile headless --json <instructions>`.

### 2.4 Resolução Dinâmica nos Adaptadores Docker

- **`DockerAgentSession` (`painkiller/adapters/sandbox/docker_agent_session.py`)**:
  - Recebe as propriedades do projeto (`harness` e `api_key`).
  - Quando `harness == "deepseek_superpowers"`:
    - Seleciona imagem `painkiller-agent-deepseek:latest`.
    - Injeta `DEEPSEEK_API_KEY` (chave do projeto ou `os.environ["DEEPSEEK_API_KEY"]`).
    - Validação antecipada: se nenhuma chave DeepSeek existir, lança `RuntimeError` com mensagem clara em pt-BR.
    - Parser de streaming: normaliza eventos JSON do `dsh` para `AgentEvent` (`ASSISTANT_DELTA`, `TOOL_USE`, `RESULT`).
  - Quando `harness == "agy_superpowers"`:
    - Mantém fluxo atual com `painkiller-agent:latest` e `GEMINI_API_KEY`.

- **`DockerSandboxRunner` (`painkiller/adapters/sandbox/docker_runner.py`)**:
  - Seleciona imagem `painkiller-worker-deepseek:latest` ou `painkiller-worker:latest` conforme `project.harness`.
  - Injeta a chave de API resolvida correspondente.
  - Mantém suporte universal ao protocolo de interrupção limpa (`painkiller ask` com exit code 42).

### 2.5 Interface Web (Frontend SvelteKit)

- **`web/src/lib/types.ts`**:
  - Tipagem `HarnessType = 'agy_superpowers' | 'deepseek_superpowers'`.
  - Atualização do tipo `Project` com `harness` e `has_api_key`.
- **`web/src/lib/components/ProjectDialog.svelte`**:
  - Seletor estilizado de Harness (Antigravity CLI vs DeepSeek Harness).
  - Campo de API Key com label dinâmico e mensagem informativa de fallback ao `.env`.
  - Integração na criação e na edição de projetos.

---

## 3. Protocolo de Interrupção Limpa (Exit 42)

O script `painkiller ask` permanece comum a ambos os contêineres:
- Ao atingir ambiguidade, o agente invoca `painkiller ask "<pergunta>"`.
- O script comita o trabalho em progresso e sai com status `42`.
- O `DockerSandboxRunner` identifica o código 42, lê `.painkiller/clarification.json` e transiciona a tarefa para `AWAITING_ANALYST`.

---

## 4. Plano de Validação e Testes

1. **Testes Unitários**:
   - `tests/unit/test_project_model.py` / `test_sqlite_tracker.py`:
     - Criação e atualização de projetos com diferentes harnesses e chaves.
     - Validação de mascaramento de chave e valores default.
   - `tests/unit/test_docker_agent_session.py`:
     - Verificação da injeção correta de credenciais e imagens para `deepseek_superpowers` e `agy_superpowers`.
     - Testes de erro amigável na ausência de chaves.
   - `tests/unit/test_docker_runner.py`:
     - Verificação do despacho de tarefas com a imagem e variáveis corretas.
2. **Checagem de Frontend**:
   - `npm run check` em `web/` com 0 erros.
