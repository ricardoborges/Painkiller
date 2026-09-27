<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import { api } from '$lib/api';
  import { setup } from '$lib/stores/setup.svelte';
  import Check from './Check.svelte';

  let {
    mode = 'wizard',
    onsaved
  }: {
    mode?: 'wizard' | 'settings';
    onsaved?: () => void;
  } = $props();

  const env = $derived(setup.state!.environment);

  let publicUrl = $state('');
  let hostRoot = $state('');
  let sessionTtl = $state(12);
  let overriding = $state(false);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let saved = $state(false);
  let probe = $state<{ ok: boolean; detail: string } | null>(null);
  let probing = $state(false);

  // Preenche uma vez por montagem com o que o servidor já sabe.
  let seeded = false;
  $effect(() => {
    if (seeded || !setup.state) return;
    seeded = true;
    publicUrl = setup.state.environment.public_url;
    sessionTtl = setup.state.environment.session_ttl_hours;
    hostRoot = setup.state.environment.host_root_source === 'settings' ? (setup.state.environment.host_root ?? '') : '';
    overriding = setup.state.environment.host_root_source === 'settings';
  });

  const SOURCE_LABEL = $derived({
    settings: t('env.sourceSettings'),
    detected: t('env.sourceDetected')
  });

  const missingImages = $derived(env.images.filter((row) => !row.present));

  async function testMount() {
    probing = true;
    probe = null;
    try {
      probe = await api.testSetupEnvironment();
    } catch (e) {
      probe = { ok: false, detail: e instanceof Error ? e.message : t('env.testFailed') };
    } finally {
      probing = false;
    }
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    busy = true;
    error = null;
    saved = false;
    try {
      setup.set(
        await api.saveSetupEnvironment({
          public_url: publicUrl.trim(),
          host_root: overriding ? hostRoot.trim() : '',
          session_ttl_hours: Number(sessionTtl) || 12
        })
      );
      saved = true;
      onsaved?.();
    } catch (err) {
      error = err instanceof Error ? err.message : t('common.saveFailed');
    } finally {
      busy = false;
    }
  }
</script>

