<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import { api, authedUrl } from '$lib/api';
  import type { ProjectTemplate } from '$lib/types';
  import Modal from './Modal.svelte';
  import Icon from './Icon.svelte';

  // Edita o único template (app Android nativo): não há criação nem tipo a escolher.
  let {
    open = $bindable(false),
    template,
    onsaved
  }: {
    open?: boolean;
    template: ProjectTemplate;
    onsaved: (t: ProjectTemplate) => void;
  } = $props();

  let name = $state('');
  let description = $state('');
  let prompt = $state('');

  // Arquivos novos a enviar
  let skillFile = $state<File | null>(null);
  let scaffoldFile = $state<File | null>(null);

  // Remoção de arquivos existentes
  let removeSkill = $state(false);
  let removeScaffold = $state(false);

  let busy = $state(false);
  let error = $state<string | null>(null);
  let touched = $state(false);

  $effect(() => {
    if (!open) return;
    name = template.name;
    description = template.description || '';
    prompt = template.prompt || '';
    skillFile = null;
    scaffoldFile = null;
    removeSkill = false;
    removeScaffold = false;
    error = null;
    touched = false;
    busy = false;
  });

  function handleSkillSelect(e: Event) {
    const input = e.target as HTMLInputElement;
    if (input.files && input.files[0]) {
      const file = input.files[0];
      const ext = file.name.toLowerCase().slice(file.name.lastIndexOf('.'));
      if (ext !== '.zip' && ext !== '.md') {
        error = t('templateDialog.skillExt');
        return;
      }
      skillFile = file;
      removeSkill = false;
      error = null;
    }
  }

  function handleScaffoldSelect(e: Event) {
    const input = e.target as HTMLInputElement;
    if (input.files && input.files[0]) {
      const file = input.files[0];
      const ext = file.name.toLowerCase().slice(file.name.lastIndexOf('.'));
      if (ext !== '.zip') {
        error = t('templateDialog.scaffoldExt');
        return;
      }
      scaffoldFile = file;
      removeScaffold = false;
      error = null;
    }
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    touched = true;
    if (!name.trim()) return;

    busy = true;
    error = null;

    try {
      let saved = await api.updateAdminTemplate(template.id, {
        name: name.trim(),
        description: description.trim(),
        prompt: prompt.trim()
      });

      if (removeSkill && template.skill_path) {
        saved = await api.deleteTemplateSkill(template.id);
      }
      if (skillFile) {
        saved = await api.uploadTemplateSkill(template.id, skillFile);
      }

      if (removeScaffold && template.scaffold_path) {
        saved = await api.deleteTemplateScaffold(template.id);
      }
      if (scaffoldFile) {
        saved = await api.uploadTemplateScaffold(template.id, scaffoldFile);
      }

      open = false;
      onsaved(saved);
    } catch (err) {
      error = err instanceof Error ? err.message : t('templateDialog.saveFailed');
    } finally {
      busy = false;
    }
  }
</script>

