<script lang="ts">
  import { api, baseName } from '$lib/api';
  import type { Project } from '$lib/types';
  import { pending } from '$lib/stores/pending.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';
  import ProjectDialog from '$lib/components/ProjectDialog.svelte';

  let projects = $state<Project[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let dialogOpen = $state(false);
  let editing = $state<Project | null>(null);
  let removing = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      projects = await api.listProjects();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Falha ao carregar projetos.';
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    load();
  });

  function blockedIn(projectId: string) {
    return pending.entries.filter((e) => e.project.id === projectId).length;
  }

  function openNew() {
    editing = null;
    dialogOpen = true;
  }

  function openEdit(p: Project) {
    editing = p;
    dialogOpen = true;
  }

  async function remove(p: Project) {
    if (!confirm(`Excluir "${p.name}" e todas as suas tarefas?`)) return;
    removing = p.id;
    try {
      await api.deleteProject(p.id);
      projects = projects.filter((x) => x.id !== p.id);
      pending.refresh();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Falha ao excluir.';
    } finally {
      removing = null;
    }
  }

  function onSaved() {
    load();
  }

  const fmt = new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: 'short',
    year: 'numeric'
  });

  function when(iso: string) {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : fmt.format(d).replace('.', '');
  }
</script>

<svelte:head><title>Projetos — Painkiller</title></svelte:head>

<header class="head spread">
  <div>
    <h1 class="display">Projetos</h1>
    <p class="lede sub">
      Contexto, propósito e documentos que alimentam o agente de análise.
    </p>
  </div>
  <button type="button" class="btn btn-solid" onclick={openNew}>
    <Icon name="plus" /> Novo projeto
  </button>
</header>

<p class="label tally">
  {#if loading}
    Carregando
  {:else}
    {projects.length}
    {projects.length === 1 ? 'projeto' : 'projetos'}
    {#if pending.count > 0}
      <span class="sep" aria-hidden="true">·</span>
      <span class="blocked">{pending.count} aguardando analista</span>
    {/if}
  {/if}
</p>

<hr class="rule rule-ink" />

{#if loading}
  <Skeleton rows={3} />
{:else if error}
  <Placeholder kind="error" title="Não foi possível carregar os projetos" detail={error}>
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={load}>Tentar de novo</button>
    {/snippet}
  </Placeholder>
{:else if projects.length === 0}
  <Placeholder
    title="Nenhum projeto ainda"
    detail="Um projeto reúne o propósito, a solução desejada e os documentos de contexto. É a partir daí que o agente monta as perguntas de especificação."
  >
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={openNew}>
        <Icon name="plus" /> Criar o primeiro
      </button>
    {/snippet}
  </Placeholder>
{:else}
  <ul class="list divide">
    {#each projects as p, i (p.id)}
      {@const blocked = blockedIn(p.id)}
      <li class="row rise" style="--i: {i}" class:dimmed={removing === p.id}>
        <span class="idx mono" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>

        <div class="body">
          <div class="name-line">
            <a class="title name" href="/projetos/{p.id}">{p.name}</a>
            {#if blocked > 0}
              <a class="blocked-tag label" href="/pendencias">
                <span class="dot" aria-hidden="true"></span>
                {blocked} aguardando
              </a>
            {/if}
          </div>

          <dl class="meta">
            <div>
              <dt class="label">Propósito</dt>
              <dd class="clamp-2">{p.purpose || 'Não informado'}</dd>
            </div>
            <div>
              <dt class="label">Solução</dt>
              <dd class="clamp-2">{p.solution_description || 'Não informada'}</dd>
            </div>
          </dl>

          {#if p.attachments.length}
            <ul class="chips">
              {#each p.attachments.slice(0, 4) as path (path)}
                <li class="chip"><Icon name="clip" size={11} />{baseName(path)}</li>
              {/each}
              {#if p.attachments.length > 4}
                <li class="chip more mono">+{p.attachments.length - 4}</li>
              {/if}
            </ul>
          {/if}
        </div>

        <div class="side">
          <time class="faint mono date" datetime={p.created_at}>{when(p.created_at)}</time>
          <div class="actions">
            <a class="btn btn-line btn-sm" href="/projetos/{p.id}">
              Abrir <Icon name="arrow-right" size={11} />
            </a>
            <button
              type="button"
              class="btn-icon"
              onclick={() => openEdit(p)}
              aria-label="Editar {p.name}"
            >
              <Icon name="pencil" />
            </button>
            <button
              type="button"
              class="btn-icon danger"
              onclick={() => remove(p)}
              disabled={removing === p.id}
              aria-label="Excluir {p.name}"
            >
              <Icon name="trash" />
            </button>
          </div>
        </div>
      </li>
    {/each}
  </ul>
{/if}

<ProjectDialog bind:open={dialogOpen} project={editing} onsaved={onSaved} />

<style>
  .head {
    padding-top: var(--s7);
  }

  .sub {
    margin-top: var(--s3);
  }

  .tally {
    margin: var(--s6) 0 var(--s2);
  }

  .sep {
    margin-inline: 0.375rem;
  }

  .blocked {
    color: var(--accent);
  }

  .list {
    border-bottom: 1px solid var(--rule);
  }

  .row {
    display: grid;
    grid-template-columns: 2.75rem 1fr auto;
    gap: var(--s4);
    padding: var(--s5) 0;
    transition: opacity var(--base) var(--ease);
  }

  .row.dimmed {
    opacity: 0.4;
  }

  /* Numeração da lista — assinatura suíça */
  .idx {
    font-size: var(--t-small);
    color: var(--ink-4);
    padding-top: 0.15rem;
  }

  .body {
    min-width: 0;
  }

  .name-line {
    display: flex;
    align-items: center;
    gap: var(--s3);
    flex-wrap: wrap;
  }

  .name {
    text-decoration: underline;
    text-decoration-color: transparent;
    text-underline-offset: 3px;
    transition: text-decoration-color var(--fast) var(--ease);
  }

  .name:hover {
    text-decoration-color: currentColor;
  }

  .blocked-tag {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    color: var(--accent);
  }

  .dot {
    width: 6px;
    height: 6px;
    background: currentColor;
  }

  .meta {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--s2) var(--s6);
    margin: var(--s3) 0 0;
    max-width: 52rem;
  }

  .meta dt {
    margin-bottom: 0.125rem;
  }

  .meta dd {
    margin: 0;
    font-size: var(--t-small);
    color: var(--ink-2);
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s2);
    margin-top: var(--s3);
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    padding: 0.125rem 0.375rem;
    border: 1px solid var(--rule);
    font-size: var(--t-micro);
    color: var(--ink-2);
    max-width: 16rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .chip.more {
    color: var(--ink-3);
  }

  .side {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--s4);
  }

  .date {
    font-size: var(--t-micro);
    padding-top: 0.2rem;
  }

  .actions {
    display: flex;
    align-items: center;
    gap: var(--s1);
  }

  @media (max-width: 760px) {
    .row {
      grid-template-columns: 1.75rem 1fr;
    }

    .meta {
      grid-template-columns: 1fr;
    }

    .side {
      grid-column: 2;
      flex-direction: row-reverse;
      align-items: center;
      justify-content: flex-end;
      margin-top: var(--s3);
    }

    .date {
      margin-left: auto;
    }
  }
</style>
