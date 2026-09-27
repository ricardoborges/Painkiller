<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import { page } from '$app/state';
</script>

<svelte:head><title>{page.status} — Painkiller</title></svelte:head>

<div class="wrap">
  <span class="code mono">{page.status}</span>
  <h1 class="display">
    {page.status === 404 ? t('error.notFound') : t('error.broken')}
  </h1>
  {#if page.error?.message}
    <p class="lede detail">{page.error.message}</p>
  {/if}
  <a class="btn btn-solid back" href="/projects">{t('error.back')}</a>
</div>

<style>
  .wrap {
    padding: var(--s9) 0;
    max-width: 44ch;
  }

  .code {
    display: block;
    font-size: var(--t-small);
    color: var(--accent);
    margin-bottom: var(--s4);
  }

  .detail {
    margin-top: var(--s4);
  }

  .back {
    margin-top: var(--s6);
  }
</style>
