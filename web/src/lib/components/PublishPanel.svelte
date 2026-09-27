<script lang="ts">
  import { onDestroy } from 'svelte';
  import { api } from '$lib/api';
  import { DEPLOYMENT_LABEL, type DeploymentView } from '$lib/types';
  import Icon from './Icon.svelte';

  let { projectId }: { projectId: string } = $props();

  let view = $state<DeploymentView | null>(null);
  let loading = $state(true);
  let publishing = $state(false);
  let error = $state<string | null>(null);
  let timer: ReturnType<typeof setTimeout> | null = null;

  const info = $derived(view?.deployment ?? null);
  const inFlight = $derived(info?.status === 'DEPLOYING' || info?.status === 'CREATED');

  async function load() {
    try {
      view = await api.getDeployment(projectId);
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Falha ao consultar a publicação.';
    } finally {
      loading = false;
      schedule();
    }
  }

  /** Enquanto o Coolify constrói, consulta de novo a cada poucos segundos. */
  function schedule() {
    if (timer) clearTimeout(timer);
    timer = null;
    if (inFlight) timer = setTimeout(load, 6000);
  }

  async function publish() {
    publishing = true;
    error = null;
    try {
      view = await api.deployProject(projectId);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Falha ao publicar.';
      // O servidor grava o erro no projeto: recarrega para mostrar o estado real.
      await load();
    } finally {
      publishing = false;
      schedule();
    }
  }

  $effect(() => {
    load();
  });

  onDestroy(() => {
    if (timer) clearTimeout(timer);
  });
</script>

<div class="panel">
  <h2 class="label">Publicação</h2>

  {#if loading}
    <p class="faint none">Consultando…</p>
  {:else if view && !view.configured}
    <p class="faint none">
      Este servidor ainda não está ligado a um Coolify. Defina as variáveis
      <span class="mono">COOLIFY_*</span> no <span class="mono">.env</span> para publicar.
    </p>
  {:else}
    <p class="status">
      {#if inFlight}<span class="pulse" aria-hidden="true"></span>{/if}
      {info ? DEPLOYMENT_LABEL[info.status] : DEPLOYMENT_LABEL.NOT_CONFIGURED}
    </p>

    {#if info?.url}
      <a class="url mono" href={info.url} target="_blank" rel="noopener noreferrer">
        {info.url} <Icon name="external" size={10} />
      </a>
    {/if}

    {#if info?.status === 'FAILED' && info.error}
      <p class="help err">{info.error}</p>
    {/if}

    {#if info && info.status !== 'NOT_CONFIGURED'}
      <p class="help">
        Porta {info.port} · build {info.build_pack}
        {#if info.dockerfile_location}· {info.dockerfile_location}{/if}
      </p>
    {/if}

    <div class="acts">
      <button
        type="button"
        class="btn btn-line btn-sm"
        onclick={publish}
        disabled={publishing || inFlight}
        title="Envia a branch principal para o Coolify construir e colocar no ar"
      >
        <Icon name="globe" size={11} />
        {#if publishing}
          Enviando…
        {:else if info?.app_uuid}
          Publicar de novo
        {:else}
          Publicar
        {/if}
      </button>
      <button type="button" class="btn btn-quiet btn-sm" onclick={load} aria-label="Atualizar estado">
        <Icon name="refresh" size={11} />
      </button>
    </div>
  {/if}

  {#if error}
    <p class="help err" role="alert">{error}</p>
  {/if}
</div>

<style>
  .panel {
    border-top: 1px solid var(--rule-ink);
    padding-top: var(--s3);
  }

  .none {
    margin-top: var(--s3);
    font-size: var(--t-small);
  }

  .status {
    display: flex;
    align-items: center;
    gap: var(--s2);
    margin-top: var(--s3);
    font-size: var(--t-small);
    font-weight: 500;
  }

  .pulse {
    width: 6px;
    height: 6px;
    flex: none;
    background: var(--ink);
    animation: blink 1.3s var(--ease) infinite;
  }

  .url {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    margin-top: var(--s2);
    font-size: var(--t-micro);
    color: var(--ink-2);
    text-decoration: underline;
    text-underline-offset: 2px;
    word-break: break-all;
  }

  .url:hover {
    color: var(--ink);
  }

  .help {
    margin-top: var(--s3);
  }

  .err {
    color: var(--ink);
    white-space: pre-wrap;
  }

  .acts {
    display: flex;
    gap: var(--s2);
    margin-top: var(--s4);
  }
</style>
