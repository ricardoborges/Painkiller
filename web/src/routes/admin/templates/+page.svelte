<script lang="ts">
  import { api, authedUrl } from '$lib/api';
  import {
    PROJECT_TYPE_META,
    type ProjectTemplate,
    type ProjectType
  } from '$lib/types';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';
  import TemplateDialog from '$lib/components/TemplateDialog.svelte';

  let templates = $state<ProjectTemplate[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let dialogOpen = $state(false);
  let editing = $state<ProjectTemplate | null>(null);
  let removing = $state<string | null>(null);

  type FilterCategory = 'all' | 'web' | 'other';
  let categoryFilter = $state<FilterCategory>('all');

  let expandedPrompts = $state<Record<string, boolean>>({});

  async function load() {
    loading = true;
    error = null;
    try {
      templates = await api.listAdminTemplates();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Falha ao carregar templates.';
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    load();
  });

  function openNew() {
    editing = null;
    dialogOpen = true;
  }

  function openEdit(t: ProjectTemplate) {
    editing = t;
    dialogOpen = true;
  }

  async function remove(t: ProjectTemplate) {
    if (!confirm(`Excluir o template "${t.name}"?`)) return;
    removing = t.id;
    try {
      await api.deleteAdminTemplate(t.id);
      templates = templates.filter((x) => x.id !== t.id);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Falha ao excluir template.';
    } finally {
      removing = null;
    }
  }

  function togglePrompt(id: string) {
    expandedPrompts[id] = !expandedPrompts[id];
  }

  const filteredTemplates = $derived(
    templates.filter((t) => {
      if (categoryFilter === 'all') return true;
      const meta = PROJECT_TYPE_META[t.project_type];
      return meta?.category === categoryFilter;
    })
  );

  const countWeb = $derived(
    templates.filter((t) => PROJECT_TYPE_META[t.project_type]?.category === 'web').length
  );
  const countOther = $derived(
    templates.filter((t) => PROJECT_TYPE_META[t.project_type]?.category === 'other').length
  );
</script>

<svelte:head>
  <title>Templates de Projeto — Administração — Painkiller</title>
</svelte:head>

<header class="head spread">
  <div>
    <h1 class="display">Administração</h1>
    <p class="lede sub">
      Gerenciamento central de configurações, templates arquiteturais e integração com deploy.
    </p>
  </div>
  <button type="button" class="btn btn-solid" onclick={openNew}>
    <Icon name="plus" /> Novo template
  </button>
</header>

<!-- Subnavegação da Área de Administração -->
<nav class="admin-tabs" aria-label="Abas da administração">
  <a href="/admin/templates" class="tab active" aria-current="page">
    Templates de Projeto
    <span class="mono count">{templates.length}</span>
  </a>
</nav>

<hr class="rule rule-ink" />

<!-- Barra de Filtros e Resumo -->
<div class="filter-bar">
  <div class="filter-group" role="group" aria-label="Filtrar por categoria">
    <button
      type="button"
      class="filter-btn"
      class:active={categoryFilter === 'all'}
      onclick={() => (categoryFilter = 'all')}
    >
      Todos <span class="mono count">{templates.length}</span>
    </button>
    <button
      type="button"
      class="filter-btn"
      class:active={categoryFilter === 'web'}
      onclick={() => (categoryFilter = 'web')}
    >
      Web (Coolify) <span class="mono count">{countWeb}</span>
    </button>
    <button
      type="button"
      class="filter-btn"
      class:active={categoryFilter === 'other'}
      onclick={() => (categoryFilter = 'other')}
    >
      Outros (Desktop / Mobile) <span class="mono count">{countOther}</span>
    </button>
  </div>

  <span class="label tally">
    {#if loading}
      Carregando templates…
    {:else}
      {filteredTemplates.length} {filteredTemplates.length === 1 ? 'template' : 'templates'}
    {/if}
  </span>
</div>

{#if loading}
  <Skeleton rows={3} />
{:else if error}
  <Placeholder kind="error" title="Não foi possível carregar os templates" detail={error}>
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={load}>Tentar de novo</button>
    {/snippet}
  </Placeholder>
{:else if templates.length === 0}
  <Placeholder
    title="Nenhum template cadastrado"
    detail="Crie templates com especificações de arquitetura, anexo de arcabouço inicial (.zip), skills especializadas (.md/.zip) e compatibilidade com deploy no Coolify."
  >
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={openNew}>
        <Icon name="plus" /> Cadastrar primeiro template
      </button>
    {/snippet}
  </Placeholder>
{:else if filteredTemplates.length === 0}
  <Placeholder
    title="Nenhum template nesta categoria"
    detail="Não há templates correspondentes ao filtro selecionado."
  >
    {#snippet action()}
      <button type="button" class="btn btn-line" onclick={() => (categoryFilter = 'all')}>
        Ver todos os templates
      </button>
    {/snippet}
  </Placeholder>
{:else}
  <div class="template-grid">
    {#each filteredTemplates as t (t.id)}
      {@const meta = PROJECT_TYPE_META[t.project_type]}
      <article class="template-card" class:inactive={!t.is_active}>
        <header class="card-head">
          <div class="head-info">
            <div class="title-row">
              <h2 class="template-title">{t.name}</h2>
              {#if !t.is_active}
                <span class="badge badge-inactive mono">Inativo</span>
              {/if}
            </div>
            {#if t.description}
              <p class="template-desc">{t.description}</p>
            {/if}
          </div>

          <div class="head-badges">
            <span class="badge mono type-badge">{meta?.label || t.project_type}</span>
            {#if t.coolify_compatible}
              <span class="badge mono coolify-badge" title="Compatível com deploy conteinerizado no Coolify">
                <Icon name="check" size={11} /> Coolify
              </span>
            {:else}
              <span class="badge mono no-coolify-badge" title="Deploy Coolify indisponível para este tipo">
                Sem Coolify
              </span>
            {/if}
          </div>
        </header>

        <!-- Anexos de Skill e Arcabouço -->
        <div class="card-files">
          <div class="file-item">
            <span class="file-label label">Skill:</span>
            {#if t.skill_filename}
              <a
                href={authedUrl(`/admin/templates/${t.id}/skill/download`)}
                class="file-link mono truncate"
                download
                title="Baixar arquivo de skill"
              >
                <Icon name="download" size={11} />
                <span>{t.skill_filename}</span>
              </a>
            {:else}
              <span class="mono faint">Nenhum</span>
            {/if}
          </div>

          <div class="file-item">
            <span class="file-label label">Arcabouço:</span>
            {#if t.scaffold_filename}
              <a
                href={authedUrl(`/admin/templates/${t.id}/scaffold/download`)}
                class="file-link mono truncate"
                download
                title="Baixar arcabouço zip"
              >
                <Icon name="download" size={11} />
                <span>{t.scaffold_filename}</span>
              </a>
            {:else}
              <span class="mono faint">Nenhum</span>
            {/if}
          </div>
        </div>

        <!-- Prévia do Prompt -->
        {#if t.prompt}
          <div class="prompt-box">
            <div class="prompt-header">
              <span class="label">Prompt do Harness</span>
              <button
                type="button"
                class="btn-quiet btn-sm mono toggle-prompt-btn"
                onclick={() => togglePrompt(t.id)}
              >
                {expandedPrompts[t.id] ? 'Recolher' : 'Expandir'}
              </button>
            </div>
            <pre class="prompt-content mono" class:expanded={expandedPrompts[t.id]}>{t.prompt}</pre>
          </div>
        {/if}

        <footer class="card-foot">
          <span class="mono faint file-id">ID: {t.id}</span>
          <div class="actions">
            <button
              type="button"
              class="btn btn-quiet btn-sm"
              onclick={() => openEdit(t)}
            >
              <Icon name="pencil" size={12} /> Editar
            </button>
            <button
              type="button"
              class="btn btn-quiet btn-sm danger-btn"
              disabled={removing === t.id}
              onclick={() => remove(t)}
            >
              <Icon name="trash" size={12} />
              {removing === t.id ? 'Excluindo…' : 'Excluir'}
            </button>
          </div>
        </footer>
      </article>
    {/each}
  </div>
{/if}

<TemplateDialog
  bind:open={dialogOpen}
  template={editing}
  onsaved={() => load()}
/>

<style>
  .admin-tabs {
    display: flex;
    gap: var(--s4);
    margin-top: var(--s5);
  }

  .admin-tabs .tab {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    padding: var(--s2) 0;
    font-size: var(--t-small);
    font-weight: 500;
    border-bottom: 2px solid transparent;
    color: var(--ink-2);
    transition: color var(--fast) var(--ease), border-color var(--fast) var(--ease);
  }

  .admin-tabs .tab:hover {
    color: var(--ink);
  }

  .admin-tabs .tab.active {
    color: var(--ink);
    border-bottom-color: var(--ink);
  }

  .filter-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--s4);
    margin: var(--s4) 0;
    flex-wrap: wrap;
  }

  .filter-group {
    display: flex;
    gap: var(--s2);
  }

  .filter-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    padding: var(--s2) var(--s3);
    border: 1px solid var(--rule-2);
    background: var(--paper);
    color: var(--ink-2);
    font-size: var(--t-micro);
    cursor: pointer;
    transition: background var(--fast) var(--ease), color var(--fast) var(--ease);
  }

  .filter-btn:hover {
    color: var(--ink);
    border-color: var(--ink-3);
  }

  .filter-btn.active {
    background: var(--paper-sunk);
    color: var(--ink);
    border-color: var(--ink);
    font-weight: 600;
  }

  .count {
    font-size: var(--t-micro);
    opacity: 0.8;
  }

  .template-grid {
    display: flex;
    flex-direction: column;
    gap: var(--s4);
  }

  .template-card {
    display: flex;
    flex-direction: column;
    gap: var(--s4);
    padding: var(--s5);
    border: 1px solid var(--rule-2);
    background: var(--paper);
    transition: border-color var(--fast) var(--ease);
  }

  .template-card:hover {
    border-color: var(--rule-ink);
  }

  .template-card.inactive {
    opacity: 0.65;
  }

  .card-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--s4);
    flex-wrap: wrap;
  }

  .head-info {
    display: flex;
    flex-direction: column;
    gap: var(--s1);
  }

  .title-row {
    display: flex;
    align-items: center;
    gap: var(--s3);
  }

  .template-title {
    font-size: var(--t-medium);
    font-weight: 600;
    margin: 0;
  }

  .template-desc {
    font-size: var(--t-small);
    color: var(--ink-2);
    margin: 0;
    max-width: 48rem;
  }

  .head-badges {
    display: flex;
    align-items: center;
    gap: var(--s2);
  }

  .badge {
    display: inline-flex;
    align-items: center;
    gap: var(--s1);
    padding: 0.15rem 0.4rem;
    font-size: var(--t-micro);
    border: 1px solid var(--rule-2);
  }

  .type-badge {
    background: var(--paper-sunk);
    color: var(--ink);
    font-weight: 500;
  }

  .coolify-badge {
    border-color: var(--ink-3);
    color: var(--ink);
  }

  .no-coolify-badge {
    color: var(--ink-3);
    border-style: dashed;
  }

  .badge-inactive {
    border-color: var(--rule-2);
    color: var(--ink-3);
  }

  .card-files {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--s3);
    padding: var(--s3);
    border: 1px solid var(--rule-2);
    background: var(--paper-sunk);
  }

  .file-item {
    display: flex;
    align-items: center;
    gap: var(--s2);
    font-size: var(--t-small);
    min-width: 0;
  }

  .file-label {
    font-size: var(--t-micro);
    flex-shrink: 0;
  }

  .file-link {
    display: inline-flex;
    align-items: center;
    gap: var(--s1);
    color: var(--ink);
    text-decoration: underline;
    text-underline-offset: 2px;
    font-size: var(--t-micro);
  }

  .prompt-box {
    display: flex;
    flex-direction: column;
    gap: var(--s2);
    padding: var(--s3);
    border: 1px solid var(--rule-2);
    background: var(--paper-sunk);
  }

  .prompt-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .toggle-prompt-btn {
    font-size: var(--t-micro);
  }

  .prompt-content {
    margin: 0;
    font-size: var(--t-micro);
    line-height: 1.45;
    color: var(--ink-2);
    white-space: pre-wrap;
    max-height: 3.5rem;
    overflow: hidden;
    transition: max-height var(--fast) var(--ease);
  }

  .prompt-content.expanded {
    max-height: 30rem;
    overflow-y: auto;
  }

  .card-foot {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: var(--s2);
    border-top: 1px solid var(--rule-2);
  }

  .file-id {
    font-size: var(--t-micro);
  }

  .actions {
    display: flex;
    align-items: center;
    gap: var(--s2);
  }

  .danger-btn:hover {
    color: var(--accent);
  }

  @media (max-width: 640px) {
    .card-files {
      grid-template-columns: 1fr;
    }
  }
</style>
