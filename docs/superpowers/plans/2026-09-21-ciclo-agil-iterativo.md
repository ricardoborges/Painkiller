# Ciclo Ágil Iterativo (Sessões, Backlog, Sprints, Artefatos e PDF) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refatorar o fluxo de construção de aplicações do Painkiller para um ciclo ágil iterativo baseado em sessões sequenciais (Sessão 1 criada automaticamente), contendo Análise, Backlog, Sprints (execução ativa) e Artefatos do Superpowers com visualização e download em PDF.

**Architecture:** A arquitetura hexagonal é estendida com a nova entidade `IterationSession` e suporte a `session_id` em `Task`. O `AnalysisOrchestrator` acumula contexto entre sessões. No frontend SvelteKit, o cabeçalho ganha um seletor de sessões com criação dinâmica, e as abas refletem as 4 fases da sessão (Análise, Backlog, Sprints, Artefatos) além de estilos `@media print` para exportação impecável em PDF.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy (Async SQLite), Pydantic v2, SvelteKit 2 + Svelte 5 (Runes), Plain CSS com tokens de design do Painkiller, Marked.js, Browser Print/PDF API.

**Spec:** [docs/superpowers/specs/2026-09-21-ciclo-agil-iterativo-design.md](file:///d:/dev/github/Painkiller/docs/superpowers/specs/2026-09-21-ciclo-agil-iterativo-design.md)

## Global Constraints

- Svelte 5 runes (`$state`, `$derived`, `$props`, `$effect`) devem ser usadas sem exceção;
- A paleta de cores do Painkiller é estritamente monocromática (tinta sobre papel), com a cor `--accent` (vermelho/laranja) reservada unicamente para estados de bloqueio do analista (`AWAITING_ANALYST` / exit 42);
- Zero border-radius, regras de 1px (`--rule-ink`, `--rule-2`), fontes Geist / Geist Mono;
- Código Python segue a separação: identifiers e docstrings em inglês; mensagens de erro, UI e prompts de LLM em português (pt-BR);
- A suite de testes `pytest` deve continuar passando com 100% de sucesso;
- `npm run check` em `web/` deve manter 0 erros.

---

### Task 1: Modelo de Domínio e Interface de Portas

**Files:**
- Modify: `painkiller/core/domain/models.py`
- Modify: `painkiller/core/ports/issue_tracker.py`
- Test: `tests/unit/test_domain_sessions.py`

**Interfaces:**
- Produces: `SessionStatus`, `IterationSession`, `Task.session_id`, e novos métodos em `IssueTrackerPort`:
  - `ensure_initial_session(project_id: str) -> IterationSession`
  - `create_session(project_id: str, title: Optional[str] = None) -> IterationSession`
  - `list_sessions(project_id: str) -> list[IterationSession]`
  - `get_session(session_id: str) -> Optional[IterationSession]`
  - `update_session(session: IterationSession) -> IterationSession`
  - `migrate_tasks_to_session(task_ids: list[str], target_session_id: str) -> list[Task]`

- [ ] **Step 1: Escrever teste unitário para `IterationSession` e `Task.session_id`**

Criar `tests/unit/test_domain_sessions.py`:
```python
import pytest
from painkiller.core.domain.models import IterationSession, SessionStatus, Task, TaskStatus

def test_iteration_session_creation():
    session = IterationSession(
        id="sess-1",
        project_id="proj-1",
        number=1,
        title="Sessão 1",
    )
    assert session.status == SessionStatus.PLANNING
    assert session.number == 1
    assert session.analysis_session_id is None

def test_task_has_session_id():
    task = Task(
        id="t-1",
        project_id="proj-1",
        title="Implementar autenticação",
        description="Criar fluxo de login",
        session_id="sess-1"
    )
    assert task.session_id == "sess-1"
```

- [ ] **Step 2: Rodar teste para verificar falha esperada**

Run: `pytest tests/unit/test_domain_sessions.py -v`
Expected: FAIL (`cannot import name 'IterationSession'`)

- [ ] **Step 3: Implementar `IterationSession` e atualizar `Task` e `IssueTrackerPort`**

Em `painkiller/core/domain/models.py`:
```python
class SessionStatus(str, Enum):
    PLANNING = "PLANNING"
    BACKLOG = "BACKLOG"
    IN_SPRINT = "IN_SPRINT"
    COMPLETED = "COMPLETED"

class IterationSession(BaseModel):
    id: str
    project_id: str
    number: int
    title: str
    status: SessionStatus = SessionStatus.PLANNING
    analysis_session_id: Optional[str] = None
    spec_path: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```
E em `Task`: adicionar `session_id: Optional[str] = None`.

Em `painkiller/core/ports/issue_tracker.py`, adicionar assinaturas abstratas de sessões.

- [ ] **Step 4: Rodar teste para verificar sucesso**

Run: `pytest tests/unit/test_domain_sessions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add painkiller/core/domain/models.py painkiller/core/ports/issue_tracker.py tests/unit/test_domain_sessions.py
git commit -m "feat(domain): adicionar entidade IterationSession e session_id em Task"
```

---

### Task 2: Implementação da Persistência no SQLite Tracker

**Files:**
- Modify: `painkiller/adapters/issue_trackers/sqlite_tracker.py`
- Test: `tests/unit/test_sqlite_tracker_sessions.py`

**Interfaces:**
- Consumes: `IterationSession`, `SessionStatus`, `Task`
- Produces: Implementações concretas de `ensure_initial_session`, `create_session`, `list_sessions`, `get_session`, `update_session`, `migrate_tasks_to_session`, e filtro `session_id` em `list_tasks`.

- [ ] **Step 1: Escrever teste de persistência do SQLite Tracker**

Criar `tests/unit/test_sqlite_tracker_sessions.py`:
```python
import pytest
from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker
from painkiller.core.domain.models import Project, TaskStatus, SessionStatus

@pytest.mark.asyncio
async def test_ensure_initial_session_and_incremental_creation():
    tracker = SQLiteIssueTracker("sqlite+aiosqlite:///:memory:")
    await tracker.init_db()

    project = await tracker.create_project(
        name="Teste",
        repo_path="/tmp/test",
        description="Desc",
        purpose="Prop",
        solution_description="Sol",
    )

    # Primeira chamada deve criar Sessão 1
    s1 = await tracker.ensure_initial_session(project.id)
    assert s1.number == 1
    assert s1.title == "Sessão 1"
    assert s1.status == SessionStatus.PLANNING

    # Chamada subsequente retorna a existente
    s1_again = await tracker.ensure_initial_session(project.id)
    assert s1_again.id == s1.id

    # Criar nova sessão deve gerar Sessão 2
    s2 = await tracker.create_session(project.id)
    assert s2.number == 2
    assert s2.title == "Sessão 2"

    sessions = await tracker.list_sessions(project.id)
    assert len(sessions) == 2
    assert [s.number for s in sessions] == [1, 2]
```

- [ ] **Step 2: Rodar teste para verificar que falha**

Run: `pytest tests/unit/test_sqlite_tracker_sessions.py -v`
Expected: FAIL (`AttributeError: 'SQLiteIssueTracker' object has no attribute 'ensure_initial_session'`)

- [ ] **Step 3: Implementar tabela e métodos no `sqlite_tracker.py`**

Adicionar `IterationSessionRecord` na base declarativa do SQLAlchemy, mapeando para tabela `iteration_sessions`, atualizar `TaskRecord` com coluna `session_id`, e implementar os métodos no `SQLiteIssueTracker`.

- [ ] **Step 4: Rodar testes do tracker**

Run: `pytest tests/unit/test_sqlite_tracker_sessions.py tests/unit/test_sqlite_tracker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add painkiller/adapters/issue_trackers/sqlite_tracker.py tests/unit/test_sqlite_tracker_sessions.py
git commit -m "feat(tracker): persistir iteration_sessions e vincular tarefas a sessoes no sqlite"
```

---

### Task 3: Atualização do Engine de Análise (`AnalysisOrchestrator`)

**Files:**
- Modify: `painkiller/engine/analysis.py`
- Test: `tests/unit/test_analysis_sessions.py`

**Interfaces:**
- Consumes: `IssueTrackerPort`, `IterationSession`
- Produces: `AnalysisOrchestrator.start(..., session_id: Optional[str] = None)` e `commit_backlog` registrando tarefas com o `session_id` e atualizando o status da `IterationSession`.

- [ ] **Step 1: Escrever teste para orquestração de análise com sessão**

Criar `tests/unit/test_analysis_sessions.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from painkiller.engine.analysis import AnalysisOrchestrator
from painkiller.core.domain.models import Project, IterationSession, SessionStatus

@pytest.mark.asyncio
async def test_commit_backlog_associates_tasks_to_iteration_session(tmp_path):
    tracker = AsyncMock()
    agent = AsyncMock()
    orchestrator = AnalysisOrchestrator(agent=agent, tracker=tracker)

    # Configurar repo falso com .painkiller/backlog.json
    repo = tmp_path / "repo"
    repo.mkdir()
    pk_dir = repo / ".painkiller"
    pk_dir.mkdir()
    (pk_dir / "backlog.json").write_text(
        '{"spec_path": "docs/superpowers/specs/spec.md", "tasks": [{"title": "T1", "description": "D1"}]}',
        encoding="utf-8"
    )

    session = IterationSession(id="sess-1", project_id="proj-1", number=1, title="Sessão 1")
    tracker.get_session.return_value = session
    tracker.create_task.return_value = MagicMock(id="task-1", title="T1")

    # Mock AnalysisRun
    run = MagicMock(repo_path=str(repo), session=MagicMock(project_id="proj-1", id="an-1"))
    orchestrator.runs["an-1"] = run

    await orchestrator.commit_backlog("an-1", iteration_session_id="sess-1")

    tracker.create_task.assert_called_once()
    assert tracker.create_task.call_args.kwargs.get("session_id") == "sess-1"
    tracker.update_session.assert_called_once()
```

- [ ] **Step 2: Rodar teste para verificar falha**

Run: `pytest tests/unit/test_analysis_sessions.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar suporte a `iteration_session_id` no `analysis.py`**

Modificar `AnalysisOrchestrator.start` e `commit_backlog` para associar o `iteration_session_id`, registrar tarefas vinculadas à sessão e atualizar o status da sessão para `BACKLOG`.

- [ ] **Step 4: Rodar teste e validar**

Run: `pytest tests/unit/test_analysis_sessions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add painkiller/engine/analysis.py tests/unit/test_analysis_sessions.py
git commit -m "feat(analysis): vincular execucao e backlog do superpowers a IterationSession"
```

---

### Task 4: Endpoints REST da API para Sessões

**Files:**
- Create: `painkiller/api/routes/sessions.py`
- Modify: `painkiller/api/server.py`
- Modify: `painkiller/api/routes/projects.py`
- Test: `tests/integration/test_sessions_api.py`

**Interfaces:**
- Produces rotas:
  - `GET /api/projects/{id}/sessions` (lista com auto-criação da Sessão 1)
  - `POST /api/projects/{id}/sessions` (cria próxima sessão)
  - `GET /api/projects/{id}/sessions/{sid}`
  - `PATCH /api/projects/{id}/sessions/{sid}`
  - `GET /api/projects/{id}/sessions/{sid}/tasks`
  - `GET /api/projects/{id}/sessions/{sid}/artifacts`
  - `POST /api/projects/{id}/sessions/{sid}/migrate-tasks`

- [ ] **Step 1: Escrever teste de integração da API de sessões**

Criar `tests/integration/test_sessions_api.py`:
```python
import pytest
from httpx import AsyncClient, ASGITransport
from painkiller.api.server import create_app

@pytest.mark.asyncio
async def test_sessions_crud_and_auto_creation():
    app = create_app(db_url="sqlite+aiosqlite:///:memory:")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Criar projeto
        resp = await client.post("/api/projects", json={
            "name": "App Iterativo",
            "repo_path": "/tmp/test",
            "description": "App",
            "purpose": "Teste",
            "solution_description": "Sol"
        })
        assert resp.status_code == 201
        proj_id = resp.json()["id"]

        # Listar sessões -> deve auto-criar Sessão 1
        resp = await client.get(f"/api/projects/{proj_id}/sessions")
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) == 1
        assert sessions[0]["number"] == 1
        assert sessions[0]["title"] == "Sessão 1"

        # Criar Sessão 2
        resp = await client.post(f"/api/projects/{proj_id}/sessions")
        assert resp.status_code == 201
        s2 = resp.json()
        assert s2["number"] == 2
        assert s2["title"] == "Sessão 2"
