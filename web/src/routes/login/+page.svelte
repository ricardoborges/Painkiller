<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import type { AuthConfig } from '$lib/types';
  import { auth } from '$lib/stores/auth.svelte';
  import Icon from '$lib/components/Icon.svelte';

  let username = $state('');
  let password = $state('');
  let error = $state<string | null>(null);
  let busy = $state(false);
  // Na dúvida (config não carregou), mostra as duas portas de entrada.
  let config = $state<AuthConfig>({ google: true, break_glass: true });
  // O acesso break-glass fica recolhido quando o Google está disponível.
  let showBreakGlass = $state(false);

  onMount(async () => {
    // O callback do Google volta para /login#token=… ou /login#error=…
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    if (fragment.has('token') || fragment.has('error')) {
      history.replaceState(null, '', window.location.pathname);
    }
    const token = fragment.get('token');
    if (token) {
      busy = true;
      try {
        await auth.signInWithToken(token);
        await goto('/projetos', { replaceState: true });
        return;
      } catch (e) {
        error = e instanceof Error ? e.message : 'Não foi possível entrar.';
      } finally {
        busy = false;
      }
    } else if (fragment.get('error')) {
      error = fragment.get('error');
    }

    try {
      config = await api.authConfig();
    } catch {
      /* servidor fora: mantém as duas opções visíveis */
    }
    showBreakGlass = config.break_glass && !config.google;
  });

  function signInWithGoogle() {
    busy = true;
    // Navegação de página inteira: o fluxo OAuth passa pelo Google e volta.
    window.location.href = '/api/auth/google/login';
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    error = null;
    busy = true;
    try {
      await auth.signIn(username, password);
      await goto('/projetos', { replaceState: true });
    } catch (e) {
      error = e instanceof Error ? e.message : 'Não foi possível entrar.';
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>Entrar — Painkiller</title></svelte:head>

<!-- Assimétrico por decisão: formulário à esquerda, colofão à direita.
     Nenhum cartão centralizado. -->
<div class="page">
  <section class="form-side">
    <div class="inner">
      <div class="brand">
        <span class="mark" aria-hidden="true"></span>
        <span class="word">Painkiller</span>
      </div>

      <h1 class="display">
        Orquestração de<br />agentes de codificação.
      </h1>

      {#if config.google}
        <div class="sso">
          <button type="button" class="btn btn-solid submit" onclick={signInWithGoogle} disabled={busy}>
            Entrar com Google
            {#if !busy}<Icon name="arrow-right" />{/if}
          </button>
          <p class="help">
            No primeiro acesso a conta é criada, junto com um usuário no Gitea que só
            enxerga os seus repositórios.
          </p>
          {#if error && !showBreakGlass}
            <p class="field-error" role="alert">{error}</p>
          {/if}
          {#if config.break_glass && !showBreakGlass}
            <button type="button" class="link" onclick={() => (showBreakGlass = true)}>
              Acesso de emergência (administrador)
            </button>
          {/if}
        </div>
      {/if}

      {#if showBreakGlass || (!config.google && !config.break_glass)}
      <form onsubmit={submit} novalidate>
        <div class="field">
          <label for="u">Usuário</label>
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
          <label for="p">Senha</label>
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
          <p class="field-error" role="alert">{error}</p>
        {/if}

        <button
          type="submit"
          class="btn submit {config.google ? 'btn-line' : 'btn-solid'}"
          disabled={busy || !config.break_glass}
        >
          {busy ? 'Entrando…' : 'Entrar'}
          {#if !busy}<Icon name="arrow-right" />{/if}
        </button>

        <p class="help">
          {#if config.break_glass}
            Conta break-glass do administrador, definida no servidor
            (<span class="mono">PAINKILLER_ADMIN_USER</span> e
            <span class="mono">PAINKILLER_ADMIN_PASSWORD</span>). Enxerga todos os projetos.
          {:else}
            Nenhuma forma de entrar está configurada. Defina
            <span class="mono">PAINKILLER_ADMIN_PASSWORD</span> ou as credenciais do
            Google no <span class="mono">.env</span> do servidor.
          {/if}
        </p>
      </form>
      {/if}
    </div>
  </section>

  <aside class="colophon">
    <div class="inner">
      <span class="label">O sistema</span>
      <dl>
        <div><dt>Arquitetura</dt><dd class="mono">Ports &amp; Adapters</dd></div>
        <div><dt>Agente</dt><dd class="mono">Antigravity CLI (agy), contêiner efêmero</dd></div>
        <div><dt>Isolamento</dt><dd class="mono">1 branch por tarefa</dd></div>
        <div><dt>Interrupção</dt><dd class="mono">exit 42</dd></div>
      </dl>

      <p class="note lede">
        Quando o agente encontra ambiguidade ele não chuta: roda
        <span class="mono">painkiller ask</span>, commita o trabalho em andamento
        e devolve a pergunta ao analista.
      </p>
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
    /* Respiro assimétrico à esquerda, escalando com a viewport */
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

  .submit {
    align-self: flex-start;
    margin-top: var(--s1);
  }

  .sso {
    display: flex;
    flex-direction: column;
    gap: var(--s3);
    border-top: 1px solid var(--rule-ink);
    padding-top: var(--s5);
    margin-bottom: var(--s6);
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

  .link:hover {
    color: var(--ink);
  }

  .help {
    margin-top: var(--s2);
    max-width: 38ch;
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

    .colophon {
      border-left: 0;
      border-top: 1px solid var(--rule);
      padding-block: var(--s6);
    }
  }
</style>
