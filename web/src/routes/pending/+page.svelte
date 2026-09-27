<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import { pending } from '$lib/stores/pending.svelte';
  import type { Task } from '$lib/types';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';
  import ClarificationPanel from '$lib/components/ClarificationPanel.svelte';

  $effect(() => {
    pending.ensure();
  });

  function onResolved(_updated: Task) {
    pending.refresh();
  }
</script>

<svelte:head><title>{t('layout.nav.pending')} — Painkiller</title></svelte:head>

<header class="head spread">
  <div>
    <h1 class="display">{t('layout.nav.pending')}</h1>
    <p class="lede sub">{@html t('pending.lede')}</p>
  </div>
  <button
    type="button"
    class="btn btn-line"
    onclick={() => pending.refresh()}
    disabled={pending.loading}
  >
    {pending.loading ? t('pending.checking') : t('pending.checkNow')}
  </button>
</header>

<hr class="rule rule-ink top-rule" />

{#if pending.loading && !pending.loaded}
  <Skeleton variant="table" rows={2} />
{:else if pending.error}
  <Placeholder kind="error" title={t('pending.scanFailed')} detail={pending.error}>
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={() => pending.refresh()}>
        {t('common.retry')}
      </button>
    {/snippet}
  </Placeholder>
{:else if pending.entries.length === 0}
  <Placeholder
    title={t('pending.emptyTitle')}
    detail={t('pending.emptyDetail')}
  >
    {#snippet action()}
      <a class="btn btn-line" href="/projects">{t('pending.seeProjects')}</a>
    {/snippet}
  </Placeholder>
{:else}
  <ul class="list">
    {#each pending.entries as entry, i (entry.task.id)}
      <li class="entry rise" style="--i: {Math.min(i, 8)}">
        <div class="meta">
          <span class="idx mono" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>
          <div>
            <a class="proj label" href="/projects/{entry.project.id}/backlog">
              {entry.project.name}
            </a>
            <h2 class="title">{entry.task.title}</h2>
            <p class="facts mono faint">
              {entry.task.id}
              {#if entry.task.assigned_branch}
                <span class="sep" aria-hidden="true">·</span>{entry.task.assigned_branch}
              {/if}
            </p>
          </div>
        </div>

        <div class="panel-wrap">
          <ClarificationPanel task={entry.task} onresolved={onResolved} />
        </div>
      </li>
    {/each}
  </ul>

  <p class="footnote help">
    <Icon name="alert" size={12} />
    {t('pending.footnote')}
  </p>
{/if}

<style>
  .head {
    padding-top: var(--s7);
  }

  .sub {
    margin-top: var(--s3);
  }

  .top-rule {
    margin-top: var(--s6);
  }

  .entry {
    display: grid;
    grid-template-columns: 1fr;
    gap: var(--s4);
    padding: var(--s6) 0;
    border-bottom: 1px solid var(--rule);
  }

  .meta {
    display: grid;
    grid-template-columns: 2.75rem 1fr;
    gap: var(--s4);
  }

  .idx {
    font-size: var(--t-small);
    color: var(--ink-4);
    padding-top: 0.2rem;
  }

  .proj {
    display: inline-block;
    margin-bottom: var(--s1);
    transition: color var(--fast) var(--ease);
  }

  .proj:hover {
    color: var(--ink);
  }

  .facts {
    margin-top: var(--s2);
    font-size: var(--t-micro);
  }

  .sep {
    margin-inline: 0.375rem;
  }

  .panel-wrap {
    margin-left: 2.75rem;
    max-width: 48rem;
  }

  .footnote {
    display: flex;
    align-items: flex-start;
    gap: var(--s2);
    margin-top: var(--s5);
    max-width: var(--measure);
  }

  @media (max-width: 760px) {
    .meta {
      grid-template-columns: 1.75rem 1fr;
    }

    .panel-wrap {
      margin-left: 0;
    }
  }
</style>
