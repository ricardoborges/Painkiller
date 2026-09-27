<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import { goto } from '$app/navigation';
  import Icon from '$lib/components/Icon.svelte';
  import ProjectForm from '$lib/components/ProjectForm.svelte';
</script>

<svelte:head><title>{t('projects.new')} — Painkiller</title></svelte:head>

<header class="head">
  <a href="/projects" class="back label">
    <Icon name="arrow-left" size={11} /> {t('layout.nav.projects')}
  </a>
  <h1 class="display">{t('projects.new')}</h1>
  <p class="lede sub">{t('projects.lede')}</p>
</header>

<hr class="rule rule-ink" />

<div class="content">
  <ProjectForm onsaved={(p) => goto(`/projects/${p.id}`)} oncancel={() => goto('/projects')} />
</div>

<style>
  .head {
    padding-top: var(--s7);
  }

  .back {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    margin-bottom: var(--s4);
    color: var(--ink-3);
    transition: color var(--fast) var(--ease);
  }

  .back:hover {
    color: var(--ink);
  }

  .sub {
    margin-top: var(--s3);
  }

  .rule {
    margin-top: var(--s5);
  }

  .content {
    padding-top: var(--s6);
  }
</style>
