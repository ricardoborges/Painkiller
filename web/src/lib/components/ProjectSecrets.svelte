<script lang="ts">
  import { t, formatDate } from '$lib/i18n/index.svelte';
  import { api } from '$lib/api';
  import type { ProjectSecret, SecretScope } from '$lib/types';
  import Skeleton from '$lib/components/Skeleton.svelte';

  let { projectId }: { projectId: string } = $props();

  let secrets = $state<ProjectSecret[] | null>(null);
  let name = $state('');
  let value = $state('');
  let saving = $state(false);
  let removing = $state<string | null>(null);
  let error = $state<string | null>(null);
  let valueInput = $state<HTMLInputElement | null>(null);

  // O prefixo decide, como no backend: VITE_ entra no build do app; o resto, só no backend.
  const cleanName = $derived(name.trim().toUpperCase());
  const scope = $derived<SecretScope>(cleanName.startsWith('VITE_') ? 'app' : 'server');
  const replacing = $derived(!!secrets?.some((s) => s.name === cleanName));

  $effect(() => {
    const id = projectId;
    api
      .listSecrets(id)
      .then((list) => {
        if (projectId === id) secrets = list;
      })
      .catch((e) => {
        secrets = [];
        error = e instanceof Error ? e.message : String(e);
      });
  });

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!cleanName || !value.trim()) return;
    saving = true;
    error = null;
    try {
      const saved = await api.putSecret(projectId, cleanName, scope, value);
      secrets = [...(secrets ?? []).filter((s) => s.name !== saved.name), saved].sort((a, b) =>
        a.name.localeCompare(b.name)
      );
      name = '';
      value = '';
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      saving = false;
    }
  }

  function replace(secret: ProjectSecret) {
    name = secret.name;
    value = '';
    valueInput?.focus();
  }

  async function remove(secret: ProjectSecret) {
    if (!confirm(t('secrets.confirmDelete', { name: secret.name }))) return;
    removing = secret.name;
    error = null;
    try {
      await api.deleteSecret(projectId, secret.name);
      secrets = (secrets ?? []).filter((s) => s.name !== secret.name);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      removing = null;
    }
  }
</script>

<section class="secrets">
  <h2 class="label">{t('secrets.title')}</h2>
  <p class="help">{t('secrets.help')}</p>

  {#if secrets === null}
    <Skeleton rows={2} />
  {:else if secrets.length}
    <ul class="list divide">
      {#each secrets as s (s.name)}
        <li class="row">
          <span class="mono name truncate" title={s.name}>{s.name}</span>
          <span class="label scope">{s.scope === 'app' ? t('secrets.scopeApp') : t('secrets.scopeServer')}</span>
          <span class="mono faint when">{formatDate(s.updated_at, { dateStyle: 'short', timeStyle: 'short' })}</span>
          <span class="acts">
            <button type="button" class="btn btn-line btn-sm" onclick={() => replace(s)}>
              {t('secrets.replace')}
            </button>
            <button
              type="button"
              class="btn btn-line btn-sm"
              onclick={() => remove(s)}
              disabled={removing === s.name}
            >
              {t('secrets.delete')}
            </button>
          </span>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="faint empty">{t('secrets.empty')}</p>
  {/if}

  <form class="add" onsubmit={save}>
    <div class="field">
      <label for="secret-name">{t('secrets.name')}</label>
      <input
        id="secret-name"
        class="input mono"
        bind:value={name}
        placeholder="OPENAI_API_KEY"
        autocomplete="off"
        spellcheck="false"
      />
    </div>
    <div class="field">
      <label for="secret-value">{t('secrets.value')}</label>
      <input
        id="secret-value"
        class="input mono"
        type="password"
        bind:value
        bind:this={valueInput}
        autocomplete="new-password"
        spellcheck="false"
      />
    </div>
    <button type="submit" class="btn btn-sm" disabled={saving || !cleanName || !value.trim()}>
      {replacing ? t('secrets.saveReplace') : t('secrets.save')}
    </button>
  </form>
  {#if cleanName}
    <p class="help" class:hatch={scope === 'app'}>
      {scope === 'app' ? t('secrets.appWarning') : t('secrets.serverNote')}
    </p>
  {/if}
  {#if error}
    <p class="field-error" role="alert">{error}</p>
  {/if}
</section>

<style>
  .secrets {
    margin-top: var(--s7);
    padding-top: var(--s5);
    border-top: 1px solid var(--rule);
  }

  .list {
    margin: var(--s4) 0;
  }

  .row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto auto;
    align-items: center;
    gap: var(--s4);
    padding: var(--s2) 0;
  }

  .acts {
    display: flex;
    gap: var(--s2);
  }

  .empty {
    margin: var(--s4) 0;
  }

  .add {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
    align-items: end;
    gap: var(--s4);
  }

  .add .field {
    margin: 0;
  }

  .hatch {
    padding: var(--s2) var(--s3);
  }

  @media (max-width: 720px) {
    .row,
    .add {
      grid-template-columns: 1fr;
    }
  }
</style>