<form class="step" onsubmit={save}>
  <section class="block">
    <h3 class="label">{t('env.checks')}</h3>
    <ul class="checks">
      <Check
        state={env.docker_ok ? 'ok' : 'fail'}
        label={t('env.dockerCheck')}
        detail={env.docker_ok
          ? t('env.dockerOk')
          : t('env.dockerMissing')}
      />
      {#if env.docker_ok}
        <Check
          state={missingImages.length ? 'pending' : 'ok'}
          label={t('env.images')}
          detail={missingImages.length
            ? t('env.imagesMissing', { list: missingImages.map((r) => r.harness).join(', ') })
            : t('env.imagesOk')}
        >
          {#if missingImages.length}
            <code class="mono cmd">docker compose --profile build build</code>
          {/if}
        </Check>
      {/if}
    </ul>
  </section>

  <section class="block">
    <div class="field">
      <label for="pk-public-url">{t('env.publicUrl')}</label>
      <input id="pk-public-url" class="input mono" bind:value={publicUrl} placeholder="http://localhost:8000" />
      <p class="help">
        {t('env.publicUrlHelp')}
        (<span class="mono">{publicUrl.replace(/\/$/, '')}/gitea</span>).
        {#if !env.public_url_saved}{t('env.publicUrlFromPage')}{/if}
      </p>
    </div>
    <div class="field ttl">
      <label for="pk-ttl">{t('env.ttl')}</label>
      <input id="pk-ttl" class="input mono" type="number" min="1" max="720" bind:value={sessionTtl} />
      <p class="help">{t('env.ttlHelp')}</p>
    </div>
  </section>

  <section class="block">
    <h3 class="label">{t('env.hostFolder')}</h3>
    {#if !env.in_container}
      <p class="lede small">{t('env.onHost')}</p>
    {:else}
      <p class="lede small">{@html t('env.inContainer')}</p>
      {#if !overriding}
        <div class="value-row">
          {#if env.host_root}
            <code class="mono value">{env.host_root}</code>
            <span class="label">{SOURCE_LABEL[env.host_root_source ?? 'detected']}</span>
          {:else}
            <span class="value hatch missing">{t('env.notDetected')}</span>
          {/if}
          <button
            type="button"
            class="btn btn-quiet btn-sm"
            onclick={() => {
              overriding = true;
              probe = null;
            }}>{t('env.override')}</button
          >
        </div>
      {:else}
        <div class="field">
          <label for="pk-host-root">{t('env.absolutePath')}</label>
          <input
            id="pk-host-root"
            class="input mono"
            bind:value={hostRoot}
            oninput={() => (probe = null)}
            placeholder={env.detected_host_root ?? 'D:\\dev\\Painkiller\\storage'}
          />
          <p class="help">
            {#if env.detected_host_root}{t('env.emptyDetected')}{:else}{t('env.cannotDetect')}{/if}
            <button
              type="button"
              class="linkish"
              onclick={() => {
                overriding = false;
                hostRoot = '';
                probe = null;
              }}>{t('env.useAuto')}</button
            >
          </p>
        </div>
      {/if}
    {/if}
    <div class="probe">
      <button type="button" class="btn btn-line btn-sm" onclick={testMount} disabled={probing || !env.docker_ok}>
        {probing ? t('env.testing') : t('env.testMount')}
      </button>
      {#if probe}
        <p class="probe-result" class:hatch={!probe.ok} class:bad={!probe.ok} role="status">{probe.detail}</p>
      {:else}
        <p class="help">{t('env.testHelp')}</p>
      {/if}
    </div>
  </section>

  {#if error}<p class="field-error" role="alert">{error}</p>{/if}

  <div class="actions">
    {#if saved && mode === 'settings'}<span class="help">{t('common.saved')}</span>{/if}
    {#if !probe}
      <span class="help">{t('env.testToSave')}</span>
    {:else if !probe.ok}
      <span class="help bad">{t('env.testMustPass')}</span>
    {/if}
    <button
      type="submit"
      class="btn btn-solid"
      disabled={busy || probing || !probe?.ok}
      title={!probe?.ok ? t('env.testTitle') : undefined}
    >
      {busy ? t('common.saving') : mode === 'wizard' ? t('setupStep.saveContinue') : t('common.save')}
    </button>
  </div>
</form>

<style>
  .step {
    display: flex;
    flex-direction: column;
    gap: var(--s6);
  }

  .block {
    display: flex;
    flex-direction: column;
    gap: var(--s3);
  }

  .checks {
    border-bottom: 1px solid var(--rule);
  }

  .ttl {
    max-width: 14rem;
  }

  .cmd {
    margin-top: var(--s1);
    font-size: var(--t-micro);
    color: var(--ink);
  }

  .small {
    font-size: var(--t-small);
  }

  .value-row {
    display: flex;
    align-items: center;
    gap: var(--s3);
    flex-wrap: wrap;
  }

  .value {
    padding: 0.3125rem var(--s2);
    border: 1px solid var(--rule);
    background: var(--paper-sunk);
    font-size: var(--t-micro);
    overflow-wrap: anywhere;
  }

  .missing {
    font-weight: 600;
    background-color: var(--paper);
  }

  .probe {
    display: flex;
    align-items: baseline;
    gap: var(--s3);
    flex-wrap: wrap;
  }

  .probe-result {
    font-size: var(--t-micro);
    color: var(--ink);
    padding: 0.25rem var(--s2);
  }

  .probe-result.bad {
    font-weight: 600;
  }

  .help.bad {
    color: var(--accent);
  }

  .linkish {
    padding: 0;
    border: 0;
    background: none;
    color: var(--ink);
    text-decoration: underline;
    text-underline-offset: 2px;
    cursor: pointer;
    font-size: inherit;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: var(--s3);
    padding-top: var(--s4);
    border-top: 1px solid var(--rule);
  }
</style>
