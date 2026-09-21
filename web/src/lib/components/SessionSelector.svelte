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
    IN_SPRINT: 'Sprint',
    COMPLETED: 'Concluída'
  };
</script>

<div class="session-bar" aria-label="Seletor de sessões ágeis">
  <div class="lead">
    <span class="label faint">Ciclo Ágil</span>
  </div>

  <div class="session-list">
    {#each sessions as s (s.id)}
      {@const active = s.id === activeSessionId}
      <button
        type="button"
        class="session-chip"
        class:active
        onclick={() => onselect(s)}
        title={`${s.title} — status: ${statusLabel[s.status] ?? s.status}`}
      >
        <span class="num mono">#{s.number}</span>
        <span class="title">{s.title}</span>
        <span class="badge mono label {s.status.toLowerCase()}">
          {statusLabel[s.status] ?? s.status}
        </span>
      </button>
    {/each}

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
  </div>
</div>

<style>
  .session-bar {
    display: flex;
    align-items: center;
    gap: var(--s4);
    padding-block: var(--s3);
    margin-top: var(--s4);
    border-top: 1px solid var(--rule-2);
    border-bottom: 1px solid var(--rule-2);
    overflow-x: auto;
  }

  .lead {
    flex-shrink: 0;
  }

  .session-list {
    display: flex;
    align-items: center;
    gap: var(--s2);
    flex-wrap: nowrap;
  }

  .session-chip {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    padding: 0.25rem 0.625rem;
    font-size: var(--t-small);
    color: var(--ink-3);
    background: transparent;
    border: 1px solid var(--rule-2);
    cursor: pointer;
    white-space: nowrap;
    transition:
      color var(--fast) var(--ease),
      border-color var(--fast) var(--ease),
      background var(--fast) var(--ease);
  }

  .session-chip:hover {
    color: var(--ink);
    border-color: var(--ink-3);
  }

  .session-chip.active {
    color: var(--ink);
    border-color: var(--ink);
    background: var(--paper-2);
    font-weight: 500;
  }

  .num {
    font-size: var(--t-micro);
    color: var(--ink-4);
  }

  .session-chip.active .num {
    color: var(--ink-2);
  }

  .title {
    font-size: var(--t-small);
  }

  .badge {
    font-size: 0.625rem;
    padding: 0.0625rem 0.25rem;
    border: 1px solid var(--rule-2);
    color: var(--ink-4);
  }

  .session-chip.active .badge {
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

  .new-session-btn {
    padding-block: 0.25rem;
    height: auto;
    font-size: var(--t-small);
    white-space: nowrap;
  }
</style>
