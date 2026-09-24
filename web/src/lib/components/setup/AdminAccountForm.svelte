<script lang="ts">
  import { api } from '$lib/api';
  import { auth } from '$lib/stores/auth.svelte';
  import { setup } from '$lib/stores/setup.svelte';

  const MIN_PASSWORD = 12;

  let username = $state('');
  let currentPassword = $state('');
  let newPassword = $state('');
  let confirm = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);
  let saved = $state(false);

  let seeded = false;
  $effect(() => {
    if (seeded || !setup.state) return;
    seeded = true;
    username = setup.state.admin_username ?? auth.user?.username ?? '';
  });

  async function save(e: SubmitEvent) {
    e.preventDefault();
    error = null;
    saved = false;
    if (newPassword && newPassword.length < MIN_PASSWORD) {
      error = `A senha nova precisa de pelo menos ${MIN_PASSWORD} caracteres.`;
      return;
    }
    if (newPassword !== confirm) {
      error = 'A confirmação não confere com a senha nova.';
      return;
    }
    busy = true;
    try {
      // A senha nova invalida a sessão atual; a resposta traz a próxima.
      auth.adopt(
        await api.updateAdminAccount({
          current_password: currentPassword,
          username: username.trim(),
          new_password: newPassword
        })
      );
      await setup.reload();
      currentPassword = newPassword = confirm = '';
      saved = true;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Não foi possível salvar.';
    } finally {
      busy = false;
    }
  }
</script>

<form class="step" onsubmit={save}>
  <p class="lede small">
    A conta criada no primeiro acesso. Enxerga todos os projetos e é o acesso de emergência quando o login
    Google estiver fora. Esqueceu a senha? No servidor, rode <span class="mono">painkiller admin-reset</span> e
    reinicie a API: o primeiro acesso reabre.
  </p>

  <div class="grid">
    <div class="field">
      <label for="adm-user">Usuário</label>
      <input id="adm-user" class="input" bind:value={username} autocomplete="username" />
    </div>
    <div class="field">
      <label for="adm-current">Senha atual</label>
      <input
        id="adm-current"
        class="input"
        type="password"
        bind:value={currentPassword}
        autocomplete="current-password"
      />
    </div>
    <div class="field">
      <label for="adm-new">Senha nova</label>
      <input id="adm-new" class="input" type="password" bind:value={newPassword} autocomplete="new-password" />
      <p class="help">Vazio mantém a senha. Mínimo de {MIN_PASSWORD} caracteres.</p>
    </div>
    <div class="field">
      <label for="adm-confirm">Confirme a senha nova</label>
      <input id="adm-confirm" class="input" type="password" bind:value={confirm} autocomplete="new-password" />
    </div>
  </div>

  {#if error}<p class="field-error" role="alert">{error}</p>{/if}

  <div class="actions">
    {#if saved}<span class="help">Salvo. As outras sessões do administrador foram encerradas.</span>{/if}
    <button type="submit" class="btn btn-solid" disabled={busy || !currentPassword}>
      {busy ? 'Salvando…' : 'Salvar'}
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
