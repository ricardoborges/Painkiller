# Menu Lateral Retrátil de Sessões (Estilo Devin) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refatorar o seletor de sessões ágeis do Painkiller para uma barra lateral retrátil (sidebar / mini-rail) inspirada no menu do Devin, permitindo alternar entre modo expandido (240px) e recolhido (48px) com persistência no navegador.

**Architecture:** A primitivas de ícones ganham o novo glifo `sidebar`. É criado o componente `SessionSidebar.svelte` que gerencia o estado `collapsed` sincronizado com `localStorage`. O layout do projeto em `routes/projetos/[id]/+layout.svelte` é reestruturado em duas colunas (sidebar à esquerda + conteúdo do projeto à direita), com suporte responsivo para mobile.

**Tech Stack:** SvelteKit 2, Svelte 5 (Runes: `$props`, `$state`, `$derived`, `$effect`), Plain CSS com tokens do Painkiller, TypeScript, `localStorage`.

**Spec:** [docs/superpowers/specs/2026-09-21-menu-lateral-retratil-sessoes-design.md](file:///d:/dev/github/Painkiller/docs/superpowers/specs/2026-09-21-menu-lateral-retratil-sessoes-design.md)

## Global Constraints

- Svelte 5 runes (`$state`, `$derived`, `$props`, `$effect`) devem ser usadas sem exceção;
- A paleta de cores é estritamente monocromática (`--paper`, `--paper-2`, `--rule-ink`, `--rule-2`, `--ink`, `--ink-2`, `--ink-3`);
- Zero `border-radius`, regras de 1px (`--rule-ink`, `--rule-2`), fontes Geist / Geist Mono;
- Preservar a persistência do estado `collapsed` em `localStorage` (`painkiller_sessions_sidebar_collapsed`);
- `npm run check` na pasta `web/` deve manter 0 erros.

---

### Task 1: Ícone `sidebar` em `Icon.svelte`

**Files:**
- Modify: `web/src/lib/components/Icon.svelte`

**Interfaces:**
- Produces: Novo valor `'sidebar'` no tipo `Name` de `Icon.svelte`.

- [x] **Step 1: Adicionar `'sidebar'` ao tipo `Name` e SVG correspondente**
- [x] **Step 2: Verificar checagem de tipos**
- [x] **Step 3: Commit**

---

### Task 2: Componente `SessionSidebar.svelte`

**Files:**
- Create: `web/src/lib/components/SessionSidebar.svelte`

**Interfaces:**
- Consumes: `Icon.svelte`, `IterationSession` de `$lib/types`
- Produces: `SessionSidebar` component com props `{ sessions, activeSessionId, loading, creating, onselect, oncreate }`

- [x] **Step 1: Implementar o componente `SessionSidebar.svelte`**
- [x] **Step 2: Validar tipos com `npm run check`**
- [x] **Step 3: Commit**

---

### Task 3: Integração no Layout do Projeto (`routes/projetos/[id]/+layout.svelte`)

**Files:**
- Modify: `web/src/routes/projetos/[id]/+layout.svelte`
- Delete: `web/src/lib/components/SessionSelector.svelte`

**Interfaces:**
- Consumes: `SessionSidebar` de `$lib/components/SessionSidebar.svelte`

- [x] **Step 1: Atualizar `web/src/routes/projetos/[id]/+layout.svelte`**
- [x] **Step 2: Validar tipos com `npm run check`**
- [x] **Step 3: Commit**

---

### Task 4: Verificação Completa e Build

**Files:**
- None (apenas verificação)

- [x] **Step 1: Executar checagem de tipos e build do frontend**
- [x] **Step 2: Executar testes de regressão do backend**
