<script lang="ts">
  import Icon from '../Icon.svelte';

  /** Valor em mono com botão de copiar — URIs de redirect, credenciais. */
  let { value, label = '' }: { value: string; label?: string } = $props();

  let copied = $state(false);
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      copied = true;
      clearTimeout(timer);
      timer = setTimeout(() => (copied = false), 1600);
    } catch {
      /* clipboard bloqueado: o valor segue selecionável */
    }
  }
</script>

<div class="copy">
  {#if label}<span class="label">{label}</span>{/if}
  <div class="line">
    <code class="mono value">{value}</code>
    <button type="button" class="btn btn-line btn-sm" onclick={copy} aria-label="Copiar {label || value}">
      <Icon name={copied ? 'check' : 'copy'} size={11} />
      {copied ? 'Copiado' : 'Copiar'}
    </button>
  </div>
</div>

<style>
  .copy {
    display: flex;
    flex-direction: column;
    gap: var(--s1);
  }

  .line {
    display: flex;
    align-items: stretch;
    gap: var(--s2);
  }

  .value {
    flex: 1;
    min-width: 0;
    padding: 0.3125rem var(--s2);
    background: var(--paper-sunk);
    border: 1px solid var(--rule);
    font-size: var(--t-micro);
    overflow-wrap: anywhere;
    user-select: all;
  }
</style>
