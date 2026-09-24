<script lang="ts">
  import { page } from '$app/state';

  /** Subnavegação da área de administração. */
  let { templateCount }: { templateCount?: number } = $props();

  const tabs = [
    { href: '/admin/templates', label: 'Templates de Projeto' },
    { href: '/admin/settings', label: 'Configurações' }
  ];
</script>

<nav class="admin-tabs" aria-label="Abas da administração">
  {#each tabs as tab (tab.href)}
    {@const active = page.url.pathname.startsWith(tab.href)}
    <a href={tab.href} class="tab" class:active aria-current={active ? 'page' : undefined}>
      {tab.label}
      {#if tab.href === '/admin/templates' && templateCount !== undefined}
        <span class="mono count">{templateCount}</span>
      {/if}
    </a>
  {/each}
</nav>

<style>
  .admin-tabs {
    display: flex;
    gap: var(--s4);
    margin-top: var(--s5);
  }

  .tab {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    padding: var(--s2) 0;
    font-size: var(--t-small);
    font-weight: 500;
    border-bottom: 2px solid transparent;
    color: var(--ink-2);
    transition:
      color var(--fast) var(--ease),
      border-color var(--fast) var(--ease);
  }

  .tab:hover {
    color: var(--ink);
  }

  .tab.active {
    color: var(--ink);
    border-bottom-color: var(--ink);
  }

  .count {
    font-size: var(--t-micro);
    color: var(--ink-3);
  }
</style>
