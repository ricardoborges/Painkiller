# Painkiller - Especificação de Arquitetura e Design da Plataforma

**Data**: 2026-09-19  
**Status**: Aprovado  
**Versão**: 1.0.0  

---

## 1. Visão Geral e Objetivos

O **Painkiller** é uma plataforma automatizada para orquestração de desenvolvimento de software baseada em agentes inteligentes, inspirada na dinâmica de trabalho do Devin, porém com foco em:
1. **Interrogação Ativa de Requisitos ("Superpowers")**: Elicitação guiada com o analista técnico/PO, gerando especificações rigorosas e decomposição em backlog atômico.
2. **Issue Tracker & Kanban Pluggável**: Arquitetura Hexagonal com adaptadores desacoplados para SQLite local, Redmine, GitLab e GitHub.
3. **Execução Segura e Efêmera**: Harness de codificação autônoma (Aider Headless) executado dentro de contêineres Docker isolados por tarefa.
4. **Protocolo de Interrupção Limpa**: Pausa determinística via script CLI (`painkiller ask`) quando o agente de codificação tiver dúvidas, commitando o estado intermediário e notificando a issue sem desperdício de tokens ou travamento de workers.
5. **Consumo Unificado de Modelos**: Interface agnóstica multi-provedor (LiteLLM) para separar modelos de raciocínio/planejamento de modelos de codificação.

---

## 2. Arquitetura do Sistema (Ports & Adapters)

O sistema segue a **Arquitetura Hexagonal**, garantindo que o domínio e as regras de negócio sejam completamente independentes de bibliotecas externas, bancos de dados e provedores de contêiner ou LLM.

```
                  ┌────────────────────────────────────────┐
                  │          Painkiller Core               │
                  │                                        │
┌──────────────┐  │  ┌──────────────┐    ┌──────────────┐  │  ┌────────────────────┐
│ HTTP / API   │─▶│  │ Task Engine  │─-─▶│ Domain Model │  │  │ IssueTrackerPort   │
└──────────────┘  │  │ & State Mach.│    │ (Task, Proj) │  │  │ (SQLite, Redmine)  │
                  │  └───────┬──────┘    └──────────────┘  │  └─────────┬──────────┘
                  │          │                             │            │
                  │          ▼                             │            ▼
                  │  ┌──────────────┐                      │  ┌────────────────────┐
                  │  │ WorkerRunner │                      │  │ SandboxPort        │
                  │  └──────────────┘                      │  │ (DockerRunner)     │
                  └──────────┬─────────────────────────────┘  └─────────┬──────────┘
                             │                                          │
                             ▼                                          ▼
                      ┌──────────────┐                        ┌────────────────────┐
                      │ LLMPort      │                        │ GitPort            │
                      │ (LiteLLM)    │                        │ (Git CLI / Python) │
                      └──────────────┘                        └────────────────────┘
```

### 2.1 Estrutura de Diretórios Proposta

```
painkiller/
├── core/
│   ├── domain/           # Entidades (Project, Task, ClarificationRequest, ExecutionLog)
│   ├── ports/            # Interfaces abstratas (IssueTrackerPort, SandboxPort, GitPort, LLMPort)
│   └── events/           # Eventos de domínio (TaskCreated, ExecutionInterrupted, TaskCompleted)
├── adapters/
│   ├── issue_trackers/   # SQLiteTracker (referência), RedmineTracker, GitLabTracker
│   ├── sandbox/          # DockerSandboxRunner
│   ├── git/              # GitCliAdapter
│   └── llm/              # LiteLLMAdapter
├── engine/
│   ├── orchestrator.py   # Despachante assíncrono e máquina de estados de tarefas
│   └── lifecycle.py      # Gestão de contêineres e retomada após esclarecimento
├── interrogation/
│   ├── wizard.py         # Máquina de entrevista iterativa de requisitos
│   └── decomposer.py     # Decompositor de especificações em backlog atômico estruturado
├── api/
│   ├── server.py         # FastAPI App
│   ├── routes/           # Rotas REST (/projects, /tasks, /interrogation)
│   ├── websockets.py     # Streaming de logs e eventos em tempo real
│   └── static/           # Dashboard Web minimalista e moderno
├── docker/
│   ├── worker.Dockerfile # Imagem do worker Aider com CLI painkiller injetada
│   └── entrypoint.sh     # Script de inicialização e captura de sinais
├── tests/
│   ├── unit/             # Testes unitários com Mocks
│   ├── integration/      # Testes de adaptadores e API
│   └── e2e/              # Testes completos com contêiner Docker
├── pyproject.toml
└── README.md
```

---

## 3. Contratos de Portas e Domínio

### 3.1 Entidades de Domínio
- **`Project`**: `id`, `name`, `repo_path`, `default_branch`, `settings`.
- **`Task`**: `id`, `project_id`, `title`, `description`, `target_files`, `acceptance_criteria`, `status`, `assigned_branch`, `created_at`, `updated_at`.
- **`TaskStatus`**:
  - `BACKLOG`
  - `READY`
  - `RUNNING`
  - `AWAITING_ANALYST`
  - `IN_REVIEW`
  - `COMPLETED`
  - `FAILED`
