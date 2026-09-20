<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';

  /**
   * Estados vazio e de erro. Ambos alinhados à esquerda dentro de um
   * bloco tipográfico — nada centralizado, nada de ilustração genérica.
   */
  let {
    kind = 'empty',
    title,
    detail = '',
    action
  }: {
    kind?: 'empty' | 'error';
    title: string;
    detail?: string;
    action?: Snippet;
  } = $props();
</script>

<div class="placeholder" class:error={kind === 'error'}>
  {#if kind === 'error'}
    <span class="badge label"><Icon name="alert" size={12} /> Falha</span>
  {/if}
  <h3 class="title">{title}</h3>
  {#if detail}
    <p class="lede detail">{detail}</p>
  {/if}
  {#if action}
    <div class="actions">{@render action()}</div>
  {/if}
</div>

<style>
  .placeholder {
    padding: var(--s8) 0 var(--s9);
    max-width: 46ch;
  }

  .badge {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    color: var(--accent);
    margin-bottom: var(--s3);
  }

  .detail {
    margin-top: var(--s2);
  }

  .actions {
    display: flex;
    gap: var(--s2);
    margin-top: var(--s5);
  }
</style>