```

- [ ] **Step 2: Rodar teste para verificar falha**

Run: `pytest tests/integration/test_sessions_api.py -v`
Expected: FAIL (404 Not Found)

- [ ] **Step 3: Implementar `painkiller/api/routes/sessions.py` e plugar em `server.py`**

Escrever o router FastAPI com todas as rotas listadas, tratamento de erros e injeção do tracker.

- [ ] **Step 4: Rodar teste para verificar aprovação**

Run: `pytest tests/integration/test_sessions_api.py -v`
Expected: PASS

- [ ] **Step 5: Rodar suite inteira de testes backend**

Run: `pytest`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add painkiller/api/routes/sessions.py painkiller/api/server.py tests/integration/test_sessions_api.py
git commit -m "feat(api): adicionar endpoints para gestao de sessoes iterativas"
```

---

### Task 5: Cliente Frontend (Tipos, API e Session Store)

**Files:**
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/lib/api.ts`
- Create: `web/src/lib/stores/session.svelte.ts`
- Test: `cd web && npm run check`

**Interfaces:**
- Produces: `IterationSession`, `SessionStatus`, métodos `api.listSessions`, `api.createSession`, `api.getSession`, `api.listSessionTasks`, `api.listSessionArtifacts`, `api.migrateTasksToSession`, e store reativo de sessão ativa.

- [ ] **Step 1: Atualizar `types.ts` com interfaces de Sessão**

Adicionar `SessionStatus`, `IterationSession`, atualizar `Task` com `session_id?: string`.

- [ ] **Step 2: Adicionar métodos em `api.ts`**

Adicionar chamadas HTTP tipadas para os novos endpoints `/api/projects/{id}/sessions/...`.

- [ ] **Step 3: Criar store reativa `web/src/lib/stores/session.svelte.ts`**

Implementar gerenciador com runes (`$state`) para manter a sessão ativa por projeto, sincronizada com URL ou localStorage.

- [ ] **Step 4: Verificar tipagem com `npm run check`**

Run: `cd web && npm run check`
Expected: 0 errors

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/types.ts web/src/lib/api.ts web/src/lib/stores/session.svelte.ts
git commit -m "feat(web): adicionar tipos, chamadas de api e store reativa de sessoes"
```

