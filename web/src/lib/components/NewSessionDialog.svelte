<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import Modal from './Modal.svelte';

  /**
   * Escolha do tipo da próxima sessão. Só aparece da segunda em diante: a
   * primeira monta a base do projeto e é sempre guiada.
   */
  let {
    open = $bindable(false),
    creating = false,
    oncreate
  }: {
    open?: boolean;
    creating?: boolean;
    oncreate: (guided: boolean) => void;
  } = $props();

  let guided = $state(true);

  // Cada abertura começa pela opção recomendada.
  $effect(() => {
    if (open) guided = true;
  });
</script>

<Modal bind:open title={t('newSession.title')} width="34rem">
  {#snippet body()}
    <div class="choices" role="radiogroup" aria-label={t('newSession.title')}>
      <label class="choice" class:active={guided}>
        <input type="radio" name="session-mode" value={true} bind:group={guided} />
        <span class="info">
          <span class="name">{t('newSession.guided')}</span>
          <span class="desc">{t('newSession.guidedDesc')}</span>
        </span>
      </label>
      <label class="choice" class:active={!guided}>
        <input type="radio" name="session-mode" value={false} bind:group={guided} />
        <span class="info">
          <span class="name">{t('newSession.direct')}</span>
          <span class="desc">{t('newSession.directDesc')}</span>
        </span>
      </label>
    </div>
    <p class="faint note">{t('newSession.note')}</p>
  {/snippet}
  {#snippet footer()}
    <button type="button" class="btn btn-line btn-sm" onclick={() => (open = false)}>
      {t('common.cancel')}
    </button>
    <button type="button" class="btn btn-solid btn-sm" disabled={creating} onclick={() => oncreate(guided)}>
      {creating ? t('sessionPicker.creating') : t('newSession.create')}
    </button>
  {/snippet}
</Modal>

<style>
  .choices {
    display: flex;
    flex-direction: column;
    padding: var(--s4) var(--s5) 0;
  }

  .choice {
    display: flex;
    gap: var(--s3);
    align-items: flex-start;
    padding: var(--s3) var(--s4);
    border: 1px solid var(--rule);
    cursor: pointer;
    transition: border-color var(--fast) var(--ease);
  }

  .choice + .choice {
    margin-top: -1px;
  }

  .choice:hover {
    border-color: var(--rule-2);
  }

  /* Selecionada: borda de tinta, nunca o acento. */
  .choice.active {
    position: relative;
    border-color: var(--ink);
  }

  input {
    margin-top: 0.2rem;
    accent-color: var(--ink);
  }

  .info {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }

  .name {
    color: var(--ink);
    font-weight: 600;
  }

  .desc {
    color: var(--ink-3);
    font-size: var(--t-small);
  }

  .note {
    padding: var(--s3) var(--s5) var(--s4);
    font-size: var(--t-micro);
  }
</style>
