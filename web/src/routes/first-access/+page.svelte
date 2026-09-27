<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api, ApiError } from '$lib/api';
  import { auth } from '$lib/stores/auth.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import LocaleSwitch from '$lib/components/LocaleSwitch.svelte';

  const MIN_PASSWORD = 12;

  let username = $state('admin');
  let password = $state('');
  let confirm = $state('');
  let touched = $state(false);
  let busy = $state(false);
  let checking = $state(true);
  let error = $state<string | null>(null);

  onMount(async () => {
    // Só existe numa instalação nova; depois disso, o caminho é o login.
    try {
      const config = await api.authConfig();
      if (!config.first_access) {
        await goto('/login', { replaceState: true });
        return;
      }
    } catch {
      /* servidor fora: o envio mostra o erro */
    }
    checking = false;
  });

  const problems = $derived({
    username: !username.trim() || /\s/.test(username.trim()),
    password: password.length < MIN_PASSWORD,
    confirm: confirm !== password
  });
  const invalid = $derived(problems.username || problems.password || problems.confirm);

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    touched = true;
    if (invalid) return;
    busy = true;
    error = null;
    try {
      await auth.createAdmin(username.trim(), password);
      // O layout manda o admin ao wizard de setup, que ainda não foi concluído.
      await goto('/setup', { replaceState: true });
    } catch (err) {
      error = err instanceof Error ? err.message : t('firstAccess.failed');
      if (err instanceof ApiError && err.status === 409) {
        setTimeout(() => goto('/login', { replaceState: true }), 1500);
      }
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>{t('firstAccess.title')} — Painkiller</title></svelte:head>

<div class="corner-switch"><LocaleSwitch /></div>

<div class="page">
  <section class="form-side">
    <div class="inner">
      <div class="brand">
        <span class="mark" aria-hidden="true"></span>
        <span class="word">Painkiller</span>
      </div>

      <span class="label">{t('firstAccess.title')}</span>
      <h1 class="display">{@html t('firstAccess.headline')}</h1>

      {#if !checking}
        <form onsubmit={submit} novalidate>
          <div class="field">
            <label for="fa-user">{t('common.username')}</label>
            <input
              id="fa-user"
              class="input"
              bind:value={username}
              autocomplete="username"
              aria-invalid={touched && problems.username ? 'true' : undefined}
            />
            {#if touched && problems.username}<p class="field-error">{t('firstAccess.usernameError')}</p>{/if}
          </div>

          <div class="field">
            <label for="fa-pass">{t('common.password')}</label>
            <input
              id="fa-pass"
              class="input"
              type="password"
              bind:value={password}
              autocomplete="new-password"
              aria-invalid={touched && problems.password ? 'true' : undefined}
            />
            <p class="help">{t('firstAccess.passwordHelp', { min: MIN_PASSWORD })}</p>
            {#if touched && problems.password}
              <p class="field-error">{t('firstAccess.passwordError', { min: MIN_PASSWORD })}</p>
            {/if}
          </div>

          <div class="field">
            <label for="fa-confirm">{t('firstAccess.confirm')}</label>
            <input
              id="fa-confirm"
              class="input"
              type="password"
              bind:value={confirm}
              autocomplete="new-password"
              aria-invalid={touched && problems.confirm ? 'true' : undefined}
            />
            {#if touched && problems.confirm}<p class="field-error">{t('firstAccess.mismatch')}</p>{/if}
          </div>

          {#if error}<p class="field-error" role="alert">{error}</p>{/if}

          <button type="submit" class="btn btn-solid submit" disabled={busy}>
            {busy ? t('sessionPicker.creating') : t('firstAccess.create')}
            {#if !busy}<Icon name="arrow-right" />{/if}
          </button>
        </form>
      {/if}
    </div>
  </section>

  <aside class="colophon">
    <div class="inner">
      <span class="label">{t('firstAccess.next')}</span>
      <ol class="next">
        <li>
          <span class="mono n">1</span>
          <div>{t('firstAccess.next1')}</div>
        </li>
        <li>
          <span class="mono n">2</span>
          <div>{t('firstAccess.next2')}</div>
        </li>
        <li>
          <span class="mono n">3</span>
          <div>{@html t('firstAccess.next3')}</div>
        </li>
      </ol>
      <p class="note lede">{t('firstAccess.note')}</p>
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
    margin: var(--s2) 0 var(--s7);
  }

  form {
    display: flex;
    flex-direction: column;
    gap: var(--s4);
    border-top: 1px solid var(--rule-ink);
    padding-top: var(--s5);
  }

  .submit {
    align-self: flex-start;
    margin-top: var(--s1);
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

  .next {
    margin-top: var(--s4);
    border-top: 1px solid var(--rule-2);
  }

  .next li {
    display: grid;
    grid-template-columns: 1.25rem 1fr;
    gap: var(--s2);
    padding: var(--s3) 0;
    border-bottom: 1px solid var(--rule);
    font-size: var(--t-small);
    color: var(--ink-2);
  }

  .n {
    color: var(--ink-3);
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

    .colophon {
      border-left: 0;
      border-top: 1px solid var(--rule);
      padding-block: var(--s6);
    }
  }
</style>
