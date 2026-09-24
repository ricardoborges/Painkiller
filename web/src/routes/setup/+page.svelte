<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { setup } from '$lib/stores/setup.svelte';
  import type { SetupStep, SetupStepStatus } from '$lib/types';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';
  import EnvironmentStep from '$lib/components/setup/EnvironmentStep.svelte';
  import GoogleStep from '$lib/components/setup/GoogleStep.svelte';
  import CoolifyStep from '$lib/components/setup/CoolifyStep.svelte';

  type Stage = SetupStep | 'review';

  const STAGES: { id: Stage; title: string; optional: boolean }[] = [
    { id: 'environment', title: 'Ambiente', optional: false },
    { id: 'google', title: 'Login com Google', optional: true },
    { id: 'coolify', title: 'Coolify', optional: true },
    { id: 'review', title: 'Revisão', optional: false }
  ];

  const STATUS_WORD: Record<SetupStepStatus, string> = {
    pending: 'pendente',
    done: 'feito',
    skipped: 'pulado'
  };

  let current = $state<Stage>('environment');
  let finishing = $state(false);
  let error = $state<string | null>(null);

  $effect(() => {
    setup.ensure();
  });

  function statusOf(stage: Stage): SetupStepStatus | null {
    if (stage === 'review' || !setup.state) return null;
    return setup.state.steps[stage];
  }

  function next() {
    const index = STAGES.findIndex((s) => s.id === current);
    current = STAGES[Math.min(index + 1, STAGES.length - 1)].id;
    window.scrollTo({ top: 0 });
  }

  async function finish() {
    finishing = true;
    error = null;
    try {
      setup.set(await api.completeSetup());
      await goto('/projects', { replaceState: true });
    } catch (e) {
      error = e instanceof Error ? e.message : 'Não foi possível concluir.';
    } finally {
      finishing = false;
    }
  }

  const index = $derived(STAGES.findIndex((s) => s.id === current));
</script>

<svelte:head><title>Configuração inicial — Painkiller</title></svelte:head>

<header class="head">
  <span class="label">Primeiro acesso do administrador</span>
  <h1 class="display">Configuração inicial</h1>
  <p class="lede">
    O que dava para descobrir sozinho já está preenchido. Google e Coolify podem ficar para depois — tudo
    aqui continua editável em Admin → Configurações.
  </p>
</header>

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
    <nav class="rail" aria-label="Etapas">
      <ol>
        {#each STAGES as stage, i (stage.id)}
          {@const status = statusOf(stage.id)}
          <li>
            <button
              type="button"
              class="stage"
              class:active={current === stage.id}
              class:done={status === 'done'}
              aria-current={current === stage.id ? 'step' : undefined}
              onclick={() => (current = stage.id)}
            >
              <span class="num mono">{i + 1}</span>
              <span class="name">
                {stage.title}
                {#if stage.optional}<span class="opt">opcional</span>{/if}
              </span>
              {#if status}<span class="label st">{STATUS_WORD[status]}</span>{/if}
            </button>
          </li>
        {/each}
      </ol>
    </nav>

    <section class="panel" aria-labelledby="stage-title">
      <h2 id="stage-title" class="title">
        <span class="mono faint">{index + 1}</span>
        {STAGES[index].title}
      </h2>

      {#key current}
        <div class="rise">
          {#if current === 'environment'}
            <EnvironmentStep onsaved={next} />
          {:else if current === 'google'}
            <GoogleStep onsaved={next} />
          {:else if current === 'coolify'}
            <CoolifyStep onsaved={next} />
          {:else}
            <div class="review">
              <ul class="summary">
                {#each STAGES.slice(0, 3) as stage (stage.id)}
                  {@const status = statusOf(stage.id)}
                  <li class:pending={status === 'pending'} class:hatch={status === 'pending' && !stage.optional}>
                    <span class="name">{stage.title}</span>
                    <span class="label">{status ? STATUS_WORD[status] : ''}</span>
                    <button type="button" class="btn btn-quiet btn-sm" onclick={() => (current = stage.id)}>
                      {status === 'done' ? 'Revisar' : 'Configurar'}
                    </button>
                  </li>
                {/each}
              </ul>
              <p class="lede small">
                Falta uma última coisa, por projeto: a chave de API do provedor do harness (Gemini ou
                DeepSeek) passa a ser pedida na criação de cada projeto. Não há mais chave global no servidor.
              </p>
              {#if error}<p class="field-error" role="alert">{error}</p>{/if}
              <div class="actions">
                <button type="button" class="btn btn-solid" onclick={finish} disabled={finishing}>
                  {finishing ? 'Concluindo…' : 'Concluir e ir para os projetos'}
                </button>
              </div>
            </div>
          {/if}
        </div>
      {/key}
    </section>
  </div>
{/if}

<style>
  .head {
    display: flex;
    flex-direction: column;
    gap: var(--s2);
    padding: var(--s7) 0 var(--s5);
  }

  .layout {
    display: grid;
    grid-template-columns: 15rem minmax(0, 46rem);
    gap: var(--s7);
    padding: var(--s6) 0 var(--s9);
  }

  .rail ol {
    display: flex;
    flex-direction: column;
    position: sticky;
    top: 5rem;
    border-top: 1px solid var(--rule);
  }

  .stage {
    display: grid;
    grid-template-columns: 1.5rem 1fr auto;
    align-items: baseline;
    gap: var(--s2);
    width: 100%;
    padding: var(--s3) var(--s2);
    border: 0;
    border-bottom: 1px solid var(--rule);
    border-left: 2px solid transparent;
    background: none;
    text-align: left;
    color: var(--ink-2);
    cursor: pointer;
    transition:
      color var(--fast) var(--ease),
      border-color var(--fast) var(--ease);
  }

  .stage:hover {
    color: var(--ink);
  }

  .stage.active {
    color: var(--ink);
    border-left-color: var(--ink);
    background: var(--paper-sunk);
  }

  .stage.done .num {
    color: var(--ink);
    font-weight: 600;
  }

  .num {
    color: var(--ink-3);
  }

  .name {
    font-size: var(--t-small);
    font-weight: 500;
    display: flex;
    flex-direction: column;
  }

  .opt {
    font-size: var(--t-micro);
    font-weight: 400;
    color: var(--ink-3);
  }

  .panel {
    display: flex;
    flex-direction: column;
    gap: var(--s5);
  }

  .panel h2 {
    display: flex;
    gap: var(--s3);
    align-items: baseline;
  }

  .review {
    display: flex;
    flex-direction: column;
    gap: var(--s5);
  }

  .summary {
    border-top: 1px solid var(--rule);
  }

  .summary li {
    display: grid;
    grid-template-columns: 1fr auto auto;
    align-items: center;
    gap: var(--s3);
    padding: var(--s3) var(--s2);
    border-bottom: 1px solid var(--rule);
  }

  .summary .name {
    color: var(--ink);
  }

  .summary li.pending .name {
    color: var(--ink-2);
  }

  .small {
    font-size: var(--t-small);
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    padding-top: var(--s4);
    border-top: 1px solid var(--rule);
  }

  @media (max-width: 860px) {
    .layout {
      grid-template-columns: 1fr;
      gap: var(--s5);
    }

    .rail ol {
      position: static;
    }
  }
</style>
