<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import { api } from '$lib/api';
  import { setup } from '$lib/stores/setup.svelte';

  let {
    mode = 'settings',
    onsaved
  }: {
    mode?: 'wizard' | 'settings';
    onsaved?: () => void;
  } = $props();

  let host = $state('');
  let port = $state(587);
  let user = $state('');
  let password = $state('');
  let sender = $state('');
  let tls = $state(true);
  let passwordSet = $state(false);

  let busy = $state(false);
  let error = $state<string | null>(null);
  let saved = $state(false);

  // Test state
  let testEmail = $state('');
  let testBusy = $state(false);
  let testSuccess = $state<string | null>(null);
  let testError = $state<string | null>(null);

  let seeded = false;
  $effect(() => {
    if (seeded || !setup.state?.smtp) return;
    seeded = true;
    const s = setup.state.smtp;
    host = s.smtp_host || '';
    port = s.smtp_port || 587;
    user = s.smtp_user || '';
    sender = s.smtp_from || '';
    tls = s.smtp_tls ?? true;
    passwordSet = s.smtp_password_set;
  });

  async function save(e: SubmitEvent) {
    e.preventDefault();
    busy = true;
    error = null;
    saved = false;
    try {
      const updated = await api.saveSetupSmtp({
        smtp_host: host.trim(),
        smtp_port: Number(port) || 587,
        smtp_user: user.trim(),
        smtp_password: password ? password : (passwordSet ? undefined : ''),
        smtp_from: sender.trim(),
        smtp_tls: tls
      });
      setup.set(updated);
      password = '';
      if (updated.smtp) {
        passwordSet = updated.smtp.smtp_password_set;
      }
      saved = true;
      onsaved?.();
    } catch (err) {
      error = err instanceof Error ? err.message : t('common.saveFailed');
    } finally {
      busy = false;
    }
  }

  async function runTest(e: SubmitEvent) {
    e.preventDefault();
    if (!testEmail) return;
    testBusy = true;
    testSuccess = null;
    testError = null;
    try {
      const res = await api.testSetupSmtp(testEmail.trim());
      testSuccess = res.message || t('setup.smtpTestSuccess');
    } catch (err) {
      testError = err instanceof Error ? err.message : t('common.saveFailed');
    } finally {
      testBusy = false;
    }
  }
</script>

<div class="smtp-container">
  <form class="step" onsubmit={save}>
    <p class="lede small">{t('setup.smtpLede')}</p>

    <div class="notice-box">
      <p class="help">{t('setup.smtpDevNote')}</p>
    </div>

    <div class="grid">
      <div class="field">
        <label for="smtp-host">{t('setup.smtpHost')}</label>
        <input
          id="smtp-host"
          class="input"
          type="text"
          bind:value={host}
          placeholder={t('setup.smtpHostPlaceholder')}
          autocomplete="off"
        />
      </div>

      <div class="field">
        <label for="smtp-port">{t('setup.smtpPort')}</label>
        <input
          id="smtp-port"
          class="input"
          type="number"
          bind:value={port}
          min="1"
          max="65535"
        />
      </div>

      <div class="field">
        <label for="smtp-user">{t('setup.smtpUser')}</label>
        <input
          id="smtp-user"
          class="input"
          type="text"
          bind:value={user}
          placeholder={t('setup.smtpUserPlaceholder')}
          autocomplete="off"
        />
      </div>

      <div class="field">
        <label for="smtp-password">{t('setup.smtpPassword')}</label>
        <input
          id="smtp-password"
          class="input"
          type="password"
          bind:value={password}
          placeholder={passwordSet ? t('setup.smtpPasswordSet') : t('setup.smtpPasswordPlaceholder')}
          autocomplete="new-password"
        />
        {#if passwordSet}
          <p class="help">{t('setup.smtpPasswordSet')}</p>
        {/if}
      </div>

      <div class="field span-2">
        <label for="smtp-from">{t('setup.smtpFrom')}</label>
        <input
          id="smtp-from"
          class="input"
          type="text"
          bind:value={sender}
          placeholder={t('setup.smtpFromPlaceholder')}
          autocomplete="off"
        />
      </div>

      <div class="field span-2">
        <label class="checkbox-label">
          <input type="checkbox" bind:checked={tls} />
          <span>{t('setup.smtpTls')}</span>
        </label>
      </div>
    </div>

    {#if error}<p class="field-error" role="alert">{error}</p>{/if}

    <div class="actions">
      {#if saved}<span class="help success-msg">{t('setup.smtpSaved')}</span>{/if}
      <button type="submit" class="btn btn-solid" disabled={busy}>
        {busy ? t('setup.smtpSaving') : t('setup.smtpSave')}
      </button>
    </div>
  </form>

  <hr class="divider" />

  <form class="step test-section" onsubmit={runTest}>
    <h3 class="title small">{t('setup.smtpTestTitle')}</h3>
    <p class="help">{t('setup.smtpTestLede')}</p>

    <div class="test-row">
      <div class="field flex-grow">
        <label for="smtp-test-email">{t('setup.smtpTestEmail')}</label>
        <input
          id="smtp-test-email"
          class="input"
          type="email"
          bind:value={testEmail}
          placeholder={t('setup.smtpTestEmailPlaceholder')}
        />
      </div>
      <button
        type="submit"
        class="btn btn-ghost align-bottom"
        disabled={testBusy || !testEmail.trim()}
      >
        {testBusy ? t('setup.smtpTesting') : t('setup.smtpTestButton')}
      </button>
    </div>

    {#if testSuccess}<p class="success-msg" role="status">{testSuccess}</p>{/if}
    {#if testError}<p class="field-error" role="alert">{testError}</p>{/if}
  </form>
</div>

<style>
  .smtp-container {
    display: flex;
    flex-direction: column;
    gap: var(--s6);
  }

  .step {
    display: flex;
    flex-direction: column;
    gap: var(--s4);
  }

  .small {
    font-size: var(--t-small);
  }

  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--s4);
  }

  .span-2 {
    grid-column: span 2;
  }

  .notice-box {
    background: var(--paper-warm, rgba(255, 255, 255, 0.04));
    border-left: 3px solid var(--accent, #6366f1);
    padding: var(--s3) var(--s4);
    border-radius: 4px;
  }

  .checkbox-label {
    display: flex;
    align-items: center;
    gap: var(--s2);
    cursor: pointer;
    font-size: var(--t-body);
    user-select: none;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: var(--s3);
    padding-top: var(--s4);
    border-top: 1px solid var(--rule);
  }

  .divider {
    border: none;
    border-top: 1px solid var(--rule);
    margin: var(--s2) 0;
  }

  .test-section {
    padding: var(--s4);
    background: var(--paper-warm, rgba(255, 255, 255, 0.02));
    border-radius: 6px;
    border: 1px solid var(--rule);
  }

  .test-row {
    display: flex;
    gap: var(--s3);
    align-items: flex-end;
  }

  .flex-grow {
    flex: 1;
  }

  .align-bottom {
    margin-bottom: 2px;
  }

  .success-msg {
    color: var(--ok, #10b981);
    font-size: var(--t-small);
  }

  @media (max-width: 640px) {
    .grid {
      grid-template-columns: 1fr;
    }
    .span-2 {
      grid-column: span 1;
    }
    .test-row {
      flex-direction: column;
      align-items: stretch;
    }
  }
</style>
