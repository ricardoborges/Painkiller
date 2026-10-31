<script lang="ts">
  /**
   * APKs no painel. O de produção (release, assinado com a chave do projeto)
   * é o artefato que vai para a loja e para os usuários: fica em destaque,
   * num bloco de tinta invertido — destaque por peso, nunca pelo acento, que
   * continua reservado ao agente esperando o analista. O de teste (debug) e o
   * histórico ficam abaixo, em tipografia comum.
   */
  import { onMount } from 'svelte';
  import { t, formatDate } from '$lib/i18n/index.svelte';
  import { apkDownloadUrl } from '$lib/api';
  import { apkBuilds, formatApkSize } from '$lib/stores/apk.svelte';
  import type { ApkBuild } from '$lib/types';
  import Icon from './Icon.svelte';
  import ApkLogDialog from './ApkLogDialog.svelte';
  import ApkQrDialog from './ApkQrDialog.svelte';

  let { projectId, branch }: { projectId: string; branch: string } = $props();

  const builds = $derived(apkBuilds.list(projectId));
  const running = $derived(apkBuilds.active(projectId));
  const release = $derived(apkBuilds.latestReady(projectId, 'release'));
  const debug = $derived(apkBuilds.latestReady(projectId, 'debug'));
  const starting = $derived(apkBuilds.starting[projectId] ?? null);
  const history = $derived(builds.slice(0, 6));

  let logBuild = $state<ApkBuild | null>(null);
  let logOpen = $state(false);

  let qrBuild = $state<ApkBuild | null>(null);
  let qrOpen = $state(false);

  function showQr(build: ApkBuild) {
    qrBuild = build;
    qrOpen = true;
  }

  function showLog(build: ApkBuild) {
    logBuild = build;
    logOpen = true;
  }

  function when(iso: string): string {
    return formatDate(iso, { dateStyle: 'short', timeStyle: 'short' });
  }

  function kind(build: ApkBuild): string {
    return build.variant === 'release' ? t('apk.release') : t('apk.debug');
  }

  onMount(() => {
    void apkBuilds.load(projectId);
  });
</script>

