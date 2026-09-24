<script lang="ts">
  import { api } from '$lib/api';
  import { setup } from '$lib/stores/setup.svelte';
  import Icon from '../Icon.svelte';
  import CopyValue from './CopyValue.svelte';

  let {
    mode = 'wizard',
    onsaved
  }: {
    mode?: 'wizard' | 'settings';
    onsaved?: () => void;
  } = $props();

  const google = $derived(setup.state!.google);

  let clientId = $state('');
  let clientSecret = $state('');
  let domains = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);
  let saved = $state(false);

  let seeded = false;
  $effect(() => {
    if (seeded || !setup.state) return;
    seeded = true;
    clientId = setup.state.google.client_id;
    domains = setup.state.google.allowed_domains;
  });

  const CONSOLE = 'https://console.cloud.google.com/apis/credentials';
  const CONSENT = 'https://console.cloud.google.com/auth/overview';

  async function save(e: SubmitEvent) {
    e.preventDefault();
    busy = true;
    error = null;
    saved = false;
    try {
      setup.set(
        await api.saveSetupGoogle({
          client_id: clientId.trim(),
          client_secret: clientSecret.trim() || undefined,
          allowed_domains: domains.trim()
        })
      );
      clientSecret = '';
      saved = true;
      onsaved?.();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Não foi possível salvar.';
    } finally {
      busy = false;
    }
  }

  async function skip() {
    busy = true;
    error = null;
    try {
      setup.set(await api.skipSetupStep('google'));
      onsaved?.();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Não foi possível pular a etapa.';
    } finally {
      busy = false;
    }
  }
</script>

<form class="step" onsubmit={save}>
  <p class="lede small">
    Opcional. Sem ele, só o administrador entra, com usuário e senha. Com ele, cada pessoa entra com a
    própria conta Google, ganha a própria conta no Gitea e vê só os próprios projetos.
  </p>

  <section class="tutorial">
    <h3 class="label">No Google Cloud Console</h3>
    <ol class="steps">
      <li>
        <span class="n mono">1</span>
        <div>
          Configure a tela de consentimento (tipo <strong>Externo</strong> ou <strong>Interno</strong>, se
          for Google Workspace).
          <a href={CONSENT} target="_blank" rel="noopener noreferrer" class="ext">
            Abrir Google Auth Platform <Icon name="external" size={11} />
          </a>
        </div>
      </li>
      <li>
        <span class="n mono">2</span>
        <div>
          Em <strong>Credenciais</strong>, crie um <strong>ID do cliente OAuth</strong> do tipo
          <strong>Aplicativo da Web</strong>.
          <a href={CONSOLE} target="_blank" rel="noopener noreferrer" class="ext">
            Abrir Credenciais <Icon name="external" size={11} />
          </a>
        </div>
      </li>
      <li>
        <span class="n mono">3</span>
        <div class="uris">
          Em <strong>URIs de redirecionamento autorizados</strong>, cadastre as duas:
          <CopyValue label="Painkiller" value={google.redirect_uris.painkiller} />
          <CopyValue label="Gitea (login único)" value={google.redirect_uris.gitea} />
        </div>
      </li>
      <li>
        <span class="n mono">4</span>
        <div>Copie o <strong>ID do cliente</strong> e a <strong>Chave secreta</strong> para os campos abaixo.</div>
      </li>
    </ol>
  </section>

  <div class="grid">
    <div class="field">
      <label for="g-id">ID do cliente</label>
      <input
        id="g-id"
        class="input mono"
        bind:value={clientId}
        placeholder="123456789-abc.apps.googleusercontent.com"
        autocomplete="off"
      />
    </div>
    <div class="field">
      <label for="g-secret">Chave secreta do cliente</label>
      <input
        id="g-secret"
        type="password"
        class="input mono"
        bind:value={clientSecret}
        placeholder={google.has_secret ? `Salva (${google.masked_secret}) — deixe em branco para manter` : 'GOCSPX-…'}
        autocomplete="off"
      />
    </div>
  </div>

  <div class="field">
    <label for="g-domains">Domínios permitidos</label>
    <input id="g-domains" class="input mono" bind:value={domains} placeholder="empresa.com.br, parceiro.com" />
    <p class="help">Vazio = qualquer conta Google com e-mail verificado pode se cadastrar.</p>
  </div>

  {#if error}<p class="field-error" role="alert">{error}</p>{/if}

  <div class="actions">
    {#if saved && mode === 'settings'}<span class="help">Salvo. O botão "Entrar com Google" já está ativo.</span>{/if}
    {#if mode === 'wizard'}
      <button type="button" class="btn btn-quiet" onclick={skip} disabled={busy}>Pular — configuro depois</button>
    {/if}
    <button type="submit" class="btn btn-solid" disabled={busy || !clientId.trim()}>
      {busy ? 'Salvando…' : mode === 'wizard' ? 'Salvar e continuar' : 'Salvar'}
    </button>
  </div>
</form>

<style>
  .step {
    display: flex;
    flex-direction: column;
    gap: var(--s5);
  }

  .small {
    font-size: var(--t-small);
  }

  .tutorial {
    display: flex;
    flex-direction: column;
    gap: var(--s3);
  }

  .steps {
    display: flex;
    flex-direction: column;
    border-top: 1px solid var(--rule);
  }

  .steps li {
    display: grid;
    grid-template-columns: 1.5rem 1fr;
    gap: var(--s3);
    padding: var(--s3) 0;
    border-bottom: 1px solid var(--rule);
    font-size: var(--t-small);
    color: var(--ink-2);
  }

  .steps strong {
    color: var(--ink);
    font-weight: 500;
  }

  .n {
    color: var(--ink-3);
  }

  .ext {
    display: inline-flex;
    align-items: center;
    gap: var(--s1);
    margin-left: var(--s1);
    color: var(--ink);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .uris {
    display: flex;
    flex-direction: column;
    gap: var(--s2);
  }

  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--s4);
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: var(--s3);
    padding-top: var(--s4);
    border-top: 1px solid var(--rule);
  }

  @media (max-width: 640px) {
    .grid {
      grid-template-columns: 1fr;
    }
  }
</style>
