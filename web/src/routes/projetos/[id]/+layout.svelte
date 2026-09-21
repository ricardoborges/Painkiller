<script lang="ts">
  import { page } from '$app/state';
  import Icon from '$lib/components/Icon.svelte';

  let { data, children } = $props();

  const base = $derived(`/projetos/${data.project.id}`);

  const tabs = $derived([
    { href: base, label: 'Contexto', exact: true },
    { href: `${base}/analise-inicial`, label: 'Análise inicial', exact: false },
    { href: `${base}/backlog`, label: 'Backlog', exact: false }
  ]);

  function isActive(href: string, exact: boolean) {
    return exact ? page.url.pathname === href : page.url.pathname.startsWith(href);
  }
</script>

<svelte:head><title>{data.project.name} — Painkiller</title></svelte:head>

<header class="head">
  <a href="/projetos" class="back label">
    <Icon name="arrow-left" size={11} /> Projetos
  </a>

  <h1 class="display">{data.project.name}</h1>

  <div class="ident mono faint">
    <span>{data.project.id}</span>
    <span class="sep" aria-hidden="true">·</span>
    <span>branch base {data.project.default_branch}</span>
    {#if data.project.repo_url}
      <span class="sep" aria-hidden="true">·</span>
      <a href={data.project.repo_url} target="_blank" rel="noopener noreferrer" class="gitea-link">
        <Icon name="external" size={10} /> Ver no Gitea
      </a>
    {/if}
  </div>

  <nav aria-label="Seções do projeto">
    {#each tabs as tab (tab.href)}
      {@const active = isActive(tab.href, tab.exact)}
      <a href={tab.href} class="tab" class:active aria-current={active ? 'page' : undefined}>
        {tab.label}
      </a>
    {/each}
  </nav>
</header>

{@render children()}

<style>
  .head {
    padding-top: var(--s6);
  }

  .back {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    color: var(--ink-3);
    margin-bottom: var(--s5);
    transition: color var(--fast) var(--ease);
  }

  .back:hover {
    color: var(--ink);
  }

  .ident {
    margin-top: var(--s3);
    font-size: var(--t-micro);
  }

  .gitea-link {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    color: var(--ink-2);
    text-decoration: underline;
    text-underline-offset: 2px;
    transition: color var(--fast) var(--ease);
  }

  .gitea-link:hover {
    color: var(--ink);
  }

  .sep {
    margin-inline: 0.375rem;
  }

  nav {
    display: flex;
    gap: var(--s5);
    margin-top: var(--s6);
    border-bottom: 1px solid var(--rule-ink);
  }

  .tab {
    position: relative;
    padding-bottom: var(--s3);
    font-size: var(--t-small);
    color: var(--ink-3);
    transition: color var(--fast) var(--ease);
  }

  .tab:hover {
    color: var(--ink);
  }

  .tab.active {
    color: var(--ink);
  }

  .tab.active::after {
    content: '';
    position: absolute;
    inset-inline: 0;
    bottom: -1px;
    height: 2px;
    background: var(--ink);
  }
</style>