- **`ClarificationRequest`**: `id`, `task_id`, `question`, `context_summary`, `status` (`PENDING`, `ANSWERED`), `answer`, `timestamp`.

### 3.2 Portas Principais
- **`IssueTrackerPort`**:
  - `get_task(task_id: str) -> Task`
  - `list_tasks(project_id: str, status: TaskStatus | None) -> list[Task]`
  - `update_task_status(task_id: str, status: TaskStatus) -> None`
  - `add_comment(task_id: str, author: str, comment: str) -> None`
  - `create_task(project_id: str, title: str, description: str, ...) -> Task`
  - `create_clarification_question(task_id: str, question: str, context: str) -> ClarificationRequest`
  - `resolve_clarification(clarification_id: str, answer: str) -> None`
- **`SandboxPort`**:
  - `run_task_environment(task: Task, repo_path: str, instructions: str, timeout_seconds: int) -> ExecutionResult`
  - `stop_task_environment(task_id: str) -> None`
- **`GitPort`**:
  - `ensure_branch(repo_path: str, branch_name: str, base_branch: str) -> None`
  - `commit_wip(repo_path: str, message: str) -> str`
  - `get_diff(repo_path: str, base_branch: str) -> str`
  - `create_pull_request(repo_path: str, title: str, body: str, head: str, base: str) -> str`
- **`LLMPort`**:
  - `complete(prompt: str, model: str, temperature: float) -> str`
  - `structured_output(prompt: str, response_model: type[T], model: str) -> T`

---

## 4. Sandbox Docker e Protocolo de Execução do Aider

### 4.1 Imagem Docker do Worker
- Base: `python:3.11-slim` (com `git`, `curl`, `nodejs`, `npm`, `pytest` pré-instalados).
- Pacotes: `aider-chat`.
- Injeção da CLI `painkiller`:
  - Script executável em `/usr/local/bin/painkiller`.
  - Execução: `painkiller ask "<pergunta>"`:
    1. Grava `/.painkiller/clarification.json` no workspace compartilhado.
    2. Executa `git add -A && git commit -m "wip: paused for clarification"`.
    3. Finaliza o processo com código de saída `exit 42`.

### 4.2 Execução no Orquestrador
- O orquestrador monta o repositório clonado em volume temporário no Docker.
- Invoca o Aider com:
  ```bash
  aider --message "$TASK_INSTRUCTIONS" --yes --no-check-update
  ```
- O orquestrador avalia o retorno do contêiner:
  - **Exit Code 0**: Roda testes de aceitação. Se passarem, cria PR e move a tarefa para `IN_REVIEW`.
  - **Exit Code 42**: Lê `clarification.json`, publica a dúvida na issue do tracker, muda status da tarefa para `AWAITING_ANALYST` e encerra o contêiner.
  - **Outro Exit Code / Erro de Teste**: Se testes falharem, envia o log de erro para o Aider tentar auto-correção (até 3 tentativas). Se esgotadas, move a tarefa para `FAILED` com relatório.

---

## 5. Módulo de Interrogação de Requisitos ("Superpowers")

1. **Sessão de Elicitação**:
   - Diálogo estruturado com o analista humano, formulando uma pergunta por vez.
   - Investiga escopo, tecnologias, endpoints, contratos de dados e tratamento de exceções.
2. **Síntese de Especificação**:
   - Compilação de um documento markdown unificado com a arquitetura validada.
3. **Decomposição em Backlog Atômico**:
   - Utilização de `LLMPort.structured_output` para mapear tarefas atômicas independentes com seus critérios de aceitação, arquivos alvo e ordem de dependência.
4. **Disparo para o Tracker**:
   - Criação automática das issues no `IssueTrackerPort` com status inicial `BACKLOG` e a primeira tarefa pronta com `READY`.

---

## 6. API, Interface Web e WebSockets

- **API REST (FastAPI)**:
  - Gerenciamento de projetos, tarefas, sessões de interrogação e respostas de esclarecimento.
- **WebSockets (`/ws/events`)**:
  - Transmissão em tempo real de logs do contêiner Docker e atualizações visuais dos cards.
- **Interface Web**:
  - Painel com Wizard de Interrogação, Quadro Kanban reativo e leitor de diffs/logs em tempo real.

---

## 7. Estratégia de Testes e Validação

- **Testes Unitários**:
  - Cobertura completa das regras de transição de estado de tarefas, parsing do protocolo `clarification.json` e serialização do backlog via Pydantic.
- **Testes de Integração**:
  - Validação do adaptador SQLite, rotas FastAPI e comandos Git locais.
- **Testes End-to-End**:
  - Execução de um cenário de teste com contêiner Docker real executando o Aider e capturando a interrupção limpa.
