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

- [ ] **Step 1: Adicionar `'sidebar'` ao tipo `Name` e SVG correspondente**

Em `web/src/lib/components/Icon.svelte`:
```svelte
<script lang="ts">
  type Name =
    | 'plus'
    | 'arrow-right'
    | 'arrow-left'
    | 'pencil'
    | 'trash'
    | 'clip'
    | 'check'
    | 'alert'
    | 'play'
    | 'close'
    | 'send'
    | 'upload'
    | 'external'
    | 'file-text'
    | 'copy'
    | 'info'
    | 'sidebar';

  let { name, size = 14 }: { name: Name; size?: number } = $props();
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 16 16"
  fill="none"
  stroke="currentColor"
  stroke-width="1.5"
  stroke-linecap="square"
  stroke-linejoin="miter"
  aria-hidden="true"
>
  <!-- ... existentes ... -->
  {#if name === 'sidebar'}
    <rect x="2" y="2.5" width="12" height="11" />
    <path d="M6 2.5v11" />
  {/if}
</svg>
```

- [ ] **Step 2: Verificar checagem de tipos**

Run: `npm run check` em `web/`  
Expected: 0 erros.

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/components/Icon.svelte
git commit -m "feat(ui): add sidebar icon primitive"
```

---

### Task 2: Componente `SessionSidebar.svelte`

**Files:**
- Create: `web/src/lib/components/SessionSidebar.svelte`

**Interfaces:**
- Consumes: `Icon.svelte`, `IterationSession` de `$lib/types`
- Produces: `SessionSidebar` component com props `{ sessions, activeSessionId, loading, creating, onselect, oncreate }`

- [ ] **Step 1: Implementar o componente `SessionSidebar.svelte`**

Criar `web/src/lib/components/SessionSidebar.svelte` com:
- Suporte a `$state` para `collapsed`, inicializado a partir de `localStorage.getItem('painkiller_sessions_sidebar_collapsed') === 'true'`.
- Efeito `$effect` para persistir em `localStorage` a cada alternância.
- Modo expandido (240px) exibindo cabeçalho `SESSÕES` + botão `[|]`, lista vertical com `#1 Sessão 1`, status badge, e botão `+ Nova sessão`.
- Modo recolhido / mini-rail (48px) exibindo botão `[|]`, botões numéricos `#1`, `#2` com indicador ativo e `+` para criar.
- Indicador ativo na borda esquerda: barra de 2px `var(--ink)`.
- Cantos retos (`border-radius: 0`) e bordas `--rule-2`.

- [ ] **Step 2: Validar tipos com `npm run check`**

Run: `npm run check` em `web/`  
Expected: 0 erros.

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/components/SessionSidebar.svelte
git commit -m "feat(ui): create SessionSidebar component with Devin style collapsible rail"
```

---

### Task 3: Integração no Layout do Projeto (`routes/projetos/[id]/+layout.svelte`)

**Files:**
- Modify: `web/src/routes/projetos/[id]/+layout.svelte`
- Delete: `web/src/lib/components/SessionSelector.svelte`

**Interfaces:**
- Consumes: `SessionSidebar` de `$lib/components/SessionSidebar.svelte`

- [ ] **Step 1: Atualizar `web/src/routes/projetos/[id]/+layout.svelte`**

- Remover a importação de `SessionSelector` e importar `SessionSidebar`.
- Envolver a área do projeto em uma estrutura de duas colunas:
  - Coluna esquerda: `<SessionSidebar ... />`
  - Coluna direita: `<div class="project-main">` contendo o cabeçalho existente (projetos, repositório, nome do projeto, identificador, abas) e `{@render children()}`.
- Ajustar CSS para flex layout contínuo, mantendo a rolagem independente se necessário.
- Excluir o arquivo antigo `web/src/lib/components/SessionSelector.svelte`.

- [ ] **Step 2: Validar tipos com `npm run check`**

Run: `npm run check` em `web/`  
Expected: 0 erros.

- [ ] **Step 3: Commit**

```bash
git add web/src/routes/projetos/[id]/+layout.svelte web/src/lib/components/SessionSidebar.svelte
git rm web/src/lib/components/SessionSelector.svelte
git commit -m "refactor(ui): replace horizontal SessionSelector with collapsible SessionSidebar in project layout"
```

---

### Task 4: Verificação Completa e Build

**Files:**
- None (apenas verificação)

- [ ] **Step 1: Executar checagem de tipos e build do frontend**

Run: `npm run check` e `npm run build` na pasta `web/`  
Expected: 0 erros e build gerado com sucesso.

- [ ] **Step 2: Executar testes de regressão do backend**

Run: `pytest tests/unit`  
Expected: 100% de testes passando.
