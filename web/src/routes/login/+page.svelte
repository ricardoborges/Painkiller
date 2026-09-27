<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import type { AuthConfig } from '$lib/types';
  import { auth } from '$lib/stores/auth.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import LocaleSwitch from '$lib/components/LocaleSwitch.svelte';

  type Mode = 'login' | 'register' | 'verify';
  let mode = $state<Mode>('login');

  // Login
  let username = $state('');
  let password = $state('');

  // Register
  let firstName = $state('');
  let lastName = $state('');
  let registerEmail = $state('');
  let registerPassword = $state('');
  let confirmPassword = $state('');

  // Verify
  let verifyEmail = $state('');
  let verifyCode = $state('');
  let resendCooldown = $state(0);
  let cooldownTimer: number | null = null;

  let error = $state<string | null>(null);
  let success = $state<string | null>(null);
  let busy = $state(false);

  // Na dúvida (config não carregou), mostra as opções.
  let config = $state<AuthConfig>({ google: true, break_glass: true, first_access: false });

  onMount(async () => {
    // Callback do Google volta para /login#token=… ou /login#error=…
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const query = new URLSearchParams(window.location.search);

    if (fragment.has('token') || fragment.has('error')) {
      history.replaceState(null, '', window.location.pathname);
    }

    const token = fragment.get('token');
    if (token) {
      busy = true;
      try {
        await auth.signInWithToken(token);
        await goto('/projects', { replaceState: true });
        return;
      } catch (e) {
        error = e instanceof Error ? e.message : t('login.failed');
      } finally {
        busy = false;
      }
    } else if (fragment.get('error')) {
      error = fragment.get('error');
    }

    if (query.get('verified') === 'true') {
      success = t('login.verifiedSuccess');
    }

    try {
      config = await api.authConfig();
    } catch {
      /* servidor fora: mantém opções visíveis */
    }
    if (config.first_access) {
      await goto('/first-access', { replaceState: true });
      return;
    }
  });

  function signInWithGoogle() {
    busy = true;
    window.location.href = '/api/auth/google/login';
  }

  async function submitLogin(e: SubmitEvent) {
    e.preventDefault();
    error = null;
    success = null;
    busy = true;
    try {
      await auth.signIn(username, password);
      await goto('/projects', { replaceState: true });
    } catch (e) {
      const msg = e instanceof Error ? e.message : t('login.failed');
      error = msg;
      // Se a conta não estiver ativada, facilita ir para a tela de verificação
      if (msg.toLowerCase().includes('ativada') || msg.toLowerCase().includes('activated')) {
        verifyEmail = username;
      }
    } finally {
      busy = false;
    }
  }

  async function submitRegister(e: SubmitEvent) {
    e.preventDefault();
    error = null;
    success = null;

    if (!firstName.trim() || !lastName.trim() || !registerEmail.trim() || !registerPassword) {
      error = t('register.requiredFields');
      return;
    }
    if (registerPassword !== confirmPassword) {
      error = t('register.passwordMismatch');
      return;
    }
    if (registerPassword.length < 8) {
      error = t('register.passwordTooShort');
      return;
    }

    busy = true;
    try {
      const res = await api.register({
        first_name: firstName,
        last_name: lastName,
        email: registerEmail,
        password: registerPassword,
        confirm_password: confirmPassword
      });
      verifyEmail = res.email || registerEmail;
      mode = 'verify';
      startResendCooldown();
    } catch (e) {
      error = e instanceof Error ? e.message : t('register.failed');
    } finally {
      busy = false;
    }
  }

  async function submitVerify(e: SubmitEvent) {
    e.preventDefault();
    error = null;
    success = null;
    if (!verifyCode.trim()) return;

    busy = true;
    try {
      const res = await api.verifyCode({
        email: verifyEmail,
        code: verifyCode.trim()
      });
      auth.adopt(res);
      await goto('/projects', { replaceState: true });
    } catch (e) {
      error = e instanceof Error ? e.message : t('verify.failed');
    } finally {
      busy = false;
    }
  }

  function startResendCooldown() {
    resendCooldown = 60;
    if (cooldownTimer) clearInterval(cooldownTimer);
    cooldownTimer = window.setInterval(() => {
      resendCooldown -= 1;
      if (resendCooldown <= 0 && cooldownTimer) {
        clearInterval(cooldownTimer);
        cooldownTimer = null;
      }
    }, 1000);
  }

  async function resendVerificationCode() {
    if (resendCooldown > 0 || busy) return;
    error = null;
    success = null;
    busy = true;
    try {
      await api.resendCode(verifyEmail);
      success = t('verify.resendSuccess');
      startResendCooldown();
    } catch (e) {
      error = e instanceof Error ? e.message : t('verify.failed');
    } finally {
      busy = false;
    }
  }

  function switchMode(newMode: Mode) {
    mode = newMode;
    error = null;
    success = null;
  }
