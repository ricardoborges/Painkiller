<script lang="ts">
  import { onDestroy } from 'svelte';
  import { api } from '$lib/api';
  import { AUTOPILOT_ACTIVE, type AutopilotRun } from '$lib/types';
  import Icon from './Icon.svelte';
  import Elapsed from './Elapsed.svelte';

  let {
    projectId,
    hasTasks,
    canPublish,
    onchange
  }: {
    projectId: string;
    hasTasks: boolean;
    /** O servidor tem Coolify configurado; sem ele o piloto só constrói. */
    canPublish: boolean;
    /** Chamado a cada mudança de estado para o backlog recarregar as tarefas. */
    onchange: (active: boolean) => void;
  } = $props();

  let run = $state<AutopilotRun | null>(null);
  let starting = $state(false);
  let error = $state<string | null>(null);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let wasActive = false;

  const active = $derived(!!run && AUTOPILOT_ACTIVE.includes(run.state));

  async function poll() {
    try {
      run = await api.getRun(projectId);
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Falha ao consultar o andamento.';
    }
    const nowActive = !!run && AUTOPILOT_ACTIVE.includes(run.state);
    // Recarrega o backlog enquanto roda e uma última vez ao parar, para que
    // os status finais (e a pergunta pendente, se houver) apareçam.
    if (nowActive || wasActive) onchange(nowActive);
    wasActive = nowActive;
    if (timer) clearTimeout(timer);
    timer = nowActive ? setTimeout(poll, 4000) : null;
  }

  async function start() {
    starting = true;
    error = null;
    try {
      run = await api.startRun(projectId, canPublish);
      wasActive = true;
      onchange(true);
      if (timer) clearTimeout(timer);
      timer = setTimeout(poll, 2000);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Falha ao iniciar a construção.';
    } finally {
      starting = false;
    }
  }

  $effect(() => {
    poll();
  });

  onDestroy(() => {
    if (timer) clearTimeout(timer);
  });
</script>

<section class="bar" class:active>
  <div class="text">
    <h2 class="label">Construção automática</h2>
    {#if run && run.state !== 'IDLE'}
      <p class="msg">
        {#if active}<span class="pulse" aria-hidden="true"></span>{/if}
        {run.message}
      </p>
      <p class="facts mono">
        <span>{run.completed}/{run.total} etapas</span>
        {#if active}
          <span class="sep" aria-hidden="true">·</span>
          <Elapsed from={new Date(run.started_at).getTime()} />
        {/if}
        {#if run.state === 'PAUSED' || run.state === 'FAILED'}
          <span class="sep" aria-hidden="true">·</span>
          <span>parou em: {run.current_task_title ?? '—'}</span>
        {/if}
      </p>
    {:else}
      <p class="msg muted">
        Executa todas as etapas do backlog em ordem, verifica cada uma e{' '}
        {#if canPublish}
          publica a aplicação no ar ao terminar.
        {:else}
          para ao terminar — publicar exige o Coolify configurado no servidor.
        {/if}
        Se o agente tiver uma dúvida, a construção pausa e a pergunta aparece abaixo.
      </p>
    {/if}
    {#if error}
      <p class="err" role="alert"><Icon name="alert" size={12} /> {error}</p>
    {/if}
  </div>

  <div class="acts">
    <button
      type="button"
      class="btn btn-solid"
      onclick={start}
      disabled={starting || active || !hasTasks}
      title={hasTasks ? 'Construir todas as etapas em sequência' : 'O backlog está vazio'}
    >
      <Icon name="bolt" size={11} />
      {#if active}
        Construindo…
      {:else if run && (run.state === 'PAUSED' || run.state === 'FAILED')}
        Continuar
      {:else if canPublish}
        Construir e publicar
      {:else}
        Construir tudo
      {/if}
    </button>
  </div>
</section>

<style>
  .bar {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: var(--s5);
    align-items: start;
    margin-top: var(--s5);
    padding: var(--s4) var(--s5);
    border: 1px solid var(--rule-2);
  }

  .bar.active {
    border-color: var(--rule-ink);
  }

  .msg {
    display: flex;
    align-items: flex-start;
    gap: var(--s2);
    margin-top: var(--s2);
    font-size: var(--t-small);
    max-width: var(--measure);
  }

  .pulse {
    width: 6px;
    height: 6px;
    flex: none;
    margin-top: 0.45rem;
    background: var(--ink);
    animation: blink 1.3s var(--ease) infinite;
  }

  .facts {
    margin-top: var(--s2);
    font-size: var(--t-micro);
    color: var(--ink-3);
  }

  .sep {
    margin-inline: 0.375rem;
  }

  .err {
    display: flex;
    align-items: center;
    gap: var(--s2);
    margin-top: var(--s2);
    font-size: var(--t-small);
  }

  .acts {
    padding-top: var(--s2);
  }

  @media (max-width: 760px) {
    .bar {
      grid-template-columns: 1fr;
    }
  }
</style>