<Modal bind:open title={t('templateDialog.editTitle')} width="50rem">
  {#snippet body()}
    <form id="template-form" onsubmit={submit}>
      {#if error}
        <div class="banner error-banner mono" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
        </div>
      {/if}

      <!-- Nome -->
      <div class="field">
        <label for="tpl-name" class="label">
          {t('templateDialog.name')} <span class="req" aria-hidden="true">*</span>
        </label>
        <input
          id="tpl-name"
          type="text"
          class="input"
          class:invalid={touched && !name.trim()}
          placeholder={t('templateDialog.namePlaceholder')}
          bind:value={name}
          required
        />
        {#if touched && !name.trim()}
          <span class="error mono">{t('templateDialog.nameRequired')}</span>
        {/if}
      </div>

      <!-- Descrição -->
      <div class="field">
        <label for="tpl-desc" class="label">{t('templateDialog.description')}</label>
        <input
          id="tpl-desc"
          type="text"
          class="input"
          placeholder={t('templateDialog.descriptionPlaceholder')}
          bind:value={description}
        />
      </div>

      <!-- Prompt do Harness -->
      <div class="field">
        <label for="tpl-prompt" class="label">
          {t('templateDialog.prompt')}
        </label>
        <textarea
          id="tpl-prompt"
          class="textarea mono-text"
          rows="5"
          placeholder={t('templateDialog.promptPlaceholder')}
          bind:value={prompt}
        ></textarea>
        <span class="help">
          {t('templateDialog.promptHelp')}
        </span>
      </div>

      <div class="two-col">
        <!-- Anexo da Skill -->
        <div class="field file-field">
          <span class="label">{t('templateDialog.skill')}</span>
          <span class="help">{@html t('templateDialog.skillHelp')}</span>

          {#if template.skill_filename && !removeSkill && !skillFile}
            <div class="current-file">
              <span class="mono truncate">{template.skill_filename}</span>
              <div class="file-acts">
                <a
                  href={authedUrl(`/admin/templates/${template.id}/skill/download`)}
                  class="btn-quiet btn-sm"
                  title={t('templateDialog.downloadSkill')}
                  download
                >
                  <Icon name="download" size={12} />
                </a>
                <button
                  type="button"
                  class="btn-quiet btn-sm"
                  title={t('templateDialog.removeSkill')}
                  onclick={() => (removeSkill = true)}
                >
                  <Icon name="trash" size={12} />
                </button>
              </div>
            </div>
          {:else}
            <div class="file-upload-row">
              <label class="btn btn-line btn-sm file-btn">
                <Icon name="clip" size={12} />
                <span>{skillFile ? skillFile.name : t('templateDialog.pickSkill')}</span>
                <input
                  type="file"
                  accept=".zip,.md"
                  onchange={handleSkillSelect}
                  class="sr-input"
                />
              </label>
              {#if skillFile}
                <button
                  type="button"
                  class="btn-quiet btn-sm"
                  title={t('templateDialog.clear')}
                  onclick={() => (skillFile = null)}
                >
                  <Icon name="close" size={12} />
                </button>
              {/if}
            </div>
            {#if removeSkill}
              <span class="faint mono hint-removed">{t('templateDialog.willRemove')}</span>
            {/if}
          {/if}
        </div>

        <!-- Anexo do Arcabouço (Scaffold) -->
        <div class="field file-field">
          <span class="label">{t('templateDialog.scaffold')}</span>
          <span class="help">{@html t('templateDialog.scaffoldHelp')}</span>

          {#if !scaffoldFile && (template.bundled_scaffold || removeScaffold)}
            <!-- Sem .zip próprio vale o embutido; baixá-lo é o ponto de partida para adaptar. -->
            <div class="current-file bundled">
              <span class="mono truncate">{t('templateDialog.bundledScaffold')}</span>
              <div class="file-acts">
                <a
                  href={authedUrl(`/admin/templates/${template.id}/scaffold/download`)}
                  class="btn-quiet btn-sm"
                  title={t('templateDialog.downloadBundledScaffold')}
                  download
                >
                  <Icon name="download" size={12} />
                </a>
              </div>
            </div>
          {/if}
          {#if template.scaffold_filename && !template.bundled_scaffold && !removeScaffold && !scaffoldFile}
            <div class="current-file">
              <span class="mono truncate">{template.scaffold_filename}</span>
              <div class="file-acts">
                <a
                  href={authedUrl(`/admin/templates/${template.id}/scaffold/download`)}
                  class="btn-quiet btn-sm"
                  title={t('templateDialog.downloadScaffold')}
                  download
                >
                  <Icon name="download" size={12} />
                </a>
                <button
                  type="button"
                  class="btn-quiet btn-sm"
                  title={t('templateDialog.removeScaffold')}
                  onclick={() => (removeScaffold = true)}
                >
                  <Icon name="trash" size={12} />
                </button>
              </div>
            </div>
          {:else}
            <div class="file-upload-row">
              <label class="btn btn-line btn-sm file-btn">
                <Icon name="clip" size={12} />
                <span>{scaffoldFile ? scaffoldFile.name : t('templateDialog.pickScaffold')}</span>
                <input
                  type="file"
                  accept=".zip"
                  onchange={handleScaffoldSelect}
                  class="sr-input"
                />
              </label>
              {#if scaffoldFile}
                <button
                  type="button"
                  class="btn-quiet btn-sm"
                  title={t('templateDialog.clear')}
                  onclick={() => (scaffoldFile = null)}
                >
                  <Icon name="close" size={12} />
                </button>
              {/if}
            </div>
            {#if removeScaffold}
              <span class="faint mono hint-removed">{t('templateDialog.willRemove')}</span>
            {/if}
          {/if}
        </div>
      </div>
    </form>
  {/snippet}

  {#snippet footer()}
    <div class="dialog-foot">
      <button
        type="button"
        class="btn btn-line btn-sm"
        disabled={busy}
        onclick={() => (open = false)}
      >
        {t('common.cancel')}
      </button>
      <button
        type="submit"
        form="template-form"
        class="btn btn-solid btn-sm"
        disabled={busy}
      >
        {busy ? t('common.saving') : t('form.saveChanges')}
      </button>
    </div>
  {/snippet}
</Modal>

<style>
  form {
    display: flex;
    flex-direction: column;
    gap: var(--s5);
    padding: var(--s5);
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--s2);
  }

  .two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--s4);
  }

  .req {
    color: var(--accent);
  }

  .error {
    color: var(--accent);
    font-size: var(--t-micro);
  }

  .banner {
    display: flex;
    align-items: center;
    gap: var(--s2);
    padding: var(--s3);
    font-size: var(--t-small);
  }

  .error-banner {
    background: var(--paper-sunk);
    border: 1px solid var(--accent);
    color: var(--ink);
  }

  .file-field {
    padding: var(--s3);
    border: 1px dashed var(--rule-2);
    background: var(--paper-sunk);
  }

  .current-file.bundled {
    border-style: dashed;
    color: var(--ink-2);
  }

  .current-file {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s2);
    padding: var(--s2) var(--s3);
    border: 1px solid var(--rule-2);
    background: var(--paper);
    font-size: var(--t-micro);
  }

  .file-acts {
    display: flex;
    align-items: center;
    gap: var(--s1);
  }

  .file-upload-row {
    display: flex;
    align-items: center;
    gap: var(--s2);
  }

  .file-btn {
    position: relative;
    cursor: pointer;
    overflow: hidden;
  }

  .sr-input {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }

  .hint-removed {
    font-size: var(--t-micro);
    color: var(--ink-3);
  }

  .mono-text {
    font-family: var(--font-mono);
    font-size: var(--t-small);
    line-height: 1.45;
  }

  .dialog-foot {
    display: flex;
    justify-content: flex-end;
    gap: var(--s3);
    width: 100%;
  }

  @media (max-width: 640px) {
    .two-col {
      grid-template-columns: 1fr;
    }
  }
</style>
