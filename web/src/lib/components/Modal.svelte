<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';

  /**
   * <dialog> nativo: dá foco preso e Escape de graça.
   * Painel encostado no topo, sem raio e com sombra mínima tingida —
   * a elevação só existe porque é funcionalmente necessária.
   */
  let {
    open = $bindable(false),
    title,
    width = '46rem',
    body,
    footer
  }: {
    open?: boolean;
    title: string;
    width?: string;
    body: Snippet;
    footer?: Snippet;
  } = $props();

  let el = $state<HTMLDialogElement | null>(null);

  $effect(() => {
    if (!el) return;
    if (open && !el.open) el.showModal();
    else if (!open && el.open) el.close();
  });
</script>

<dialog bind:this={el} onclose={() => (open = false)} style="--w: {width}">
  <div class="panel">
    <header>
      <h2 class="title">{title}</h2>
      <button type="button" class="btn-icon" onclick={() => (open = false)} aria-label="Fechar">
        <Icon name="close" />
      </button>
    </header>
    <div class="body">{@render body()}</div>
    {#if footer}
      <footer>{@render footer()}</footer>
    {/if}
  </div>
</dialog>

<style>
  dialog {
    width: min(var(--w), calc(100vw - 2rem));
    max-height: min(86vh, 54rem);
    margin: 4.5rem auto auto;
    padding: 0;
    border: 1px solid var(--rule-2);
    background: var(--paper);
    color: var(--ink);
    box-shadow: 0 24px 48px -24px var(--shadow);
    /* A janela nunca rola: só o corpo tem barra, cabeçalho e rodapé ficam fixos. */
    overflow: hidden;
  }

  /* Só aberto: `display` no <dialog> fechado anularia o `display: none` nativo. */
  dialog[open] {
    display: flex;
    flex-direction: column;
  }

  dialog::backdrop {
    background: var(--scrim);
  }

  dialog[open] {
    animation: rise var(--base) var(--ease);
  }

  .panel {
    display: flex;
    flex-direction: column;
    /* Ocupa a altura útil do dialog (já descontada a borda) e deixa o corpo encolher. */
    flex: 1 1 auto;
    min-height: 0;
  }

  header,
  footer {
    flex-shrink: 0;
  }

  /* O único contêiner que rola: uma só barra, qualquer que seja o conteúdo. */
  .body {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s4);
    padding: var(--s4) var(--s5);
    border-bottom: 1px solid var(--rule-ink);
  }

  footer {
    display: flex;
    justify-content: flex-end;
    gap: var(--s2);
    padding: var(--s4) var(--s5);
    border-top: 1px solid var(--rule);
    background: var(--paper-sunk);
  }

  @media (max-width: 640px) {
    dialog {
      margin-top: 1rem;
      max-height: calc(100vh - 2rem);
    }
  }
</style>
