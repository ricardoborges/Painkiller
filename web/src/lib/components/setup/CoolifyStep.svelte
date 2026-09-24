<script lang="ts">
  import { api } from '$lib/api';
  import { setup } from '$lib/stores/setup.svelte';
  import type { CoolifyStatus } from '$lib/types';
  import Icon from '../Icon.svelte';
  import Skeleton from '../Skeleton.svelte';
  import Check from './Check.svelte';
  import CopyValue from './CopyValue.svelte';

  let {
    mode = 'wizard',
    onsaved
  }: {
    mode?: 'wizard' | 'settings';
    onsaved?: () => void;
  } = $props();

  const coolify = $derived(setup.state!.coolify);
  const dash = $derived(coolify.dashboard_url);

  let status = $state<CoolifyStatus | null>(null);
  let loadingStatus = $state(true);

  let email = $state('admin@painkiller.local');
  let automating = $state(false);
  /** Credenciais mostradas uma vez, logo depois de a automação criar a conta. */
  let created = $state<{ email: string; password: string } | null>(null);
  let revealed = $state<{ email: string; password: string | null } | null>(null);

  let manual = $state(false);
  let token = $state('');
  let wildcard = $state('');
  let serverUuid = $state('');
  let dashboardUrl = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);
  let saved = $state(false);

  let seeded = false;
  $effect(() => {
    if (seeded || !setup.state) return;
    seeded = true;
    wildcard = setup.state.coolify.wildcard_domain;
    serverUuid = setup.state.coolify.server_uuid;
    dashboardUrl = setup.state.coolify.dashboard_url;
    refresh();
  });

  async function refresh() {
    loadingStatus = true;
    try {
      status = await api.coolifyStatus();
      if (status.coolify.server_uuid && !serverUuid) serverUuid = status.coolify.server_uuid;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Não foi possível consultar o Coolify.';
    } finally {
      loadingStatus = false;
    }
  }

  const container = $derived(status?.container);
  const apiCheck = $derived(status?.api);
  const servers = $derived(apiCheck?.servers ?? []);
  const ready = $derived(Boolean(apiCheck?.token_ok));
  const deployServer = $derived(servers.find((s) => s.uuid === serverUuid) ?? servers[0]);

  async function automate() {
    automating = true;
    error = null;
    created = null;
    try {
      const result = await api.bootstrapCoolify(email.trim());
      setup.set(result.state);
      if (result.password) created = { email: result.email, password: result.password };
      await refresh();
    } catch (e) {
      error = e instanceof Error ? e.message : 'A automação falhou. Use o passo a passo manual.';
      manual = true;
    } finally {
      automating = false;
    }
  }

  async function reveal() {
    try {
      revealed = await api.coolifyCredentials();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Credenciais indisponíveis.';
    }
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    busy = true;
    error = null;
    saved = false;
    try {
      setup.set(
        await api.saveSetupCoolify({
          api_token: token.trim() || undefined,
          server_uuid: serverUuid,
          wildcard_domain: wildcard.trim(),
          dashboard_url: dashboardUrl.trim() !== coolify.dashboard_url ? dashboardUrl.trim() : undefined
        })
      );
      token = '';
      saved = true;
      await refresh();
      onsaved?.();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Não foi possível salvar.';
    } finally {
      busy = false;
    }
  }

  async function skip() {
    busy = true;
    try {
      setup.set(await api.skipSetupStep('coolify'));
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
    Opcional. O Coolify publica cada tarefa concluída num ambiente de teste ("Testar") e o projeto em
    produção. Sem ele, o botão "Testar" só simula o endereço.
  </p>

  <section class="auto" aria-labelledby="c-auto-title">
    <div class="auto-head">
      <h3 id="c-auto-title" class="title">Configuração automática</h3>
      <span class="label">recomendado</span>
    </div>
    <p class="small muted">
      Um clique: cria a conta de administrador do Coolify (se ainda não existir), liga a API e gera um
      token com permissão total, tudo dentro do contêiner <span class="mono">painkiller-coolify</span>. O
      servidor de deploy já vem pronto: ao subir, o próprio Coolify registra este host como
      <span class="mono">localhost</span> e liga o proxy que publica os ambientes.
      {#if ready}Gerar de novo substitui o token atual.{/if}
    </p>
    <div class="auto-row">
      {#if status && !container?.root_user}
        <div class="field grow">
          <label for="c-email">E-mail da conta de administrador</label>
          <input id="c-email" class="input mono" type="email" bind:value={email} />
        </div>
      {/if}
      <button
        type="button"
        class="btn btn-solid auto-btn"
        onclick={automate}
        disabled={automating || !container?.reachable}
      >
        {automating ? 'Configurando…' : ready ? 'Gerar novo token' : 'Configurar automaticamente'}
      </button>
    </div>
    {#if status && !container?.reachable}
      <p class="help">O contêiner do Coolify precisa estar rodando: <span class="mono">docker compose up -d</span>.</p>
    {/if}
  </section>

  {#if created}
    <section class="once" role="status">
      <h3 class="label">Conta criada no Coolify — guarde a senha</h3>
      <p class="help">
        O Painkiller também a guarda cifrada; ela pode ser vista de novo em Admin → Configurações.
      </p>
      <CopyValue label="E-mail" value={created.email} />
      <CopyValue label="Senha" value={created.password} />
      <a href={`${dash}/login`} target="_blank" rel="noopener noreferrer" class="btn btn-line btn-sm open">
        Abrir o Coolify <Icon name="external" size={11} />
      </a>
    </section>
  {/if}

  <section class="block">
    <div class="block-head">
      <h3 class="label">Situação</h3>
      <button type="button" class="btn btn-quiet btn-sm" onclick={refresh} disabled={loadingStatus}>
        {loadingStatus ? 'Consultando…' : 'Verificar de novo'}
      </button>
    </div>
    {#if loadingStatus && !status}
      <Skeleton rows={4} />
    {:else if status}
      <ul class="checks">
        <Check
          state={container?.reachable ? 'ok' : 'fail'}
          label="Contêiner do Coolify rodando"
          detail={container?.reachable ? '' : (container?.error ?? '')}
        />
        <Check
          state={!container?.reachable ? 'unknown' : container.root_user ? 'ok' : 'pending'}
          label="Conta de administrador (root)"
          detail={container?.root_email ?? ''}
        />
        <Check
          state={!container?.reachable ? 'unknown' : container.api_enabled ? 'ok' : 'pending'}
          label="API ligada"
        />
        <Check
          state={ready ? 'ok' : coolify.has_token ? 'fail' : 'pending'}
          label="Token de API aceito"
          detail={ready ? `Coolify ${apiCheck?.version}` : (apiCheck?.error ?? '')}
        />
        <Check
          state={!ready ? 'unknown' : deployServer?.usable ? 'ok' : 'fail'}
          label="Servidor de deploy (este host)"
          detail={!ready
            ? 'Verificado depois que o token for aceito.'
            : deployServer
              ? `${deployServer.name} (${deployServer.ip})${deployServer.usable ? '' : ' — o Coolify ainda não validou o SSH até ele; confira o contêiner painkiller-coolify-host.'}`
              : 'Nenhum servidor cadastrado no Coolify.'}
        />
      </ul>
    {/if}
  </section>

  <section class="block">
    <button type="button" class="disclose" aria-expanded={manual} onclick={() => (manual = !manual)}>
      <span class="mono">{manual ? '−' : '+'}</span> Prefiro fazer manualmente
    </button>
    {#if manual}
      <ol class="steps">
        <li>
          <span class="n mono">1</span>
          <div>
            Crie a conta de administrador. A primeira conta cadastrada vira root e fecha o cadastro.
            <a href={`${dash}/register`} target="_blank" rel="noopener noreferrer" class="ext">
              Abrir cadastro <Icon name="external" size={11} />
            </a>
          </div>
        </li>
        <li>
          <span class="n mono">2</span>
          <div>
            Em <strong>Settings → Advanced</strong>, ligue <strong>API Access</strong> e salve.
            <a href={`${dash}/settings/advanced`} target="_blank" rel="noopener noreferrer" class="ext">
              Abrir Settings <Icon name="external" size={11} />
            </a>
          </div>
        </li>
        <li>
          <span class="n mono">3</span>
          <div>
            Em <strong>Keys &amp; Tokens → API Tokens</strong>, crie um token com a permissão
            <strong>root</strong> e copie-o (ele só aparece uma vez).
            <a href={`${dash}/security/api-tokens`} target="_blank" rel="noopener noreferrer" class="ext">
              Abrir API Tokens <Icon name="external" size={11} />
            </a>
          </div>
        </li>
        <li>
          <span class="n mono">4</span>
          <div class="field grow">
            <label for="c-token">Token de API</label>
            <input
              id="c-token"
              type="password"
              class="input mono"
              bind:value={token}
              placeholder={coolify.has_token ? `Salvo (${coolify.masked_token}) — deixe em branco para manter` : '1|…'}
              autocomplete="off"
            />
          </div>
        </li>
      </ol>
    {/if}
  </section>

  <div class="grid">
    <div class="field">
      <label for="c-wildcard">Domínio dos ambientes</label>
      <input id="c-wildcard" class="input mono" bind:value={wildcard} placeholder={coolify.suggested_wildcard_domain} />
      <p class="help">
        Cada ambiente vira <span class="mono">projeto-test.{wildcard || coolify.suggested_wildcard_domain}</span>.
        Um <span class="mono">IP.nip.io</span> funciona sem DNS.
      </p>
    </div>
    <div class="field">
      <label for="c-server">Servidor de deploy</label>
      {#if servers.length > 1}
        <select id="c-server" class="input mono" bind:value={serverUuid}>
          {#each servers as s (s.uuid)}
            <option value={s.uuid}>{s.name} ({s.ip})</option>
          {/each}
        </select>
      {:else}
        <input id="c-server" class="input mono" value={servers[0]?.name ?? (serverUuid || 'automático')} disabled />
        <p class="help">Com um servidor só, ele é escolhido sozinho.</p>
      {/if}
    </div>
  </div>

  {#if mode === 'settings'}
    <div class="field">
      <label for="c-dash">Endereço do painel do Coolify</label>
      <input id="c-dash" class="input mono" bind:value={dashboardUrl} />
      <p class="help">Usado só nos links desta tela. Padrão: o host do Painkiller na porta COOLIFY_PORT.</p>
    </div>
    {#if coolify.root_email}
      <div class="creds">
        {#if revealed}
          <CopyValue label="E-mail root do Coolify" value={revealed.email} />
          {#if revealed.password}<CopyValue label="Senha" value={revealed.password} />{/if}
        {:else}
          <button type="button" class="btn btn-line btn-sm" onclick={reveal}>Ver credenciais do Coolify</button>
        {/if}
      </div>
    {/if}
  {/if}

  {#if error}<p class="field-error" role="alert">{error}</p>{/if}

  <div class="actions">
    {#if saved && mode === 'settings'}<span class="help">Salvo.</span>{/if}
    <a href={dash} target="_blank" rel="noopener noreferrer" class="btn btn-quiet">
      Abrir o Coolify <Icon name="external" size={11} />
    </a>
    {#if mode === 'wizard' && !ready}
      <button type="button" class="btn btn-quiet" onclick={skip} disabled={busy}>Pular — configuro depois</button>
    {/if}
    <button type="submit" class="btn btn-solid" disabled={busy || (!ready && !token.trim())}>
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

  .block {
    display: flex;
    flex-direction: column;
    gap: var(--s3);
  }

  .block-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }

  .checks {
    border-bottom: 1px solid var(--rule);
  }

  .once {
    display: flex;
    flex-direction: column;
    gap: var(--s3);
    padding: var(--s4);
    border: 1px solid var(--rule-ink);
  }

  .open {
    align-self: flex-start;
  }

  /* A ação principal da etapa: filete de tinta, primeira coisa da tela. */
  .auto {
    display: flex;
    flex-direction: column;
    gap: var(--s3);
    padding: var(--s5);
    border: 1px solid var(--rule-ink);
    border-left-width: 3px;
  }

  .auto-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--s3);
  }

  .auto-btn {
    padding: 0.625rem 1.125rem;
  }

  .auto-row {
    display: flex;
    align-items: flex-end;
    gap: var(--s3);
    flex-wrap: wrap;
  }

  .grow {
    flex: 1;
    min-width: 14rem;
  }

  .disclose {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    align-self: flex-start;
    padding: 0;
    border: 0;
    background: none;
    font-size: var(--t-small);
    font-weight: 500;
    color: var(--ink);
    cursor: pointer;
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

  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--s4);
  }

  .creds {
    display: flex;
    flex-direction: column;
    gap: var(--s2);
    align-items: flex-start;
  }

  .creds :global(.copy) {
    width: 100%;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: var(--s3);
    padding-top: var(--s4);
    border-top: 1px solid var(--rule);
    flex-wrap: wrap;
  }

  @media (max-width: 640px) {
    .grid {
      grid-template-columns: 1fr;
    }
  }
</style>
