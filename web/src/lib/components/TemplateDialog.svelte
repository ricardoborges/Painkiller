<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import { api, authedUrl } from '$lib/api';
  import {
    PROJECT_TYPES,
    PROJECT_TYPE_META,
    type ProjectTemplate,
    type ProjectType
  } from '$lib/types';
  import Modal from './Modal.svelte';
  import Icon from './Icon.svelte';

  let {
    open = $bindable(false),
    template = null,
    onsaved
  }: {
    open?: boolean;
    template?: ProjectTemplate | null;
    onsaved: (t: ProjectTemplate) => void;
  } = $props();

  let name = $state('');
  let description = $state('');
  let projectType = $state<ProjectType>('web_fullstack');
  let coolifyCompatible = $state(true);
  let prompt = $state('');
  let isActive = $state(true);

  // Arquivos novos a enviar
  let skillFile = $state<File | null>(null);
  let scaffoldFile = $state<File | null>(null);

  // Remoção de arquivos existentes no modo de edição
  let removeSkill = $state(false);
  let removeScaffold = $state(false);

  let busy = $state(false);
  let error = $state<string | null>(null);
  let touched = $state(false);

  const editing = $derived(template !== null);

  // Atualiza compatibilidade padrão com Coolify se o usuário trocar o tipo (a menos que tenha editado explicitamente)
  let lastType = $state<ProjectType>('web_fullstack');

  $effect(() => {
    if (!open) return;
    if (template) {
      name = template.name;
      description = template.description || '';
      projectType = template.project_type;
      coolifyCompatible = template.coolify_compatible;
      prompt = template.prompt || '';
      isActive = template.is_active;
      lastType = template.project_type;
    } else {
      name = '';
      description = '';
      projectType = 'web_fullstack';
      coolifyCompatible = PROJECT_TYPE_META['web_fullstack'].coolifyDefault;
      prompt = '';
      isActive = true;
      lastType = 'web_fullstack';
    }
    skillFile = null;
    scaffoldFile = null;
    removeSkill = false;
    removeScaffold = false;
    error = null;
    touched = false;
    busy = false;
  });

  function onTypeChange(newType: ProjectType) {
    projectType = newType;
    // Se o tipo mudou, atualiza a sugestão de compatibilidade com o Coolify
    coolifyCompatible = PROJECT_TYPE_META[newType].coolifyDefault;
  }

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
      let saved: ProjectTemplate;

      if (editing && template) {
        saved = await api.updateAdminTemplate(template.id, {
          name: name.trim(),
          description: description.trim(),
          project_type: projectType,
          coolify_compatible: coolifyCompatible,
          prompt: prompt.trim(),
          is_active: isActive
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
      } else {
        saved = await api.createAdminTemplate({
          name: name.trim(),
          description: description.trim(),
          project_type: projectType,
          coolify_compatible: coolifyCompatible,
          prompt: prompt.trim(),
          is_active: isActive
        });

        if (skillFile) {
          saved = await api.uploadTemplateSkill(saved.id, skillFile);
        }
        if (scaffoldFile) {
          saved = await api.uploadTemplateScaffold(saved.id, scaffoldFile);
        }
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

<Modal bind:open title={editing ? t('templateDialog.editTitle') : t('templateDialog.newTitle')} width="50rem">
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

      <!-- Tipo de Projeto -->
      <div class="field">
        <label for="tpl-type" class="label">{t('templateDialog.type')}</label>
        <select
          id="tpl-type"
          class="input"
          value={projectType}
          onchange={(e) => onTypeChange(e.currentTarget.value as ProjectType)}
        >
          {#each PROJECT_TYPES as type (type)}
            <option value={type}>
              {PROJECT_TYPE_META[type].label}
              ({PROJECT_TYPE_META[type].coolifyDefault ? t('form.coolifyCompatible') : t('templateDialog.noCoolifyDeploy')})
            </option>
          {/each}
        </select>
        <span class="help">
          {PROJECT_TYPE_META[projectType].description}
        </span>
      </div>

      <!-- Compatibilidade com Coolify -->
      <div class="field coolify-box" class:is-coolify={coolifyCompatible}>
        <label class="check-label">
          <input type="checkbox" bind:checked={coolifyCompatible} />
          <span class="check-text">
            <strong>{t('templateDialog.coolifyCompatible')}</strong>
            <span class="help">
              {#if coolifyCompatible}
                {t('templateDialog.coolifyOn')}
              {:else}
                {t('templateDialog.coolifyOff')}
              {/if}
            </span>
          </span>
        </label>
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

          {#if template?.skill_filename && !removeSkill && !skillFile}
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

          {#if template?.scaffold_filename && !removeScaffold && !scaffoldFile}
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

      <!-- Ativo / Inativo -->
      <div class="field">
        <label class="check-label">
          <input type="checkbox" bind:checked={isActive} />
          <span class="check-text">
            <strong>{t('templateDialog.active')}</strong>
            <span class="help">{t('templateDialog.activeHelp')}</span>
          </span>
        </label>
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
        {#if busy}
          {t('common.saving')}
        {:else if editing}
          {t('form.saveChanges')}
        {:else}
          {t('templateDialog.create')}
        {/if}
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

  .coolify-box {
    padding: var(--s3);
    border: 1px solid var(--rule-2);
    background: var(--paper-sunk);
  }

  .coolify-box.is-coolify {
    border-color: var(--ink-3);
  }

  .check-label {
    display: flex;
    align-items: flex-start;
    gap: var(--s3);
    cursor: pointer;
  }

  .check-label input[type='checkbox'] {
    margin-top: 0.2rem;
    cursor: pointer;
  }

  .check-text {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    font-size: var(--t-small);
  }

  .file-field {
    padding: var(--s3);
    border: 1px dashed var(--rule-2);
    background: var(--paper-sunk);
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