<section class="panel apk rise" style="--i: 1">
  <h2 class="label">{t('apk.title')}</h2>

  <!-- APK de produção: o destaque do painel -->
  <div class="release">
    <div class="release-head">
      <Icon name="phone" size={18} />
      <div>
        <p class="release-title">{t('apk.releaseTitle')}</p>
        <p class="release-help">{t('apk.releaseHelp', { branch })}</p>
      </div>
    </div>

    {#if release}
      <p class="release-meta mono">
        <span>{when(release.finished_at ?? release.created_at)}</span>
        {#if release.commit_sha}<span>{release.commit_sha}</span>{/if}
        {#if release.size_bytes}<span>{formatApkSize(release.size_bytes)}</span>{/if}
      </p>
    {:else}
      <p class="release-meta">{t('apk.releaseNone')}</p>
    {/if}

    <div class="release-acts">
      {#if release}
        <a class="btn release-download" href={apkDownloadUrl(release)}>
          <Icon name="download" size={12} /> {t('apk.downloadRelease')}
        </a>
        <button type="button" class="btn release-build" onclick={() => showQr(release)} title={t('apk.qrTitle')}>
          <Icon name="qr" size={12} /> {t('apk.qr')}
        </button>
      {/if}
      <button
        type="button"
        class="btn release-build"
        onclick={() => (running?.variant === 'release' ? showLog(running) : apkBuilds.start(projectId, 'release'))}
        disabled={starting !== null || (!!running && running.variant !== 'release')}
        title={t('apk.buildReleaseTitle')}
      >
        {#if starting === 'release'}
          {t('backlog.preparing')}
        {:else if running?.variant === 'release'}
          {t('apk.building')} <span class="mono tabular">{apkBuilds.elapsed(running)}</span>
        {:else}
          <Icon name="refresh" size={11} /> {release ? t('apk.rebuildRelease') : t('apk.buildRelease')}
        {/if}
      </button>
    </div>
  </div>

  <!-- APK de teste -->
  <div class="debug">
    <div>
      <p class="label">{t('apk.debugTitle')}</p>
      <p class="small faint">
        {#if debug}
          {when(debug.finished_at ?? debug.created_at)}
          {#if debug.commit_sha}· <span class="mono">{debug.commit_sha}</span>{/if}
          {#if debug.size_bytes}· {formatApkSize(debug.size_bytes)}{/if}
        {:else}
          {t('apk.debugNone')}
        {/if}
      </p>
    </div>
    <div class="debug-acts">
      {#if debug}
        <a class="btn btn-line btn-sm" href={apkDownloadUrl(debug)}>
          <Icon name="download" size={10} /> {t('apk.downloadShort')}
        </a>
        <button type="button" class="btn btn-line btn-sm" onclick={() => showQr(debug)} title={t('apk.qrTitle')}>
          <Icon name="qr" size={10} /> {t('apk.qr')}
        </button>
      {/if}
      <button
        type="button"
        class="btn btn-line btn-sm"
        onclick={() => (running?.variant === 'debug' ? showLog(running) : apkBuilds.start(projectId, 'debug'))}
        disabled={starting !== null || (!!running && running.variant !== 'debug')}
        title={t('apk.buildDebugTitle')}
      >
        {#if starting === 'debug'}
          {t('backlog.preparing')}
        {:else if running?.variant === 'debug'}
          {t('apk.building')} <span class="mono tabular">{apkBuilds.elapsed(running)}</span>
        {:else}
          {t('apk.build')}
        {/if}
      </button>
    </div>
  </div>

  {#if history.length}
    <h3 class="label sub">{t('apk.history')}</h3>
    <ul class="builds">
      {#each history as b (b.id)}
        <li class:hatch={b.status === 'FAILED'}>
          <span class="mono faint">{when(b.created_at)}</span>
          <span class="label" class:strong={b.variant === 'release'}>{kind(b)}</span>
          <span class="mono faint">{b.commit_sha ?? '—'}</span>
          <span class="end">
            {#if b.status === 'BUILDING'}
              <button type="button" class="link mono" onclick={() => showLog(b)}>
                {t('apk.building')} {apkBuilds.elapsed(b)}
              </button>
            {:else if b.status === 'FAILED'}
              <button type="button" class="link mono" onclick={() => showLog(b)}>{t('apk.failedShort')}</button>
            {:else if b.available}
              <a class="link mono" href={apkDownloadUrl(b)}>
                <Icon name="download" size={10} /> {formatApkSize(b.size_bytes)}
              </a>
              <button type="button" class="link mono" onclick={() => showQr(b)} title={t('apk.qrTitle')} aria-label={t('apk.qr')}>
                <Icon name="qr" size={10} />
              </button>
            {:else}
              <span class="mono faint" title={t('apk.prunedTitle')}>{t('apk.pruned')}</span>
            {/if}
          </span>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<ApkQrDialog bind:open={qrOpen} build={qrBuild} />
<ApkLogDialog bind:open={logOpen} build={logBuild ? (builds.find((b) => b.id === logBuild?.id) ?? logBuild) : null} />

<style>
  .panel {
    border-top: 1px solid var(--rule-ink);
    padding-top: var(--s3);
  }

  .sub {
    margin-top: var(--s5);
    color: var(--ink-3);
  }

  /* Bloco invertido: o único artefato que sai para o mundo. */
  .release {
    margin-top: var(--s3);
    padding: var(--s5);
    background: var(--ink);
    color: var(--paper);
    display: flex;
    flex-direction: column;
    gap: var(--s3);
  }

  .release-head {
    display: flex;
    align-items: flex-start;
    gap: var(--s3);
  }

  .release-title {
    font-size: var(--t-h3, 1.25rem);
    font-weight: 600;
    letter-spacing: -0.01em;
  }

  .release-help,
  .release-meta {
    opacity: 0.72;
    font-size: var(--t-small, 0.8125rem);
  }

  .release-meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s3);
  }

  .release-acts {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s2);
  }

  .release-download {
    background: var(--paper);
    color: var(--ink);
    border: 1px solid var(--paper);
    font-weight: 600;
  }

  .release-download:hover {
    opacity: 0.88;
  }

  .release-build {
    background: transparent;
    color: var(--paper);
    border: 1px solid currentColor;
  }

  .release-build:disabled {
    opacity: 0.5;
  }

  .debug {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--s3);
    padding: var(--s3) 0;
    border-bottom: 1px solid var(--rule);
  }

  .debug-acts {
    display: flex;
    gap: var(--s2);
    flex: none;
  }

  .small {
    font-size: var(--t-small, 0.8125rem);
  }

  .builds {
    list-style: none;
    margin: var(--s2) 0 0;
    padding: 0;
  }

  .builds li {
    display: grid;
    grid-template-columns: auto 1fr auto auto;
    gap: var(--s3);
    align-items: center;
    padding: var(--s2) 0;
    border-bottom: 1px solid var(--rule);
    font-size: var(--t-small, 0.8125rem);
  }

  .strong {
    font-weight: 700;
    color: var(--ink);
  }

  .end {
    justify-self: end;
    display: inline-flex;
    gap: var(--s2);
  }

  .link {
    background: none;
    border: 0;
    padding: 0;
    cursor: pointer;
    color: var(--ink-2);
    display: inline-flex;
    align-items: center;
    gap: var(--s1);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .link:hover {
    color: var(--ink);
  }
</style>
