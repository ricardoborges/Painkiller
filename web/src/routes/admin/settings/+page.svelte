<script lang="ts">
  import { setup } from '$lib/stores/setup.svelte';
  import AdminTabs from '$lib/components/AdminTabs.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';
  import EnvironmentStep from '$lib/components/setup/EnvironmentStep.svelte';
  import GoogleStep from '$lib/components/setup/GoogleStep.svelte';
  import CoolifyStep from '$lib/components/setup/CoolifyStep.svelte';
  import AdminAccountForm from '$lib/components/setup/AdminAccountForm.svelte';

  $effect(() => {
    // Recarrega ao entrar: o estado do Docker e do Coolify pode ter mudado.
    setup.reload();
  });

  const SECTIONS = [
    { id: 'admin', title: 'Administrador' },
    { id: 'environment', title: 'Ambiente' },
    { id: 'google', title: 'Login com Google' },
    { id: 'coolify', title: 'Coolify' }
  ];
</script>

<svelte:head><title>Configurações — Administração — Painkiller</title></svelte:head>

<header class="head spread">
  <div>
    <h1 class="display">Administração</h1>
    <p class="lede sub">
      Configuração da plataforma, guardada no banco. Entra em vigor sem reiniciar.
    </p>
  </div>
</header>

<AdminTabs />

<hr class="rule rule-ink" />

{#if !setup.state && !setup.error}
  <Skeleton rows={6} />
{:else if setup.error}
  <Placeholder kind="error" title="Não foi possível carregar a configuração" detail={setup.error}>
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={() => setup.reload()}>Tentar de novo</button>
    {/snippet}
  </Placeholder>
{:else if setup.state}
  <div class="layout">
    <nav class="toc" aria-label="Seções">
      {#each SECTIONS as s (s.id)}
        <a href={`#${s.id}`}>{s.title}</a>
      {/each}
      <p class="help env-note">
        No .env ficam só ajustes de infraestrutura (imagens, portas, senha da conta de serviço do Gitea).
      </p>
    </nav>
    <div class="sections">
      <section id="admin">
        <h2 class="title">Administrador</h2>
        <AdminAccountForm />
      </section>
      <section id="environment">
        <h2 class="title">Ambiente</h2>
        <EnvironmentStep mode="settings" />
      </section>
      <section id="google">
        <h2 class="title">Login com Google</h2>
        <GoogleStep mode="settings" />
      </section>
      <section id="coolify">
        <h2 class="title">Coolify</h2>
        <CoolifyStep mode="settings" />
      </section>
    </div>
  </div>
{/if}

<style>
  .head {
    padding: var(--s7) 0 0;
  }

  .sub {
    margin-top: var(--s2);
  }

  .layout {
    display: grid;
    grid-template-columns: 13rem minmax(0, 46rem);
    gap: var(--s7);
    padding: var(--s6) 0 var(--s9);
  }

  .toc {
    position: sticky;
    top: 5rem;
    align-self: start;
    display: flex;
    flex-direction: column;
    border-top: 1px solid var(--rule);
  }

  .toc a {
    padding: var(--s2) 0;
    border-bottom: 1px solid var(--rule);
    font-size: var(--t-small);
    color: var(--ink-2);
  }

  .toc a:hover {
    color: var(--ink);
  }

  .env-note {
    margin-top: var(--s4);
  }

  .sections {
    display: flex;
    flex-direction: column;
    gap: var(--s8);
  }

  section {
    display: flex;
    flex-direction: column;
    gap: var(--s5);
    scroll-margin-top: 5rem;
  }

  @media (max-width: 860px) {
    .layout {
      grid-template-columns: 1fr;
    }

    .toc {
      position: static;
    }
  }
</style>
