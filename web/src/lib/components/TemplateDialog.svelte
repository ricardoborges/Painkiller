<script lang="ts">
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
        error = 'O arquivo de skill deve ser .zip ou .md';
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
        error = 'O arquivo de arcabouço deve ser .zip';
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
      error = err instanceof Error ? err.message : 'Falha ao salvar template.';
    } finally {
      busy = false;
    }
  }
</script>

<Modal bind:open title={editing ? 'Editar template' : 'Novo template de projeto'} width="50rem">
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
          Nome do template <span class="req" aria-hidden="true">*</span>
        </label>
        <input
          id="tpl-name"
          type="text"
          class="input"
          class:invalid={touched && !name.trim()}
          placeholder="ex: FastAPI REST API, SvelteKit Fullstack, Android Nativo"
          bind:value={name}
          required
        />
        {#if touched && !name.trim()}
          <span class="error mono">Nome é obrigatório.</span>
        {/if}
      </div>

      <!-- Tipo de Projeto -->
      <div class="field">
        <label for="tpl-type" class="label">Tipo de aplicação</label>
        <select
          id="tpl-type"
          class="input"
          value={projectType}
          onchange={(e) => onTypeChange(e.currentTarget.value as ProjectType)}
        >
          {#each PROJECT_TYPES as t}
            <option value={t}>
              {PROJECT_TYPE_META[t].label}
              {PROJECT_TYPE_META[t].coolifyDefault ? '(Compatível com Coolify)' : '(Sem deploy Coolify)'}
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
            <strong>Compatível com deploy no Coolify</strong>
            <span class="help">
              {#if coolifyCompatible}
                Aplicações Web e APIs são publicadas em contêineres e expostas via URL de teste / produção no Coolify.
              {:else}
                Aplicações Desktop, Mobile ou Android nativo não geram deploys automáticos no servidor Coolify.
              {/if}
            </span>
          </span>
        </label>
      </div>

      <!-- Descrição -->
      <div class="field">
        <label for="tpl-desc" class="label">Descrição do template</label>
        <input
          id="tpl-desc"
          type="text"
          class="input"
          placeholder="Breve resumo da pilha e arquitetura proposta"
          bind:value={description}
        />
      </div>

      <!-- Prompt do Harness -->
      <div class="field">
        <label for="tpl-prompt" class="label">
          Prompt de orientação arquitetural / instruções para o harness
        </label>
        <textarea
          id="tpl-prompt"
          class="textarea mono-text"
          rows="5"
          placeholder="Exemplo: Utilize Clean Architecture com Fastify e Prisma. Estruture as rotas em /src/routes e entidades em /src/domain. Não utilize bibliotecas deprecadas..."
          bind:value={prompt}
        ></textarea>
        <span class="help">
          Instruções injetadas no contexto do agente para guiar a análise inicial e a criação do código.
        </span>
      </div>

      <div class="two-col">
        <!-- Anexo da Skill -->
        <div class="field file-field">
          <span class="label">Skill do agente (opcional)</span>
          <span class="help">Instruções ou skill especializada em arquivo <code>.md</code> ou <code>.zip</code>.</span>

          {#if template?.skill_filename && !removeSkill && !skillFile}
            <div class="current-file">
              <span class="mono truncate">{template.skill_filename}</span>
              <div class="file-acts">
                <a
                  href={authedUrl(`/admin/templates/${template.id}/skill/download`)}
                  class="btn-quiet btn-sm"
                  title="Baixar skill"
                  download
                >
                  <Icon name="download" size={12} />
                </a>
                <button
                  type="button"
                  class="btn-quiet btn-sm"
                  title="Remover skill"
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
                <span>{skillFile ? skillFile.name : 'Selecionar .md ou .zip'}</span>
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
                  title="Limpar seleção"
                  onclick={() => (skillFile = null)}
                >
                  <Icon name="close" size={12} />
                </button>
              {/if}
            </div>
            {#if removeSkill}
              <span class="faint mono hint-removed">O arquivo anterior será excluído ao salvar.</span>
            {/if}
          {/if}
        </div>

        <!-- Anexo do Arcabouço (Scaffold) -->
        <div class="field file-field">
          <span class="label">Arcabouço da aplicação (opcional)</span>
          <span class="help">Estrutura inicial do projeto compactada em arquivo <code>.zip</code>.</span>

          {#if template?.scaffold_filename && !removeScaffold && !scaffoldFile}
            <div class="current-file">
              <span class="mono truncate">{template.scaffold_filename}</span>
              <div class="file-acts">
                <a
                  href={authedUrl(`/admin/templates/${template.id}/scaffold/download`)}
                  class="btn-quiet btn-sm"
                  title="Baixar arcabouço"
                  download
                >
                  <Icon name="download" size={12} />
                </a>
                <button
                  type="button"
                  class="btn-quiet btn-sm"
                  title="Remover arcabouço"
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
                <span>{scaffoldFile ? scaffoldFile.name : 'Selecionar .zip'}</span>
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
                  title="Limpar seleção"
                  onclick={() => (scaffoldFile = null)}
                >
                  <Icon name="close" size={12} />
                </button>
              {/if}
            </div>
            {#if removeScaffold}
              <span class="faint mono hint-removed">O arquivo anterior será excluído ao salvar.</span>
            {/if}
          {/if}
        </div>
      </div>

      <!-- Ativo / Inativo -->
      <div class="field">
        <label class="check-label">
          <input type="checkbox" bind:checked={isActive} />
          <span class="check-text">
            <strong>Template ativo</strong>
            <span class="help">Disponível para seleção ao criar novos projetos.</span>
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
        Cancelar
      </button>
      <button
        type="submit"
        form="template-form"
        class="btn btn-solid btn-sm"
        disabled={busy}
      >
        {#if busy}
          Salvando…
        {:else if editing}
          Salvar alterações
        {:else}
          Criar template
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
    overflow-y: auto;
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
