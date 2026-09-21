# Especificação Técnica: Ciclo Ágil Iterativo (Sessões, Backlog, Sprints, Artefatos e PDF)

- **Data**: 2026-09-21
- **Status**: Aprovado
- **Autor**: Painkiller Core Team

---

## 1. Visão Geral

Atualmente, o Painkiller opera sobre um fluxo linear fixo por projeto: `1 Contexto → 2 Análise inicial → 3 Backlog` com visualização de tarefas única e global.

Esta especificação transforma o ciclo de desenvolvimento de software em um **fluxo ágil iterativo baseado em Sessões**, permitindo ciclos sucessivos de melhoria e expansão do software com histórico cumulativo:
- Cada projeto é composto por **Sessões** incrementais (`Sessão 1`, `Sessão 2`, `Sessão 3`, ...).
- Ao abrir o projeto pela primeira vez, a **Sessão 1** é criada automaticamente.
- Cada sessão possui seu próprio ciclo interno composto por:
  1. **Análise**: Elicitação de requisitos e brainstorming com agente Claude/Antigravity (`superpowers:brainstorming`), com contexto cumulativo das sessões anteriores.
  2. **Backlog**: Tarefas geradas e decompostas para a iteração, com critérios de aceitação e dependências.
  3. **Sprints**: Painel de execução e acompanhamento ativo das tarefas daquela sessão (disparo de workers Aider, logs ao vivo, cronômetro e tratamento de esclarecimentos exit 42).
  4. **Artefatos**: Documentos gerados pelo Superpowers vinculados especificamente à sessão (especificações de design, planos de implementação e backlog JSON), com capacidade de visualização e exportação para PDF.

---

## 2. Modelo de Domínio e Banco de Dados

### 2.1. Entidade `IterationSession`

Localizada em `painkiller/core/domain/models.py`:

