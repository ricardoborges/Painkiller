<script lang="ts">
  import { page } from '$app/state';
  import Icon from '$lib/components/Icon.svelte';
  import SessionSelector from '$lib/components/SessionSelector.svelte';
  import { getProjectSessionStore } from '$lib/stores/session.svelte';

  let { data, children } = $props();

  const base = $derived(`/projetos/${data.project.id}`);
  const sessionStore = $derived(getProjectSessionStore(data.project.id));

  $effect(() => {
    sessionStore.loadSessions();
  });

  /* O ciclo ágil iterativo da sessão: Análise → Backlog → Sprints → Artefatos.
     Contexto e Custos são visões de referência do projeto. */
  const steps = $derived([
    { href: `${base}/analise-inicial`, label: 'Análise', exact: false },
    { href: `${base}/backlog`, label: 'Backlog', exact: false },
    { href: `${base}/sprints`, label: 'Sprints', exact: false },
    { href: `${base}/artefatos`, label: 'Artefatos', exact: false }
  ]);

  const aside = $derived([
    { href: base, label: 'Contexto', exact: true },
    { href: `${base}/custos`, label: 'Custos', exact: false }
  ]);

  function isActive(href: string, exact: boolean) {
    return exact ? page.url.pathname === href : page.url.pathname.startsWith(href);
  }

  /* Uma tela que gerencia a própria altura não pode conviver com o rodapé
     generoso do layout raiz. */
  const compact = $derived(page.url.pathname.startsWith(`${base}/analise-inicial`));
</script>

<svelte:head><title>{data.project.name} — Painkiller</title></svelte:head>

<header class="head" class:compact>
  <div class="top">
    <a href="/projetos" class="back label">
      <Icon name="arrow-left" size={11} /> Projetos
    </a>

    {#if data.project.repo_url}
      <a
        href={data.project.repo_url}
        target="_blank"
        rel="noopener noreferrer"
        class="repo label"
      >
        Repositório <Icon name="external" size={10} />
      </a>
    {/if}
  </div>

  <h1 class="display">{data.project.name}</h1>

  <div class="ident mono faint">
    <span>{data.project.id}</span>
    <span class="sep" aria-hidden="true">·</span>
    <span>branch base {data.project.default_branch}</span>
  </div>

  <SessionSelector
    sessions={sessionStore.sessions}
    activeSessionId={sessionStore.activeSessionId}
    loading={sessionStore.loading}
    creating={sessionStore.creating}
    onselect={(s) => sessionStore.selectSession(s.id)}
    oncreate={() => sessionStore.createNextSession()}
  />

  <nav aria-label="Seções do projeto">
    {#each steps as tab, i (tab.href)}
      {@const active = isActive(tab.href, tab.exact)}
      <a href={tab.href} class="tab" class:active aria-current={active ? 'page' : undefined}>
        <span class="n mono" aria-hidden="true">{i + 1}</span>
        {tab.label}
      </a>
    {/each}

    <span class="gap" aria-hidden="true"></span>

    {#each aside as tab (tab.href)}
      {@const active = isActive(tab.href, tab.exact)}
      <a href={tab.href} class="tab quiet" class:active aria-current={active ? 'page' : undefined}>
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

  /* Na análise o cabeçalho cede espaço: a conversa é que precisa de altura. */
  .head.compact {
    padding-top: var(--s4);
  }

  .head.compact .display {
    font-size: var(--t-title);
  }

  .head.compact .ident {
    display: none;
  }

  .top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s4);
    margin-bottom: var(--s5);
  }

  .head.compact .top {
    margin-bottom: var(--s3);
  }

  .back,
  .repo {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    color: var(--ink-3);
    transition: color var(--fast) var(--ease);
  }

  .back:hover,
  .repo:hover {
    color: var(--ink);
  }

  .ident {
    margin-top: var(--s3);
    font-size: var(--t-micro);
  }

  .sep {
    margin-inline: 0.375rem;
  }

  nav {
    display: flex;
    align-items: stretch;
    gap: var(--s5);
    margin-top: var(--s6);
    border-bottom: 1px solid var(--rule-ink);
  }

  .head.compact nav {
    margin-top: var(--s4);
  }

  .gap {
    flex: 1;
  }

  .tab {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    padding-bottom: var(--s3);
    font-size: var(--t-small);
    color: var(--ink-3);
    transition: color var(--fast) var(--ease);
  }

  /* Ordinal do passo: filete quadrado, do mesmo peso do resto da régua. */
  .n {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.125rem;
    height: 1.125rem;
    font-size: var(--t-label);
    border: 1px solid var(--rule-2);
    color: var(--ink-3);
    transition:
      color var(--fast) var(--ease),
      border-color var(--fast) var(--ease),
      background var(--fast) var(--ease);
  }

  .tab:hover,
  .tab.active {
    color: var(--ink);
  }

  .tab:hover .n {
    border-color: var(--ink-3);
    color: var(--ink);
  }

  .tab.active .n {
    background: var(--ink);
    border-color: var(--ink);
    color: var(--paper);
  }

  .tab.active::after {
    content: '';
    position: absolute;
    inset-inline: 0;
    bottom: -1px;
    height: 2px;
    background: var(--ink);
  }

  .quiet {
    color: var(--ink-4);
  }

  @media (max-width: 640px) {
    nav {
      gap: var(--s4);
      overflow-x: auto;
    }

    .gap {
      flex: 0 0 var(--s3);
    }
  }
</style>
