<script lang="ts">
  /**
   * "Gerar APK" e "Baixar APK" do backlog: o APK de debug da branch padrão,
   * para instalar no aparelho e testar o que já foi incorporado.
   */
  import { onMount } from 'svelte';
  import { t } from '$lib/i18n/index.svelte';
  import { apkDownloadUrl } from '$lib/api';
  import { apkBuilds, formatApkSize } from '$lib/stores/apk.svelte';
  import Icon from './Icon.svelte';
  import ApkLogDialog from './ApkLogDialog.svelte';
  import ApkQrDialog from './ApkQrDialog.svelte';

  let { projectId, disabled = false }: { projectId: string; disabled?: boolean } = $props();

  const running = $derived(apkBuilds.active(projectId));
  const ready = $derived(apkBuilds.latestReady(projectId, 'debug'));
  const last = $derived(apkBuilds.latest(projectId, 'debug'));
  const starting = $derived(apkBuilds.starting[projectId] === 'debug');
  let logOpen = $state(false);
  let qrOpen = $state(false);

  onMount(() => {
    void apkBuilds.load(projectId);
  });
</script>

<button
  type="button"
  class="btn btn-line btn-sm"
  onclick={() => (running ? (logOpen = true) : apkBuilds.start(projectId, 'debug'))}
  disabled={starting || (disabled && !running)}
  title={running ? t('apk.buildingTitle') : t('apk.buildDebugTitle')}
>
  {#if starting}
    <span class="spinner-inline" aria-hidden="true"></span> {t('backlog.preparing')}
  {:else if running}
    <span class="spinner-inline" aria-hidden="true"></span> {t('apk.building')}
    <span class="mono tabular">{apkBuilds.elapsed(running)}</span>
  {:else}
    <Icon name="phone" size={11} /> {t('apk.build')}
  {/if}
</button>

{#if ready}
  <a
    class="btn btn-line btn-sm"
    href={apkDownloadUrl(ready)}
    title={t('apk.downloadDebugTitle', { size: formatApkSize(ready.size_bytes) })}
  >
    <Icon name="download" size={11} /> {t('apk.downloadShort')}
  </a>
  <button type="button" class="btn btn-line btn-sm" onclick={() => (qrOpen = true)} title={t('apk.qrTitle')}>
    <Icon name="qr" size={11} /> {t('apk.qr')}
  </button>
{/if}

{#if !running && last?.status === 'FAILED'}
  <button type="button" class="btn-link label failed" onclick={() => (logOpen = true)} title={last.error ?? ''}>
    {t('apk.failedShort')}
  </button>
{/if}

<ApkLogDialog bind:open={logOpen} build={running ?? last} />
<ApkQrDialog bind:open={qrOpen} build={ready} />

<style>
  .spinner-inline {
    display: inline-block;
    width: 12px;
    height: 12px;
    border: 2px solid var(--rule-2);
    border-top-color: var(--ink);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  .btn-link {
    background: none;
    border: 0;
    padding: 0;
    cursor: pointer;
    color: var(--ink-2);
  }

  .btn-link:hover {
    color: var(--ink);
  }

  .failed {
    text-decoration: underline;
    text-decoration-style: wavy;
  }
</style>