```python
class SessionStatus(str, Enum):
    PLANNING = "PLANNING"     # Em análise / elicitação
    BACKLOG = "BACKLOG"       # Backlog gerado e em refinamento
    IN_SPRINT = "IN_SPRINT"   # Tarefas em execução ativa
    COMPLETED = "COMPLETED"   # Sessão finalizada

class IterationSession(BaseModel):
    id: str                                  # ex: "sess-<uuid8>"
    project_id: str
    number: int                              # 1, 2, 3... sequencial por projeto
    title: str                               # "Sessão 1", "Sessão 2", etc.
    status: SessionStatus = SessionStatus.PLANNING
    analysis_session_id: Optional[str] = None
    spec_path: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### 2.2. Atualização em `Task`

O modelo `Task` recebe o campo:
```python
session_id: Optional[str] = None
```
Tarefas existentes sem `session_id` são vinculadas à `Sessão 1` do respectivo projeto no momento da inicialização/migração.

### 2.3. Persistência SQLite (`sqlite_tracker.py`)

- Nova tabela `iteration_sessions`:
  - `id`: `String, primary_key=True`
  - `project_id`: `String, nullable=False, index=True`
  - `number`: `Integer, nullable=False`
  - `title`: `String, nullable=False`
  - `status`: `SQLEnum(SessionStatus), default=SessionStatus.PLANNING`
  - `analysis_session_id`: `String, nullable=True`
  - `spec_path`: `String, nullable=True`
  - `created_at`: `DateTime, default=now`
  - `updated_at`: `DateTime, default=now`
- Adição da coluna `session_id` (`String, nullable=True, index=True`) na tabela `tasks`.

### 2.4. Porta `IssueTrackerPort`

Novos métodos assíncronos:
- `ensure_initial_session(project_id: str) -> IterationSession`
- `create_session(project_id: str, title: Optional[str] = None) -> IterationSession`
- `list_sessions(project_id: str) -> list[IterationSession]`
- `get_session(session_id: str) -> Optional[IterationSession]`
- `update_session(session: IterationSession) -> IterationSession`
- `list_tasks(project_id: str, session_id: Optional[str] = None) -> Sequence[Task]`
- `migrate_tasks_to_session(task_ids: list[str], target_session_id: str) -> list[Task]`

---

## 3. Engine e Endpoints da API

### 3.1. Auto-criação e Ciclo de Vida
1. Ao invocar `GET /api/projects/{id}/sessions`, se a lista de sessões for vazia, `ensure_initial_session(project_id)` cria automaticamente a `Sessão 1` (status `PLANNING`). Tarefas legadas órfãs são migradas para esta sessão.
2. `POST /api/projects/{id}/sessions` cria a próxima sessão incremental com `number = max(numbers) + 1` e título `"Sessão {number}"`.

### 3.2. Integração com Análise (`AnalysisOrchestrator`)
- `POST /api/projects/{id}/analysis` aceita `session_id: Optional[str]`.
- Quando omitido, associa à sessão ativa mais recente.
- `build_analysis_prompt(project, session_number, previous_sessions_summary)`:
  - Para sessões N > 1, injeta um bloco contextual informando quais especificações e tarefas foram implementadas em sessões anteriores e que a iteração atual deve evoluir ou refinar o software existente.
- Quando `commit_backlog` é acionado:
  - As tarefas criadas no banco de dados recebem o `session_id` da iteração correspondente.
  - A `IterationSession` tem seu `spec_path` gravado e seu status atualizado para `BACKLOG`.

### 3.3. Endpoints REST

| Método | Caminho | Descrição |
|---|---|---|
| `GET` | `/api/projects/{id}/sessions` | Lista sessões do projeto (com contagem de tarefas e progresso) |
| `POST` | `/api/projects/{id}/sessions` | Cria a próxima sessão incremental |
| `GET` | `/api/projects/{id}/sessions/{sid}` | Retorna detalhes da sessão |
| `PATCH` | `/api/projects/{id}/sessions/{sid}` | Atualiza título ou status da sessão |
| `GET` | `/api/projects/{id}/sessions/{sid}/tasks` | Lista tarefas da sessão |
| `GET` | `/api/projects/{id}/sessions/{sid}/artifacts` | Lista artefatos vinculados à sessão |
| `POST` | `/api/projects/{id}/sessions/{sid}/migrate-tasks` | Migra tarefas pendentes para esta sessão |

---

## 4. Frontend e Experiência do Usuário (UI/UX)

### 4.1. Seletor de Sessões no Cabeçalho
No layout de projeto (`web/src/routes/projetos/[id]/+layout.svelte`):
- Exibição de régua de sessões no topo:
  - Abas/pills com cada sessão (`Sessão 1`, `Sessão 2`...), exibindo estado sutil.
  - Botão `+ Nova sessão` à direita, com confirmação rápida e transição fluida.
  - A sessão ativa é preservada na URL (`?sessao={id}` ou rota dedicada).

### 4.2. Abas do Ciclo Ágil Iterativo
Sob a sessão selecionada, a navegação apresenta os 4 passos do ciclo:
1. **1 Análise** (`/projetos/[id]/analise-inicial`): Chat de elicitação com o agente Claude/Antigravity (`superpowers:brainstorming`).
2. **2 Backlog** (`/projetos/[id]/backlog`): Lista de tarefas da sessão com seus critérios de aceitação e dependências. Botão de importação e de migração de tarefas de sessões anteriores.
3. **3 Sprints** (`/projetos/[id]/sprints`): Painel de execução das tarefas da sessão (disparo de workers, relógio de execução, logs, diffs e atendimento a dúvidas).
4. **4 Artefatos** (`/projetos/[id]/artefatos`): Documentos gerados durante a sessão ativa (especificação `docs/superpowers/specs/`, planos de implementação e backlog JSON).
- Abas utilitárias do projeto: **Contexto** e **Custos** mantêm-se acessíveis.

### 4.3. Visualizador de Documentos com Exportação para PDF
No componente `DocViewer.svelte`:
- Adição do botão **"Baixar como PDF"** no cabeçalho do modal/visualizador.
- Implementação via estilos dedicados `@media print` e acionamento de `window.print()`:
  - Formatação tipográfica editorial de alta legibilidade (Geist Sans para texto, Geist Mono para código).
  - Quebra de página inteligente (`page-break-inside: avoid` em blocos de código e seções).
  - Cabeçalho de impressão com Nome do Projeto, Identificação da Sessão e Data de Emissão.
  - Ocultação automática de botões, modais e barras de ferramentas durante a geração do PDF.

---

## 5. Plano de Validação e Testes

- **Testes Unitários de Backend (`pytest`)**:
  - Testar criação atômica e autoincremental de sessões (`ensure_initial_session`, `create_session`).
  - Testar vínculo de tarefas a sessões e listagem filtrada por `session_id`.
  - Testar `commit_backlog` associando tarefas e `spec_path` à sessão corrente.
  - Testar injeção de contexto cumulativo no prompt de análise para sessões subsequentes.
- **Testes de Integração e Frontend**:
  - Validar `npm run check` no diretório `web/` garantindo 0 erros de TypeScript/Svelte 5.
  - Validar carregamento do projeto sem sessões prévias (criação automática da Sessão 1).
  - Validar alternância entre Sessão 1 e Sessão 2.
  - Validar renderização de artefatos e acionamento da exportação de PDF.
