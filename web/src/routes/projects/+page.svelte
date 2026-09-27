<script lang="ts">
  import { t, tp, i18n } from '$lib/i18n/index.svelte';
  import { api, baseName } from '$lib/api';
  import type { Project } from '$lib/types';
  import { auth } from '$lib/stores/auth.svelte';
  import { pending } from '$lib/stores/pending.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';

  let projects = $state<Project[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let removing = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      projects = await api.listProjects();
    } catch (e) {
      error = e instanceof Error ? e.message : t('projects.loadFailed');
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

  async function remove(p: Project) {
    if (!confirm(t('projects.confirmDelete', { name: p.name }))) return;
    removing = p.id;
    try {
      await api.deleteProject(p.id);
      projects = projects.filter((x) => x.id !== p.id);
      pending.refresh();
    } catch (e) {
      error = e instanceof Error ? e.message : t('projects.deleteFailed');
    } finally {
      removing = null;
    }
  }

  const fmt = $derived(
    new Intl.DateTimeFormat(i18n.current, {
      day: '2-digit',
      month: 'short',
      year: 'numeric'
    })
  );

  function when(iso: string) {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : fmt.format(d).replace('.', '');
  }
</script>

<svelte:head><title>{t('layout.nav.projects')} — Painkiller</title></svelte:head>

<header class="head spread">
  <div>
    <h1 class="display">{t('layout.nav.projects')}</h1>
    <p class="lede sub">{t('projects.lede')}</p>
  </div>
  <a class="btn btn-solid" href="/projects/new">
    <Icon name="plus" /> {t('projects.new')}
  </a>
</header>

<p class="label tally">
  {#if loading}
    {t('common.loading')}
  {:else}
    {tp('projects.count', projects.length)}
    {#if auth.isAdmin && pending.count > 0}
      <span class="sep" aria-hidden="true">·</span>
      <span class="blocked">{t('projects.awaitingAnalyst', { count: pending.count })}</span>
    {/if}
  {/if}
</p>

<hr class="rule rule-ink" />

{#if loading}
  <Skeleton rows={3} />
{:else if error}
  <Placeholder kind="error" title={t('projects.loadFailedTitle')} detail={error}>
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={load}>{t('common.retry')}</button>
    {/snippet}
  </Placeholder>
{:else if projects.length === 0}
  <Placeholder
    title={t('projects.emptyTitle')}
    detail={t('projects.emptyDetail')}
  >
    {#snippet action()}
      <a class="btn btn-solid" href="/projects/new">
        <Icon name="plus" /> {t('projects.createFirst')}
      </a>
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
            <a class="title name" href="/projects/{p.id}">{p.name}</a>
            {#if p.harness === 'deepseek_superpowers'}
              <span class="harness-badge label mono" title="DeepSeek Harness">dsh</span>
            {:else if p.harness === 'maki_superpowers'}
              <span class="harness-badge label mono" title="Maki">maki</span>
            {:else if p.harness === 'unreal_superpowers'}
              <span class="harness-badge label mono" title="Unreal Agent">unreal</span>
            {:else}
              <span class="harness-badge label mono" title="Antigravity CLI">agy</span>
            {/if}
            {#if auth.isAdmin && blocked > 0}
              <a class="blocked-tag label" href="/pending">
                <span class="dot" aria-hidden="true"></span>
                {t('projects.awaiting', { count: blocked })}
              </a>
            {/if}
          </div>

          <dl class="meta">
            <div>
              <dt class="label">{t('projects.purpose')}</dt>
              <dd class="clamp-2">{p.purpose || t('projects.notProvided')}</dd>
            </div>
            <div>
              <dt class="label">{t('projects.solution')}</dt>
              <dd class="clamp-2">{p.solution_description || t('projects.notProvided')}</dd>
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
            <a class="btn btn-line btn-sm" href="/projects/{p.id}">
              {t('common.open')} <Icon name="arrow-right" size={11} />
            </a>
            <a class="btn-icon" href="/projects/{p.id}/edit" aria-label={t('projects.editAria', { name: p.name })}>
              <Icon name="pencil" />
            </a>
            <button
              type="button"
              class="btn-icon danger"
              onclick={() => remove(p)}
              disabled={removing === p.id}
              aria-label={t('projects.deleteAria', { name: p.name })}
            >
              <Icon name="trash" />
            </button>
          </div>
        </div>
      </li>
    {/each}
  </ul>
{/if}

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

  .harness-badge {
    padding: 0.0625rem 0.375rem;
    border: 1px solid var(--rule-2);
    font-size: var(--t-micro);
    color: var(--ink-2);
    background: var(--paper-sunk);
    line-height: 1.4;
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
