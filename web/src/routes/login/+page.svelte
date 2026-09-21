<script lang="ts">
  import { goto } from '$app/navigation';
  import { auth } from '$lib/stores/auth.svelte';
  import Icon from '$lib/components/Icon.svelte';

  let username = $state('admin');
  let password = $state('');
  let error = $state<string | null>(null);
  let busy = $state(false);

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

        <button type="submit" class="btn btn-solid submit" disabled={busy}>
          {busy ? 'Entrando…' : 'Entrar'}
          {#if !busy}<Icon name="arrow-right" />{/if}
        </button>

        <p class="help">
          Autenticação de usuário único, fixada no código do servidor
          (<span class="mono">routes/auth.py</span>). Não é fronteira de segurança.
        </p>
      </form>
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