---

### Task 6: Seletor de Sessões e Layout do Projeto

**Files:**
- Modify: `web/src/routes/projetos/[id]/+layout.svelte`
- Create: `web/src/lib/components/SessionSelector.svelte`

**Interfaces:**
- Produces: Barra de sessões com lista de sessões (`Sessão 1`, `Sessão 2`...), botão `+ Nova sessão`, e navegação adaptada para as 4 etapas da sessão: `1 Análise`, `2 Backlog`, `3 Sprints`, `4 Artefatos`, além das guias de apoio `Contexto` e `Custos`.

- [ ] **Step 1: Criar componente `SessionSelector.svelte`**

Construir componente editorial monocromático com botões de cada sessão, badge de status e botão para disparar nova sessão.

- [ ] **Step 2: Atualizar `web/src/routes/projetos/[id]/+layout.svelte`**

Integrar o `SessionSelector`, atualizar as abas de navegação para:
- `1 Análise`: `${base}/analise-inicial`
- `2 Backlog`: `${base}/backlog`
- `3 Sprints`: `${base}/sprints`
- `4 Artefatos`: `${base}/artefatos`
E abas de apoio: `Contexto` (`${base}`) e `Custos` (`${base}/custos`).

- [ ] **Step 3: Validar com `npm run check`**

