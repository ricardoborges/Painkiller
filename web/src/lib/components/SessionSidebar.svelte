<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import type { IterationSession, SessionStatus } from '$lib/types';

  let {
    sessions = [],
    activeSessionId = null,
    loading = false,
    creating = false,
    onselect,
    oncreate
  }: {
    sessions: IterationSession[];
    activeSessionId: string | null;
    loading?: boolean;
    creating?: boolean;
    onselect: (session: IterationSession) => void;
    oncreate: () => void;
  } = $props();

  const statusLabel: Record<SessionStatus, string> = {
    PLANNING: 'Análise',
    BACKLOG: 'Backlog',
    IN_SPRINT: 'Execução',
    COMPLETED: 'Concluída'
  };

  const STORAGE_KEY = 'painkiller_sessions_sidebar_collapsed';

  let collapsed = $state(false);
  let initialized = $state(false);

  $effect(() => {
    if (!initialized && typeof window !== 'undefined') {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved !== null) {
        collapsed = saved === 'true';
      }
      initialized = true;
    }
  });

  function toggle() {
    collapsed = !collapsed;
    if (typeof window !== 'undefined') {
      localStorage.setItem(STORAGE_KEY, String(collapsed));
    }
  }
</script>

<aside class="session-sidebar" class:collapsed aria-label="Sessões do projeto">
  <div class="sidebar-head">
    {#if !collapsed}
      <div class="head-lead">
        <span class="head-title mono">SESSÕES</span>
        {#if loading}
          <span class="loading-label mono faint">…</span>
        {/if}
      </div>
    {/if}

    <button
      type="button"
      class="toggle-btn"
      onclick={toggle}
      title={collapsed ? 'Expandir sessões' : 'Recolher sessões'}
      aria-label={collapsed ? 'Expandir sessões' : 'Recolher sessões'}
    >
      <Icon name="sidebar" size={13} />
    </button>
  </div>

  <div class="sidebar-list">
    {#each sessions as s (s.id)}
      {@const active = s.id === activeSessionId}
      <button
        type="button"
        class="session-item"
        class:active
        class:collapsed
        onclick={() => onselect(s)}
        title={`#${s.number} ${s.title} — Status: ${statusLabel[s.status] ?? s.status}`}
      >
        <span class="active-bar" aria-hidden="true"></span>

        {#if collapsed}
          <span class="chip-num mono">#{s.number}</span>
        {:else}
          <div class="item-body">
            <div class="item-title-row">
              <span class="item-num mono">#{s.number}</span>
              <span class="item-title" title={s.title}>{s.title}</span>
            </div>
            <div class="item-meta">
              <span class="badge mono label {s.status.toLowerCase()}">
                {statusLabel[s.status] ?? s.status}
              </span>
            </div>
          </div>
        {/if}
      </button>
    {/each}
  </div>

  <div class="sidebar-foot">
    {#if collapsed}
      <button
        type="button"
        class="compact-add-btn"
        onclick={oncreate}
        disabled={creating || loading}
        title={creating ? 'Criando sessão…' : 'Nova sessão'}
        aria-label="Nova sessão"
      >
        <Icon name="plus" size={11} />
      </button>
    {:else}
      <button
        type="button"
        class="btn btn-line btn-sm new-session-btn"
        onclick={oncreate}
        disabled={creating || loading}
        title="Iniciar próxima iteração ágil"
      >
        <Icon name="plus" size={11} />
        <span>{creating ? 'Criando…' : 'Nova sessão'}</span>
      </button>
    {/if}
  </div>
</aside>

<style>
  .session-sidebar {
    position: sticky;
    top: 3.25rem;
    height: calc(100vh - 3.25rem);
    width: 15rem;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    background: var(--paper);
    border-right: 1px solid var(--rule-ink);
    transition: width var(--fast) var(--ease);
    user-select: none;
    z-index: 10;
  }

  .session-sidebar.collapsed {
    width: 3rem;
  }

  @media (max-width: 768px) {
    .session-sidebar {
      position: static;
      height: auto;
      width: 100% !important;
      border-right: none;
      border-bottom: 1px solid var(--rule-ink);
    }

    .session-sidebar.collapsed {
      width: 100% !important;
    }
  }

  .sidebar-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 2.75rem;
    padding-inline: var(--s3);
    border-bottom: 1px solid var(--rule-2);
  }

  .collapsed .sidebar-head {
    justify-content: center;
    padding-inline: 0;
  }

  .head-lead {
    display: flex;
    align-items: center;
    gap: var(--s2);
    overflow: hidden;
  }

  .head-title {
    font-size: var(--t-micro);
    letter-spacing: 0.08em;
    font-weight: 600;
    color: var(--ink-3);
  }

  .loading-label {
    font-size: var(--t-micro);
  }

  .toggle-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.75rem;
    height: 1.75rem;
    background: transparent;
    border: 1px solid transparent;
    color: var(--ink-3);
    cursor: pointer;
    transition:
      color var(--fast) var(--ease),
      border-color var(--fast) var(--ease),
      background var(--fast) var(--ease);
  }

  .toggle-btn:hover {
    color: var(--ink);
    border-color: var(--rule-2);
    background: var(--paper-2);
  }

  .sidebar-list {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding-block: var(--s2);
    display: flex;
    flex-direction: column;
    gap: 1px;
  }

  .session-item {
    position: relative;
    display: flex;
    align-items: center;
    width: 100%;
    padding: var(--s2) var(--s3);
    background: transparent;
    border: none;
    text-align: left;
    cursor: pointer;
    color: var(--ink-3);
    transition:
      background var(--fast) var(--ease),
      color var(--fast) var(--ease);
  }

  .session-item.collapsed {
    padding: var(--s2) 0;
    justify-content: center;
  }

  .session-item:hover {
    background: var(--paper-2);
    color: var(--ink);
  }

  .session-item.active {
    background: var(--paper-2);
    color: var(--ink);
  }

  /* Filete marcador ativo na borda extrema esquerda (estilo Devin / monocromático Painkiller) */
  .active-bar {
    display: none;
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--ink);
  }

  .session-item.active .active-bar {
    display: block;
  }

  .chip-num {
    font-size: var(--t-micro);
    color: var(--ink-3);
    font-weight: 500;
  }

  .session-item.active .chip-num {
    color: var(--ink);
    font-weight: 600;
  }

  .item-body {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--s1);
  }

  .item-title-row {
    display: flex;
    align-items: baseline;
    gap: var(--s2);
    overflow: hidden;
  }

  .item-num {
    font-size: var(--t-micro);
    color: var(--ink-4);
    flex-shrink: 0;
  }

  .session-item.active .item-num {
    color: var(--ink-2);
  }

  .item-title {
    font-size: var(--t-small);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: inherit;
  }

  .session-item.active .item-title {
    font-weight: 500;
  }

  .item-meta {
    display: flex;
    align-items: center;
    gap: var(--s2);
  }

  .badge {
    font-size: 0.625rem;
    padding: 0.0625rem 0.25rem;
    border: 1px solid var(--rule-2);
    color: var(--ink-4);
  }

  .session-item.active .badge {
    border-color: var(--rule-ink);
    color: var(--ink-2);
  }

  .badge.in_sprint {
    border-color: var(--rule-ink);
    color: var(--ink);
    background: var(--paper);
  }

  .badge.completed {
    border-color: var(--rule-2);
    color: var(--ink-4);
    text-decoration: line-through;
  }

  .sidebar-foot {
    padding: var(--s3);
    border-top: 1px solid var(--rule-2);
  }

  .collapsed .sidebar-foot {
    padding: var(--s2) 0;
    display: flex;
    justify-content: center;
  }

  .compact-add-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    background: transparent;
    border: 1px solid var(--rule-2);
    color: var(--ink-3);
    cursor: pointer;
    transition:
      color var(--fast) var(--ease),
      border-color var(--fast) var(--ease),
      background var(--fast) var(--ease);
  }

  .compact-add-btn:hover:not(:disabled) {
    color: var(--ink);
    border-color: var(--ink);
    background: var(--paper-2);
  }

  .compact-add-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .new-session-btn {
    width: 100%;
    justify-content: center;
    gap: var(--s2);
    white-space: nowrap;
  }
</style>
