<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import { api, authedUrl } from '$lib/api';
  import { PROJECT_TYPE_META, type ProjectTemplate } from '$lib/types';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';
  import TemplateDialog from '$lib/components/TemplateDialog.svelte';
  import AdminTabs from '$lib/components/AdminTabs.svelte';

  // Esta edição tem um template só (app Android nativo), semeado pelo backend:
  // aqui o admin o configura, sem criar nem excluir.
  let templates = $state<ProjectTemplate[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let dialogOpen = $state(false);
  let editing = $state<ProjectTemplate | null>(null);

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

  function openEdit(tpl: ProjectTemplate) {
    editing = tpl;
    dialogOpen = true;
  }

  function togglePrompt(id: string) {
    expandedPrompts[id] = !expandedPrompts[id];
  }
</script>

<svelte:head>
  <title>{t('adminTabs.templates')} — {t('admin.title')} — Painkiller</title>
</svelte:head>

<header class="head">
  <div>
    <h1 class="display">{t('admin.title')}</h1>
    <p class="lede sub">{t('templates.lede')}</p>
  </div>
</header>

<!-- Subnavegação da Área de Administração -->
<AdminTabs />

<hr class="rule rule-ink" />

{#if loading}
  <Skeleton rows={3} />
{:else if error}
  <Placeholder kind="error" title={t('templates.loadFailedTitle')} detail={error}>
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={load}>{t('common.retry')}</button>
    {/snippet}
  </Placeholder>
{:else}
  <div class="template-grid">
    {#each templates as tpl (tpl.id)}
      {@const meta = PROJECT_TYPE_META[tpl.project_type]}
      <article class="template-card">
        <header class="card-head">
          <div class="head-info">
            <h2 class="template-title">{tpl.name}</h2>
            {#if tpl.description}
              <p class="template-desc">{tpl.description}</p>
            {/if}
          </div>

          <div class="head-badges">
            <span class="badge mono type-badge">{meta?.label || tpl.project_type}</span>
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
            <a
              href={authedUrl(`/admin/templates/${tpl.id}/scaffold/download`)}
              class="file-link mono truncate"
              download
              title={t('templates.downloadScaffold')}
            >
              <Icon name="download" size={11} />
              <span>{tpl.bundled_scaffold ? t('templates.bundledScaffold') : tpl.scaffold_filename}</span>
            </a>
          </div>
        </div>

        <!-- Prévia das diretrizes -->
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
            <button type="button" class="btn btn-line btn-sm" onclick={() => openEdit(tpl)}>
              <Icon name="pencil" size={12} /> {t('common.edit')}
            </button>
          </div>
        </footer>
      </article>
    {/each}
  </div>
{/if}

{#if editing}
  <TemplateDialog bind:open={dialogOpen} template={editing} onsaved={() => load()} />
{/if}

<style>
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

  @media (max-width: 640px) {
    .card-files {
      grid-template-columns: 1fr;
    }
  }
</style>