Run: `cd web && npm run check`
Expected: 0 errors

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/components/SessionSelector.svelte web/src/routes/projetos/[id]/+layout.svelte
git commit -m "feat(web): implementar seletor de sessoes e novo fluxo de navegacao agil"
```

---

### Task 7: Tela de Sprints (Execução das Tarefas da Sessão) e Backlog

**Files:**
- Create: `web/src/routes/projetos/[id]/sprints/+page.svelte`
- Modify: `web/src/routes/projetos/[id]/backlog/+page.svelte`

**Interfaces:**
- Produces:
  - `sprints/+page.svelte`: Painel de execução das tarefas da sessão selecionada (disparo de workers, relógio em tempo real, logs ao vivo, revisão e clarificação exit 42).
  - `backlog/+page.svelte`: Focado no planejamento e decomposição das tarefas da sessão, com botão para avançar para a Sprint ou migrar tarefas não concluídas de sessões anteriores.

- [ ] **Step 1: Implementar `web/src/routes/projetos/[id]/sprints/+page.svelte`**

Reaproveitar os componentes de execução (`Elapsed.svelte`, dispatch de tarefas, modais de log e clarificação) focados exclusivamente nas tarefas da sessão ativa.

- [ ] **Step 2: Ajustar `web/src/routes/projetos/[id]/backlog/+page.svelte`**

Filtrar as tarefas pela sessão ativa, adicionar ação rápida de migrar tarefas pendentes de sessões anteriores e botão para ir para a execução em Sprints.

- [ ] **Step 3: Validar com `npm run check`**

Run: `cd web && npm run check`
Expected: 0 errors

- [ ] **Step 4: Commit**

```bash
git add web/src/routes/projetos/[id]/sprints/+page.svelte web/src/routes/projetos/[id]/backlog/+page.svelte
git commit -m "feat(web): implementar tela de sprints e refatorar backlog por sessao"
```

---

### Task 8: Artefatos Vinculados à Sessão e Exportação para PDF

**Files:**
- Modify: `web/src/routes/projetos/[id]/artefatos/+page.svelte`
- Modify: `web/src/lib/components/DocViewer.svelte`

**Interfaces:**
- Produces:
  - Listagem dos artefatos do Superpowers filtrados pela sessão selecionada.
  - Botão **"Baixar como PDF"** no visualizador `DocViewer.svelte`.
  - Folha de estilo `@media print` com formatação editorial profissional (cabeçalho da sessão/projeto, numeração de páginas, quebra limpa de blocos de código).

- [ ] **Step 1: Adicionar estilos `@media print` e ação de PDF no `DocViewer.svelte`**

Adicionar botão com ícone de download/impressão e método que dispara `window.print()` com estilos `@media print` dedicados.

- [ ] **Step 2: Atualizar `artefatos/+page.svelte` para vincular à sessão ativa**

Exibir os artefatos correspondentes à sessão ativa atual, com link para o visualizador com PDF.

- [ ] **Step 3: Validar com `npm run check` e testar build do frontend**

Run: `cd web && npm run check && npm run build`
Expected: Build concluído com sucesso e 0 erros.

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/components/DocViewer.svelte web/src/routes/projetos/[id]/artefatos/+page.svelte
git commit -m "feat(web): adicionar download como PDF no visualizador e filtrar artefatos por sessao"
```

---

## Plan Self-Review Checklist

1. **Spec coverage**:
   - Ciclo ágil iterativo (Sessões): Coberto nas Tasks 1, 2, 4, 5, 6.
   - Sessão 1 criada automaticamente: Coberto nas Tasks 2, 4.
   - IDs incrementais (Sessão 1, 2...): Coberto nas Tasks 1, 2, 4.
   - Divisão em Análise, Backlog, Sprints: Coberto nas Tasks 6, 7.
   - Artefatos vinculados à sessão: Coberto nas Tasks 3, 4, 8.
   - Visualização e download em PDF: Coberto na Task 8.
2. **No Placeholders**: Sem TODOs ou TBDs; comandos exatos de teste e código especificados.
3. **Type consistency**: Tipos `IterationSession`, `SessionStatus`, `Task.session_id` uniformes entre Python e TypeScript.
