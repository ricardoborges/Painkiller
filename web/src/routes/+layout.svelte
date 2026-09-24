<script lang="ts">
  import '../app.css';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { auth } from '$lib/stores/auth.svelte';
  import { pending } from '$lib/stores/pending.svelte';
  import { disposeAnalyses } from '$lib/stores/analysis.svelte';
  import { setup } from '$lib/stores/setup.svelte';

  import Icon from '$lib/components/Icon.svelte';

  let { children } = $props();

  // Páginas de quem ainda não entrou: login e o primeiro acesso de uma instalação nova.
  const isLogin = $derived(page.url.pathname === '/login' || page.url.pathname === '/first-access');

  $effect(() => {
    auth.restore();
  });

  // Gate de navegação (não de segurança — ver auth.svelte.ts).
  $effect(() => {
    if (!auth.ready) return;
    if (!auth.signedIn && !isLogin) goto('/login', { replaceState: true });
    if (auth.signedIn && isLogin) goto('/projects', { replaceState: true });
    if (
      auth.signedIn &&
      !auth.isAdmin &&
      (page.url.pathname.startsWith('/pending') ||
        page.url.pathname.startsWith('/admin') ||
        page.url.pathname.startsWith('/setup'))
    ) {
      goto('/projects', { replaceState: true });
    }
  });

  $effect(() => {
    if (auth.signedIn && auth.isAdmin) pending.ensure();
  });

  // Primeiro acesso do admin: o wizard vem antes de tudo, até ser concluído.
  $effect(() => {
    if (!auth.signedIn || !auth.isAdmin) return;
    setup.ensure().then(() => {
      if (setup.state && !setup.state.completed && !page.url.pathname.startsWith('/setup')) {
        goto('/setup', { replaceState: true });
      }
    });
  });

  function signOut() {
    auth.signOut();
    pending.reset();
    setup.reset();
    // As sessões de análise vivem num módulo e sobrevivem à navegação de
    // propósito; o logout é o único momento em que devem ser descartadas.
    disposeAnalyses();
    goto('/login', { replaceState: true });
  }

  const nav = $derived([
    { href: '/projects', label: 'Projetos', external: false },
    { href: '/gitea/', label: 'Repositórios', external: true },
    ...(auth.isAdmin
      ? [
          { href: '/pending', label: 'Pendências', external: false },
          { href: '/admin/templates', label: 'Admin', external: false }
        ]
      : [])
  ]);
  const isFluid = $derived(page.url.pathname.includes('/initial-analysis'));
</script>

<svelte:head>
  <title>Painkiller</title>
</svelte:head>

{#if !auth.ready}
  <div class="boot" aria-busy="true"></div>
{:else if isLogin}
  {@render children()}
{:else}
  <header>
    <div class="shell bar" class:fluid={isFluid}>
      <a href="/projects" class="brand" aria-label="Painkiller, início">
        <span class="mark" aria-hidden="true"></span>
        <span class="word">Painkiller</span>
      </a>

      <nav aria-label="Principal">
        {#each nav as item (item.href)}
          {@const active = !item.external && page.url.pathname.startsWith(item.href)}
          {#if item.external}
            <a
              href={item.href}
              target="_blank"
              rel="noopener noreferrer"
              class="nav-link"
              title="Acessar repositórios no Gitea"
            >
              <span>{item.label}</span>
              <Icon name="external" size={11} />
            </a>
          {:else}
            <a href={item.href} class="nav-link" class:active aria-current={active ? 'page' : undefined}>
              {item.label}
              {#if item.href === '/pending' && pending.count > 0}
                <span class="count mono">{pending.count}</span>
              {/if}
            </a>
          {/if}
        {/each}
      </nav>

      <div class="who">
        <span class="label user">{auth.user?.username}</span>
        <button type="button" class="btn btn-quiet btn-sm" onclick={signOut}>Sair</button>
      </div>
    </div>
  </header>

  <main class="shell" class:fluid={isFluid}>
    {@render children()}
  </main>
{/if}

<style>
  .boot {
    min-height: 100dvh;
  }

  header {
    position: sticky;
    top: 0;
    z-index: 20;
    background: var(--paper);
    border-bottom: 1px solid var(--rule-ink);
  }

  .bar {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: var(--s6);
    height: 3.25rem;
  }

  .brand {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
  }

  /* Quadrado de acento: a única cor fixa do cabeçalho */
  .mark {
    width: 9px;
    height: 9px;
    background: var(--accent);
  }

  .word {
    font-size: var(--t-small);
    font-weight: 600;
    letter-spacing: 0.02em;
  }

  nav {
    display: flex;
    gap: var(--s5);
    justify-self: start;
  }

  .nav-link {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    height: 3.25rem;
    font-size: var(--t-small);
    color: var(--ink-3);
    transition: color var(--fast) var(--ease);
  }

  .nav-link:hover {
    color: var(--ink);
  }

  /* Indicador de rota: filete grosso encostado na régua do cabeçalho */
  .nav-link.active {
    color: var(--ink);
  }

  .nav-link.active::after {
    content: '';
    position: absolute;
    inset-inline: 0;
    bottom: -1px;
    height: 2px;
    background: var(--ink);
  }

  .count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.125rem;
    height: 1.125rem;
    padding-inline: 0.25rem;
    font-size: 0.6875rem;
    font-weight: 500;
    background: var(--accent);
    color: #fff;
  }

  .who {
    display: flex;
    align-items: center;
    gap: var(--s3);
  }

  .user {
    color: var(--ink-2);
  }

  main {
    padding-bottom: var(--s9);
  }

  @media (max-width: 640px) {
    .bar {
      grid-template-columns: auto auto;
      grid-template-areas: 'brand who' 'nav nav';
      height: auto;
      row-gap: 0;
      padding-block: var(--s3) 0;
    }

    .brand {
      grid-area: brand;
    }

    .who {
      grid-area: who;
      justify-self: end;
    }

    nav {
      grid-area: nav;
      gap: var(--s4);
    }

    .nav-link {
      height: 2.5rem;
    }

    .user {
      display: none;
    }
  }
</style>