</script>

<svelte:head><title>{t('login.pageTitle')} — Painkiller</title></svelte:head>

<div class="corner-switch"><LocaleSwitch /></div>

<!-- Assimétrico por decisão: formulário à esquerda, colofão à direita.
     Nenhum cartão centralizado. -->
<div class="page">
  <section class="form-side">
    <div class="inner">
      <div class="brand">
        <span class="mark" aria-hidden="true"></span>
        <span class="word">Painkiller</span>
      </div>

      <h1 class="display">{@html t('login.headline')}</h1>

      {#if mode === 'login'}
        {#if config.google}
          <div class="sso">
            <button type="button" class="btn btn-solid submit-btn" onclick={signInWithGoogle} disabled={busy}>
              {t('login.google')}
              {#if !busy}<Icon name="arrow-right" />{/if}
            </button>
          </div>
          <div class="divider"><span>{t('login.orDivider')}</span></div>
        {/if}

        <form onsubmit={submitLogin} novalidate>
          <div class="field">
            <label for="u">{t('common.username')}</label>
            <input
              id="u"
              class="input"
              bind:value={username}
              autocomplete="username"
              required
              aria-invalid={error ? 'true' : undefined}
            />
          </div>

          <div class="field">
            <label for="p">{t('common.password')}</label>
            <input
              id="p"
              class="input"
              type="password"
              bind:value={password}
              autocomplete="current-password"
              required
              aria-invalid={error ? 'true' : undefined}
            />
          </div>

          {#if error}
            <div class="error-box">
              <p class="field-error" role="alert">{error}</p>
              {#if verifyEmail && (error.toLowerCase().includes('ativada') || error.toLowerCase().includes('activated'))}
                <button type="button" class="link verify-link" onclick={() => switchMode('verify')}>
                  {t('verify.title')} &rarr;
                </button>
              {/if}
            </div>
          {/if}

          {#if success}
            <p class="field-success" role="status">{success}</p>
          {/if}

          <div class="actions">
            <button
              type="submit"
              class="btn btn-solid submit-btn"
              disabled={busy}
            >
              {busy ? t('login.signingIn') : t('login.signIn')}
              {#if !busy}<Icon name="arrow-right" />{/if}
            </button>

            <button
              type="button"
              class="btn btn-line"
              onclick={() => switchMode('register')}
              disabled={busy}
            >
              {t('login.createAccount')}
            </button>
          </div>
        </form>

      {:else if mode === 'register'}
        <form onsubmit={submitRegister} novalidate>
          <div class="name-row">
            <div class="field">
              <label for="first-name">{t('register.firstName')}</label>
              <input
                id="first-name"
                class="input"
                bind:value={firstName}
                autocomplete="given-name"
                required
              />
            </div>
            <div class="field">
              <label for="last-name">{t('register.lastName')}</label>
              <input
                id="last-name"
                class="input"
                bind:value={lastName}
                autocomplete="family-name"
                required
              />
            </div>
          </div>

          <div class="field">
            <label for="reg-email">{t('register.email')}</label>
            <input
              id="reg-email"
              class="input"
              type="email"
              bind:value={registerEmail}
              autocomplete="email"
              required
            />
          </div>

          <div class="field">
            <label for="reg-password">{t('register.password')}</label>
            <input
              id="reg-password"
              class="input"
              type="password"
              bind:value={registerPassword}
              autocomplete="new-password"
              required
            />
          </div>

          <div class="field">
            <label for="reg-confirm">{t('register.confirmPassword')}</label>
            <input
              id="reg-confirm"
              class="input"
              type="password"
              bind:value={confirmPassword}
              autocomplete="new-password"
              required
            />
          </div>

          {#if error}
            <p class="field-error" role="alert">{error}</p>
          {/if}

          <div class="actions">
            <button
              type="submit"
              class="btn btn-solid submit-btn"
              disabled={busy}
            >
              {busy ? t('register.creating') : t('register.submit')}
              {#if !busy}<Icon name="arrow-right" />{/if}
            </button>

            <button
              type="button"
              class="link"
              onclick={() => switchMode('login')}
              disabled={busy}
            >
              {t('login.backToLogin')}
            </button>
          </div>
        </form>

      {:else if mode === 'verify'}
        <form onsubmit={submitVerify} novalidate>
          <div class="verify-header">
            <h2 class="title">{t('verify.title')}</h2>
            <p class="help">
              {t('verify.instruction')} <strong>{verifyEmail}</strong>.
            </p>
          </div>

          <div class="field">
            <label for="v-code">{t('verify.codeLabel')}</label>
            <input
              id="v-code"
              class="input code-input"
              bind:value={verifyCode}
              placeholder={t('verify.codePlaceholder')}
              maxlength="6"
              autocomplete="one-time-code"
              required
            />
          </div>

          {#if error}
            <p class="field-error" role="alert">{error}</p>
          {/if}

          {#if success}
            <p class="field-success" role="status">{success}</p>
          {/if}

          <div class="actions">
            <button
              type="submit"
              class="btn btn-solid submit-btn"
              disabled={busy || !verifyCode.trim()}
            >
              {busy ? t('verify.verifying') : t('verify.submit')}
              {#if !busy}<Icon name="arrow-right" />{/if}
            </button>

            <button
              type="button"
              class="link"
              onclick={resendVerificationCode}
              disabled={busy || resendCooldown > 0}
            >
              {t('verify.resend')}{resendCooldown > 0 ? ` (${resendCooldown}s)` : ''}
            </button>
          </div>

          <p class="help note-help">{t('verify.orLink')}</p>

          <div class="back-link">
            <button
              type="button"
              class="link"
              onclick={() => switchMode('login')}
              disabled={busy}
            >
              &larr; {t('login.backToLogin')}
            </button>
          </div>
        </form>
      {/if}
    </div>
  </section>

  <aside class="colophon">
    <div class="inner">
      <span class="label">{t('login.system')}</span>
      <dl>
        <div><dt>{t('login.architecture')}</dt><dd class="mono">Ports &amp; Adapters</dd></div>
        <div><dt>{t('login.agent')}</dt><dd class="mono">{t('login.agentValue')}</dd></div>
        <div><dt>{t('login.isolation')}</dt><dd class="mono">{t('login.isolationValue')}</dd></div>
        <div><dt>{t('login.interruption')}</dt><dd class="mono">exit 42</dd></div>
      </dl>

      <p class="note lede">{@html t('login.note')}</p>
    </div>
  </aside>
</div>

<style>
  .page {
    display: grid;
    grid-template-columns: 1.35fr 1fr;
    min-height: 100dvh;
  }

  .form-side {
    display: flex;
    align-items: center;
    padding: var(--s7) var(--gutter);
  }

  .form-side .inner {
    width: 100%;
    max-width: 27rem;
    margin-left: auto;
    margin-right: clamp(0rem, 4vw, 5rem);
  }

  .brand {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    margin-bottom: var(--s7);
  }

  .mark {
    width: 9px;
    height: 9px;
    background: var(--accent);
  }

  .word {
    font-size: var(--t-small);
    font-weight: 600;
  }

  h1 {
    margin-bottom: var(--s7);
  }

  form {
    display: flex;
    flex-direction: column;
    gap: var(--s4);
    border-top: 1px solid var(--rule-ink);
    padding-top: var(--s5);
  }

  .sso {
    display: flex;
    flex-direction: column;
    gap: var(--s3);
    border-top: 1px solid var(--rule-ink);
    padding-top: var(--s5);
  }

  .divider {
    display: flex;
    align-items: center;
    gap: var(--s3);
    margin: var(--s4) 0 var(--s2);
    color: var(--ink-2);
    font-size: var(--t-small);
  }

  .divider::before,
  .divider::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--rule-2);
  }

  .name-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--s3);
  }

  .actions {
    display: flex;
    align-items: center;
    gap: var(--s4);
    margin-top: var(--s2);
    flex-wrap: wrap;
  }

  .submit-btn {
    align-self: flex-start;
  }

  .link {
    align-self: flex-start;
    padding: 0;
    border: 0;
    background: none;
    font: inherit;
    font-size: var(--t-small);
    color: var(--ink-2);
    text-decoration: underline;
    text-underline-offset: 3px;
    cursor: pointer;
  }

  .link:hover:not(:disabled) {
    color: var(--ink);
  }

  .link:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .verify-link {
    display: inline-block;
    margin-top: var(--s1);
    color: var(--ink);
    font-weight: 500;
  }

  .error-box {
    display: flex;
    flex-direction: column;
    gap: var(--s1);
  }

  .field-success {
    font-size: var(--t-small);
    color: var(--success, #16a34a);
    margin: 0;
  }

  .help {
    margin-top: var(--s1);
    font-size: var(--t-small);
    color: var(--ink-2);
    max-width: 38ch;
  }

  .help strong {
    color: var(--ink);
  }

  .note-help {
    margin-top: var(--s3);
    border-top: 1px solid var(--rule);
    padding-top: var(--s3);
  }

  .back-link {
    margin-top: var(--s2);
  }

  .code-input {
    font-size: 1.25rem;
    letter-spacing: 0.25em;
    text-align: center;
    font-family: var(--font-mono, monospace);
  }

  .verify-header h2 {
    font-size: 1.15rem;
    font-weight: 600;
    margin-bottom: var(--s1);
  }

  .colophon {
    display: flex;
    align-items: center;
    border-left: 1px solid var(--rule);
    background: var(--paper-sunk);
    padding: var(--s7) var(--gutter);
  }

  .colophon .inner {
    max-width: 24rem;
  }

  dl {
    margin: var(--s4) 0 0;
    border-top: 1px solid var(--rule-2);
  }

  dl > div {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: var(--s4);
    padding: var(--s3) 0;
    border-bottom: 1px solid var(--rule);
  }

  dt {
    font-size: var(--t-small);
    color: var(--ink-2);
  }

  dd {
    margin: 0;
    font-size: var(--t-small);
    text-align: right;
  }

  .note {
    margin-top: var(--s5);
    font-size: var(--t-small);
  }

  @media (max-width: 880px) {
    .page {
      grid-template-columns: 1fr;
      min-height: auto;
    }

    .form-side {
      padding-block: var(--s7) var(--s6);
    }

    .form-side .inner {
      margin-inline: 0;
      max-width: 32rem;
    }

    .name-row {
      grid-template-columns: 1fr;
    }

    .colophon {
      border-left: 0;
      border-top: 1px solid var(--rule);
      padding-block: var(--s6);
    }
  }
</style>
