<script lang="ts">
  import type { Snippet } from 'svelte';

  /**
   * Uma verificação do ambiente. Sem paleta de status: cumprido é marcador
   * cheio e peso normal; pendente é marcador vazado; falha ganha hachura.
   * O vermelhão continua reservado ao agente parado esperando o analista.
   */
  let {
    state,
    label,
    detail = '',
    children
  }: {
    state: 'ok' | 'pending' | 'fail' | 'unknown';
    label: string;
    detail?: string;
    children?: Snippet;
  } = $props();

  const word = $derived(
    { ok: 'ok', pending: 'falta', fail: 'falhou', unknown: 'a verificar' }[state]
  );
</script>

<li class="check" class:ok={state === 'ok'} class:fail={state === 'fail'} class:hatch={state === 'fail'}>
  <span class="mark" aria-hidden="true"></span>
  <div class="body">
    <span class="what">{label}</span>
    {#if detail}<span class="detail">{detail}</span>{/if}
    {#if children}{@render children()}{/if}
  </div>
  <span class="label word">{word}</span>
</li>

<style>
  .check {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: baseline;
    gap: var(--s3);
    padding: var(--s3) var(--s2);
    border-top: 1px solid var(--rule);
  }

  .mark {
    width: 8px;
    height: 8px;
    border: 1px solid var(--ink-3);
    transform: translateY(-1px);
  }

  .ok .mark {
    background: var(--ink);
    border-color: var(--ink);
  }

  .fail .mark {
    border-color: var(--ink);
    border-width: 2px;
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
    min-width: 0;
  }

  .what {
    font-size: var(--t-small);
    color: var(--ink-2);
  }

  .ok .what,
  .fail .what {
    color: var(--ink);
  }

  .fail .what {
    font-weight: 600;
  }

  .detail {
    font-size: var(--t-micro);
    color: var(--ink-3);
    overflow-wrap: anywhere;
  }

  .word {
    white-space: nowrap;
  }

  .fail .word {
    color: var(--ink);
  }
</style>
