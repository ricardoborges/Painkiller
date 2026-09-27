<script lang="ts">
  import { t, tp } from '$lib/i18n/index.svelte';
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
  import AdminTabs from '$lib/components/AdminTabs.svelte';

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
      error = e instanceof Error ? e.message : t('templates.loadFailed');
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

  async function remove(tpl: ProjectTemplate) {
    if (!confirm(t('templates.confirmDelete', { name: tpl.name }))) return;
    removing = tpl.id;
    try {
      await api.deleteAdminTemplate(tpl.id);
      templates = templates.filter((x) => x.id !== tpl.id);
    } catch (e) {
      error = e instanceof Error ? e.message : t('templates.deleteFailed');
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
  <title>{t('adminTabs.templates')} — {t('admin.title')} — Painkiller</title>
</svelte:head>

<header class="head spread">
  <div>
    <h1 class="display">{t('admin.title')}</h1>
    <p class="lede sub">{t('templates.lede')}</p>
  </div>
  <button type="button" class="btn btn-solid" onclick={openNew}>
    <Icon name="plus" /> {t('templates.new')}
  </button>
</header>

<!-- Subnavegação da Área de Administração -->
<AdminTabs templateCount={templates.length} />

<hr class="rule rule-ink" />

<!-- Barra de Filtros e Resumo -->
<div class="filter-bar">
  <div class="filter-group" role="group" aria-label={t('templates.filterAria')}>
    <button
      type="button"
      class="filter-btn"
      class:active={categoryFilter === 'all'}
      onclick={() => (categoryFilter = 'all')}
    >
      {t('templates.all')} <span class="mono count">{templates.length}</span>
    </button>
    <button
      type="button"
      class="filter-btn"
      class:active={categoryFilter === 'web'}
      onclick={() => (categoryFilter = 'web')}
    >
      {t('templates.web')} <span class="mono count">{countWeb}</span>
    </button>
    <button
      type="button"
      class="filter-btn"
      class:active={categoryFilter === 'other'}
      onclick={() => (categoryFilter = 'other')}
    >
      {t('templates.other')} <span class="mono count">{countOther}</span>
    </button>
  </div>

  <span class="label tally">
    {#if loading}
      {t('templates.loading')}
    {:else}
      {tp('templates.count', filteredTemplates.length)}
    {/if}
  </span>
</div>

{#if loading}
  <Skeleton rows={3} />
{:else if error}
  <Placeholder kind="error" title={t('templates.loadFailedTitle')} detail={error}>
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={load}>{t('common.retry')}</button>
    {/snippet}
  </Placeholder>
{:else if templates.length === 0}
  <Placeholder
    title={t('templates.emptyTitle')}
    detail={t('templates.emptyDetail')}
  >
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={openNew}>
        <Icon name="plus" /> {t('templates.createFirst')}
      </button>
    {/snippet}
  </Placeholder>
{:else if filteredTemplates.length === 0}
  <Placeholder
    title={t('templates.emptyFilterTitle')}
    detail={t('templates.emptyFilterDetail')}
  >
    {#snippet action()}
      <button type="button" class="btn btn-line" onclick={() => (categoryFilter = 'all')}>
        {t('templates.seeAll')}
      </button>
    {/snippet}
  </Placeholder>
{:else}
  <div class="template-grid">
    {#each filteredTemplates as tpl (tpl.id)}
      {@const meta = PROJECT_TYPE_META[tpl.project_type]}
      <article class="template-card" class:inactive={!tpl.is_active}>
        <header class="card-head">
          <div class="head-info">
            <div class="title-row">
              <h2 class="template-title">{tpl.name}</h2>
              {#if !tpl.is_active}
                <span class="badge badge-inactive mono">{t('templates.inactive')}</span>
              {/if}
            </div>
            {#if tpl.description}
              <p class="template-desc">{tpl.description}</p>
            {/if}
          </div>

          <div class="head-badges">
            <span class="badge mono type-badge">{meta?.label || tpl.project_type}</span>
            {#if tpl.coolify_compatible}
              <span class="badge mono coolify-badge" title={t('templates.coolifyTitle')}>
                <Icon name="check" size={11} /> Coolify
              </span>
            {:else}
              <span class="badge mono no-coolify-badge" title={t('templates.noCoolifyTitle')}>
                {t('templates.noCoolify')}
              </span>
            {/if}
          </div>
        </header>

        <!-- Anexos de Skill e Arcabouço -->
        <div class="card-files">
          <div class="file-item">
            <span class="file-label label">{t('templates.skill')}:</span>
            {#if tpl.skill_filename}
              <a
                href={authedUrl(`/admin/templates/${tpl.id}/skill/download`)}
                class="file-link mono truncate"
                download
                title={t('templates.downloadSkill')}
              >
                <Icon name="download" size={11} />
                <span>{tpl.skill_filename}</span>
              </a>
            {:else}
              <span class="mono faint">{t('common.none')}</span>
            {/if}
          </div>

          <div class="file-item">
            <span class="file-label label">{t('templates.scaffold')}:</span>
            {#if tpl.scaffold_filename}
              <a
                href={authedUrl(`/admin/templates/${tpl.id}/scaffold/download`)}
                class="file-link mono truncate"
                download
                title={t('templates.downloadScaffold')}
              >
                <Icon name="download" size={11} />
                <span>{tpl.scaffold_filename}</span>
              </a>
            {:else}
              <span class="mono faint">{t('common.none')}</span>
            {/if}
          </div>
        </div>

        <!-- Prévia do Prompt -->
        {#if tpl.prompt}
          <div class="prompt-box">
            <div class="prompt-header">
              <span class="label">{t('templates.harnessPrompt')}</span>
              <button
                type="button"
                class="btn-quiet btn-sm mono toggle-prompt-btn"
                onclick={() => togglePrompt(tpl.id)}
              >
                {expandedPrompts[tpl.id] ? t('templates.collapse') : t('templates.expand')}
              </button>
            </div>
            <pre class="prompt-content mono" class:expanded={expandedPrompts[tpl.id]}>{tpl.prompt}</pre>
          </div>
        {/if}

        <footer class="card-foot">
          <span class="mono faint file-id">ID: {tpl.id}</span>
          <div class="actions">
            <button
              type="button"
              class="btn btn-quiet btn-sm"
              onclick={() => openEdit(tpl)}
            >
              <Icon name="pencil" size={12} /> {t('common.edit')}
            </button>
            <button
              type="button"
              class="btn btn-quiet btn-sm danger-btn"
              disabled={removing === tpl.id}
              onclick={() => remove(tpl)}
            >
              <Icon name="trash" size={12} />
              {removing === tpl.id ? t('templates.deleting') : t('common.delete')}
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
