<script lang="ts">
  /** Log do build de um APK (npm, Gradle e assinatura) no terminal dos deploys. */
  import { t } from '$lib/i18n/index.svelte';
  import type { ApkBuild } from '$lib/types';
  import Modal from './Modal.svelte';
  import DeployTerminal from './DeployTerminal.svelte';

  let { open = $bindable(false), build }: { open?: boolean; build: ApkBuild | null } = $props();
</script>

<Modal bind:open title={t('apk.logTitle')}>
  {#snippet body()}
    {#if build}
      {#if build.error}
        <p class="err">{build.error}</p>
      {/if}
      <DeployTerminal
        logs={build.logs || t('apk.noLog')}
        active={build.status === 'BUILDING'}
        failed={build.status === 'FAILED'}
        branch={build.branch}
        title={t('apk.buildLogs')}
      />
    {/if}
  {/snippet}
</Modal>

<style>
  .err {
    padding: var(--s3) var(--s5);
    font-weight: 600;
  }
</style>
