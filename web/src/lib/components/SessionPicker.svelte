<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import type { IterationSession, SessionStatus } from '$lib/types';

  /* Seletor da sessão no cabeçalho: diz de qual sessão são as etapas ao lado
     e troca de sessão sem voltar ao painel. Recolhido por padrão. */
  let {
    sessions = [],
    active = null,
    creating = false,
    onselect,
    oncreate
  }: {
    sessions: IterationSession[];
    active: IterationSession | null;
    creating?: boolean;
    onselect: (session: IterationSession) => void;
    oncreate: () => void;
  } = $props();

  const STATUS_LABEL: Record<SessionStatus, string> = {
    PLANNING: 'Análise',
    BACKLOG: 'Backlog',
    IN_SPRINT: 'Execução',
    COMPLETED: 'Concluída'
  };

  let open = $state(false);
  let root = $state<HTMLElement | null>(null);

  function pick(s: IterationSession) {
    open = false;
    onselect(s);
  }

  function create() {
    open = false;
    oncreate();
  }

  function onWindowClick(e: MouseEvent) {
    if (open && root && !root.contains(e.target as Node)) open = false;
  }

  function onKeydown(e: KeyboardEvent) {
    if (open && e.key === 'Escape') open = false;
  }
</script>

<svelte:window onclick={onWindowClick} onkeydown={onKeydown} />

<div class="picker" bind:this={root}>
  <button
    type="button"
    class="trigger"
    aria-haspopup="listbox"
    aria-expanded={open}
    onclick={() => (open = !open)}
    title={active ? `#${active.number} ${active.title}` : 'Sessões'}
  >
    {#if active}
      <span class="mono faint">#{active.number}</span>
      <span class="name truncate">{active.title}</span>
    {:else}
      <span class="name">Sessão</span>
    {/if}
    <Icon name="chevron-down" size={10} />
  </button>

  {#if open}
    <div class="menu">
      <ul role="listbox" aria-label="Sessões do projeto">
        {#each [...sessions].reverse() as s (s.id)}
          {@const current = s.id === active?.id}
          <li role="option" aria-selected={current}>
            <button type="button" class="item" class:current onclick={() => pick(s)}>
              <span class="mono faint">#{s.number}</span>
              <span class="truncate">{s.title}</span>
              <span class="badge mono label" class:closed={s.status === 'COMPLETED'}>
                {STATUS_LABEL[s.status] ?? s.status}
              </span>
            </button>
          </li>
        {/each}
      </ul>
      <button type="button" class="item create" onclick={create} disabled={creating}>
        <Icon name="plus" size={10} />
        <span>{creating ? 'Criando…' : 'Nova sessão'}</span>
      </button>
    </div>
  {/if}
</div>

<style>
  .picker {
    position: relative;
    display: flex;
    align-items: stretch;
  }

  .trigger {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    max-width: 14rem;
    padding: 0 0 var(--s3);
    background: none;
    border: 0;
    font-size: var(--t-small);
    color: var(--ink);
    cursor: pointer;
  }

  .trigger:hover .name {
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  .name {
    font-weight: 600;
  }

  .menu {
    position: absolute;
    top: calc(100% + 1px);
    left: 0;
    z-index: 20;
    width: 20rem;
    max-width: calc(100vw - 2rem);
    background: var(--paper);
    border: 1px solid var(--rule-ink);
    box-shadow: var(--shadow);
  }

  ul {
    max-height: 18rem;
    overflow-y: auto;
  }

  li + li {
    border-top: 1px solid var(--rule);
  }

  .item {
    display: grid;
    grid-template-columns: 2rem minmax(0, 1fr) auto;
    align-items: baseline;
    gap: var(--s2);
    width: 100%;
    padding: var(--s3);
    background: none;
    border: 0;
    text-align: left;
    font-size: var(--t-small);
    color: var(--ink-2);
    cursor: pointer;
  }

  .item:hover:not(:disabled) {
    background: var(--paper-sunk);
    color: var(--ink);
  }

  .item.current {
    color: var(--ink);
    font-weight: 600;
    box-shadow: inset 2px 0 0 var(--ink);
  }

  .create {
    display: flex;
    align-items: center;
    border-top: 1px solid var(--rule-ink);
    color: var(--ink);
  }

  .create:disabled {
    color: var(--ink-4);
    cursor: default;
  }

  .badge {
    font-size: 0.625rem;
    font-weight: 400;
    padding: 0.0625rem 0.25rem;
    border: 1px solid var(--rule-ink);
    color: var(--ink-2);
  }

  .badge.closed {
    border-color: var(--rule-2);
    color: var(--ink-4);
  }
</style>
