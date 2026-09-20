<script lang="ts">
  /** Esqueleto com a métrica do conteúdo real. Nunca um spinner circular. */
  let {
    rows = 3,
    variant = 'list'
  }: { rows?: number; variant?: 'list' | 'lines' | 'table' } = $props();
</script>

{#if variant === 'list'}
  <ul class="divide" aria-busy="true" aria-label="Carregando">
    {#each { length: rows } as _, i (i)}
      <li class="item">
        <span class="skel idx"></span>
        <span class="body">
          <span class="skel bar" style="width: {42 - i * 6}%"></span>
          <span class="skel bar thin" style="width: {70 - i * 8}%"></span>
        </span>
      </li>
    {/each}
  </ul>
{:else if variant === 'table'}
  <ul class="divide" aria-busy="true" aria-label="Carregando">
    {#each { length: rows } as _, i (i)}
      <li class="trow">
        <span class="skel bar" style="width: {55 - i * 7}%"></span>
        <span class="skel bar thin" style="width: 5.5rem"></span>
      </li>
    {/each}
  </ul>
{:else}
  <div class="lines" aria-busy="true" aria-label="Carregando">
    {#each { length: rows } as _, i (i)}
      <span class="skel bar thin" style="width: {[92, 78, 85, 54][i % 4]}%"></span>
    {/each}
  </div>
{/if}

<style>
  .item {
    display: flex;
    gap: var(--s5);
    padding: var(--s5) 0;
  }

  .idx {
    width: 1.5rem;
    height: 0.75rem;
    flex: none;
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: var(--s3);
    flex: 1;
  }

  .trow {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s4);
    padding: var(--s4) 0;
  }

  .lines {
    display: flex;
    flex-direction: column;
    gap: var(--s3);
  }

  .bar {
    display: block;
    height: 0.875rem;
  }

  .thin {
    height: 0.6875rem;
  }
</style>
