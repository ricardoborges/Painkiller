<script lang="ts">
  import { t, i18n, LOCALES, type Locale } from '$lib/i18n/index.svelte';
  import { api, baseName } from '$lib/api';
  import {
    DEEPSEEK_KEY_HARNESSES,
    EFFORT_HARNESSES,
    EFFORT_LEVELS,
    DEFAULT_TEMPLATE_ID,
    type EffortLevel,
    PROJECT_TYPE_META,
    type HarnessType,
    type Project,
    type ProjectTemplate
  } from '$lib/types';
  import Icon from './Icon.svelte';

  let {
    project = null,
    onsaved,
    oncancel
  }: {
    /** null = criar; caso contrário, editar */
    project?: Project | null;
    onsaved: (p: Project) => void;
    oncancel: () => void;
  } = $props();

  let name = $state('');
  let description = $state('');
  let purpose = $state('');
  let solution = $state('');
  /** Opcional, para usuários avançados: stack, padrões, regras de negócio. */
  let notes = $state('');
  let harness = $state<HarnessType>('agy_superpowers');
  /** dsh e maki usam a mesma chave DeepSeek: trocar entre eles a preserva. */
  const usesDeepseekKey = $derived(DEEPSEEK_KEY_HARNESSES.includes(harness));
  let apiKey = $state('');
  let files = $state<File[]>([]);
  let dragging = $state(false);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let touched = $state(false);
  let fileInput = $state<HTMLInputElement | null>(null);

  const editing = $derived(project !== null);
  const existing = $derived(project?.attachments ?? []);

  const MODEL_PRESETS: Record<HarnessType, { id: string; label: string }[]> = $derived({
    maki_superpowers: [
      { id: 'deepseek/deepseek-v4-pro', label: `deepseek/deepseek-v4-pro (${t('form.defaultRecommended')})` },
      { id: 'deepseek/deepseek-v4-flash', label: 'deepseek/deepseek-v4-flash' },
      { id: 'deepseek/deepseek-flash', label: 'deepseek/deepseek-flash' }
    ],
    agy_superpowers: [
      { id: 'gemini-3.8-flash', label: `gemini-3.8-flash (${t('form.default')})` },
      { id: 'gemini-3.8-pro', label: 'gemini-3.8-pro' },
      { id: 'gemini-2.5-flash', label: 'gemini-2.5-flash' },
      { id: 'gemini-2.5-pro', label: 'gemini-2.5-pro' }
    ],
    // `deepseek-flash` é o DeepSeek-V4.1-Flash; o catálogo do dsh não anuncia
    // `deepseek-v4-flash`, então ele cairia no padrão do próprio dsh.
    deepseek_superpowers: [
      { id: 'deepseek-flash', label: `deepseek-flash · V4.1-Flash (${t('form.default')})` },
      { id: 'deepseek-v4-pro', label: 'deepseek-v4-pro' }
    ],
    // A Responses API da DeepSeek recebe o id sem o prefixo `provider/` do maki.
    unreal_superpowers: [
      { id: 'deepseek-flash', label: `deepseek-flash · V4.1-Flash (${t('form.default')})` },
      { id: 'deepseek-v4-pro', label: 'deepseek-v4-pro' }
    ]
  });

  function defaultModelFor(h: HarnessType): string {
    return MODEL_PRESETS[h]?.[0]?.id ?? '';
  }

  let model = $state('');
  /** Idioma em que o agente conduz a análise e escreve specs, código e commits. */
  let language = $state<Locale>(i18n.current);
  let effort = $state<EffortLevel>('medium');
  const hasEffort = $derived(EFFORT_HARNESSES.includes(harness));
  let isCustomModel = $state(false);
  let customModelText = $state('');

  // Todo projeto nasce de um template ativo (hoje só o Capacitor), escolhido
  // só na criação: depois o repositório já tem a estrutura dele.
  let templates = $state<ProjectTemplate[]>([]);
  let templateId = $state(DEFAULT_TEMPLATE_ID);
  const template = $derived(templates.find((tpl) => tpl.id === templateId) ?? null);

  async function loadTemplates() {
    try {
      templates = await api.listActiveTemplates();
    } catch {
      templates = [];
    }
  }

  const effectiveSolution = $derived(solution.trim());

  // Repopula ao montar e sempre que o projeto editado muda
  $effect(() => {
    loadTemplates();
    templateId = project?.template_id ?? DEFAULT_TEMPLATE_ID;
    name = project?.name ?? '';
    description = project?.description ?? '';
    purpose = project?.purpose ?? '';
    solution = project?.solution_description ?? '';
    notes = project?.implementation_notes ?? '';
    // Variável local: ler `harness` aqui o tornaria dependência do efeito,
    // que então desfaria toda troca de harness feita pelo usuário.
    const initialHarness: HarnessType = project?.harness ?? 'agy_superpowers';
    harness = initialHarness;
    previousHarness = initialHarness;
    const currentModel = project?.model || defaultModelFor(initialHarness);
    const presets = MODEL_PRESETS[initialHarness] || [];
    if (presets.some((p) => p.id === currentModel)) {
      model = currentModel;
      isCustomModel = false;
      customModelText = '';
    } else {
      model = '__custom__';
      isCustomModel = true;
      customModelText = currentModel;
    }
    effort = project?.effort ?? 'medium';
    language = project?.language ?? i18n.current;
    apiKey = '';
    files = [];
    error = null;
    touched = false;
  });

  let previousHarness = $state<HarnessType>('agy_superpowers');
  $effect(() => {
    if (harness !== previousHarness) {
      previousHarness = harness;
      if (!isCustomModel) {
        model = defaultModelFor(harness);
      }
    }
  });

  function onModelSelect(val: string) {
    if (val === '__custom__') {
      isCustomModel = true;
      model = '__custom__';
    } else {
      isCustomModel = false;
      model = val;
    }
  }

  const effectiveModel = $derived(isCustomModel ? customModelText.trim() : model);

  /** A chave salva só serve se o provedor (Gemini ou DeepSeek) não mudou. */
  const savedKeyUsable = $derived(
    Boolean(
      project?.has_api_key &&
        DEEPSEEK_KEY_HARNESSES.includes(project.harness ?? 'agy_superpowers') === usesDeepseekKey
    )
  );

  const KEY_PAGES = {
    deepseek: { name: 'DeepSeek', url: 'https://platform.deepseek.com/api_keys' },
    gemini: { name: 'Google Gemini', url: 'https://aistudio.google.com/apikey' }
  } as const;
  const keyPage = $derived(usesDeepseekKey ? KEY_PAGES.deepseek : KEY_PAGES.gemini);

  const missing = $derived({
    name: !name.trim(),
    purpose: !purpose.trim(),
    solution: !effectiveSolution,
    apiKey: !apiKey.trim() && !savedKeyUsable
  });

  const invalid = $derived(missing.name || missing.purpose || missing.solution || missing.apiKey);

  function addFiles(list: FileList | null) {
    if (!list) return;
    const incoming = Array.from(list);
    const known = new Set(files.map((f) => `${f.name}:${f.size}`));
    files = [...files, ...incoming.filter((f) => !known.has(`${f.name}:${f.size}`))];
  }

  function removeFile(target: File) {
    files = files.filter((f) => f !== target);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    dragging = false;
    addFiles(e.dataTransfer?.files ?? null);
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    touched = true;
    if (invalid) return;

    busy = true;
    error = null;
    try {
      // Pergunta ao provedor antes de salvar; só uma recusa explícita bloqueia.
      if (apiKey.trim()) {
        const check = await api.validateProjectKey(harness, apiKey.trim());
        if (check.valid === false) {
          error = check.detail ?? t('form.keyRefused');
          return;
        }
      }
      const body: {
        name: string;
        description: string;
        purpose: string;
        solution_description: string;
        implementation_notes: string;
        harness: HarnessType;
        api_key?: string;
        model?: string;
        effort?: string;
        language: Locale;
        template_id?: string;
      } = {
        name: name.trim(),
        description: description.trim(),
        purpose: purpose.trim(),
        solution_description: effectiveSolution,
        implementation_notes: notes.trim(),
        harness: harness,
        model: effectiveModel || undefined,
        // Só agy e dsh têm o ajuste; para os demais o backend o descarta.
        effort: hasEffort ? effort : undefined,
        language
      };
      if (!editing) {
        body.template_id = templateId;
      }
      if (apiKey.trim()) {
        body.api_key = apiKey.trim();
      }

      // O arcabouço do template só entra na criação (o backend o aplica sozinho):
      // depois o repositório já é do agente.
      let saved = editing ? await api.updateProject(project!.id, body) : await api.createProject(body);

      for (const file of files) {
        const res = await api.uploadAttachment(saved.id, file);
        saved = res.project;
      }

      onsaved(saved);
    } catch (e) {
      error = e instanceof Error ? e.message : t('form.saveFailed');
    } finally {
      busy = false;
    }
  }
</script>

<form id="project-form" onsubmit={save} novalidate>
  <div class="field">
    <label for="pname">{t('form.name')} <span class="req">*</span></label>
    <input
      id="pname"
      class="input"
      bind:value={name}
      placeholder={t('form.namePlaceholder')}
      aria-invalid={touched && missing.name ? 'true' : undefined}
    />
    {#if touched && missing.name}<p class="field-error">{t('form.nameError')}</p>{/if}
  </div>

  <div class="field">
    <label for="pdesc">{t('form.description')}</label>
    <textarea
      id="pdesc"
      class="textarea"
      bind:value={description}
      placeholder={t('form.descriptionPlaceholder')}
    ></textarea>
  </div>

  <div class="field">
    <label for="ppurp">{t('projects.purpose')} <span class="req">*</span></label>
    <textarea
      id="ppurp"
      class="textarea"
      bind:value={purpose}
      placeholder={t('form.purposePlaceholder')}
      aria-invalid={touched && missing.purpose ? 'true' : undefined}
    ></textarea>
    {#if touched && missing.purpose}<p class="field-error">{t('form.purposeError')}</p>{/if}
  </div>

  {#if !editing && templates.length > 1}
    <div class="field">
      <label for="ptemplate-options">{t('form.platform')}</label>
      <p class="help">{t('form.platformHelp')}</p>
      <div id="ptemplate-options" class="harness-options">
        {#each templates as tpl (tpl.id)}
          <label class="radio-card" class:active={templateId === tpl.id}>
            <input type="radio" name="template" value={tpl.id} bind:group={templateId} />
            <div class="radio-info">
              <span class="radio-title">{PROJECT_TYPE_META[tpl.project_type]?.label || tpl.name}</span>
              <span class="radio-desc">{PROJECT_TYPE_META[tpl.project_type]?.description || tpl.description}</span>
            </div>
          </label>
        {/each}
      </div>
    </div>
  {/if}

  <div class="field">
    <label for="psol">
      {t('form.solution')} <span class="req">*</span>
    </label>
    <p class="help">
      {#if template}
        <span class="platform mono">
          {PROJECT_TYPE_META[template.project_type]?.label || template.name}{#if !editing}
            · {t('form.withScaffold')}{/if}
        </span>
      {/if}
      {t('form.solutionHelp')}
    </p>
    <textarea
      id="psol"
      class="textarea"
      bind:value={solution}
      placeholder={t('form.solutionPlaceholder')}
      aria-invalid={touched && missing.solution ? 'true' : undefined}
    ></textarea>
    {#if touched && missing.solution}
      <p class="field-error">{t('form.solutionError')}</p>
    {/if}
  </div>

  <div class="field">
    <label for="pnotes">
      {t('form.implementationNotes')} <span class="faint">({t('setup.optional')})</span>
    </label>
    <p class="help">{t('form.implementationNotesHelp')}</p>
    <textarea
      id="pnotes"
      class="textarea notes"
      bind:value={notes}
      placeholder={t('form.implementationNotesPlaceholder')}
    ></textarea>
  </div>

  <div class="field">
    <label for="pharness-options">{t('form.harness')}</label>
    <p class="help">{t('form.harnessHelp')}</p>
    <div id="pharness-options" class="harness-options">
      <label class="radio-card" class:active={harness === 'agy_superpowers'}>
        <input
          type="radio"
          name="harness"
          value="agy_superpowers"
          bind:group={harness}
        />
        <div class="radio-info">
          <span class="radio-title">Antigravity CLI (agy)</span>
          <span class="radio-desc">{t('form.harness.agy')}</span>
        </div>
      </label>
      <label class="radio-card" class:active={harness === 'deepseek_superpowers'}>
        <input
          type="radio"
          name="harness"
          value="deepseek_superpowers"
          bind:group={harness}
        />
        <div class="radio-info">
          <span class="radio-title">DeepSeek Harness (dsh)</span>
          <span class="radio-desc">{t('form.harness.dsh')}</span>
        </div>
      </label>
      <label class="radio-card" class:active={harness === 'maki_superpowers'}>
        <input
          type="radio"
          name="harness"
          value="maki_superpowers"
          bind:group={harness}
        />
        <div class="radio-info">
          <span class="radio-title">Maki</span>
          <span class="radio-desc">{t('form.harness.maki')}</span>
        </div>
      </label>
      <label class="radio-card" class:active={harness === 'unreal_superpowers'}>
        <input
          type="radio"
          name="harness"
          value="unreal_superpowers"
          bind:group={harness}
        />
        <div class="radio-info">
          <span class="radio-title">Unreal Agent</span>
          <span class="radio-desc">{t('form.harness.unreal')}</span>
        </div>
      </label>
    </div>
  </div>

  <div class="field">
    <label for="planguage">{t('form.language')}</label>
    <p class="help">{t('form.languageHelp')}</p>
    <select id="planguage" class="input select-input" bind:value={language}>
      {#each LOCALES as option (option.code)}
        <option value={option.code}>{option.label}</option>
      {/each}
    </select>
  </div>

  <div class="field">
    <label for="pmodel">{t('form.model')}</label>
    <p class="help">{@html t('form.modelHelp')}</p>
    <div class="model-select-wrap">
      <select
        id="pmodel"
        class="input mono select-input"
        value={isCustomModel ? '__custom__' : model}
        onchange={(e) => onModelSelect(e.currentTarget.value)}
      >
        {#each MODEL_PRESETS[harness] ?? [] as preset (preset.id)}
          <option value={preset.id}>
            {preset.label}
          </option>
        {/each}
        <option value="__custom__">{t('form.customModel')}</option>
      </select>
      {#if isCustomModel}
        <input
          type="text"
          class="input mono custom-model-input"
          placeholder={harness === 'maki_superpowers' ? 'deepseek/deepseek-v4-pro' : harness === 'unreal_superpowers' ? 'deepseek-flash' : t('form.modelNamePlaceholder')}
          bind:value={customModelText}
        />
      {/if}
    </div>
  </div>

  {#if hasEffort}
    <div class="field">
      <label for="peffort">{t('form.effort')}</label>
      <p class="help">{t('form.effortHelp')}</p>
      <select id="peffort" class="input select-input" bind:value={effort}>
        {#each EFFORT_LEVELS as level (level.id)}
          <option value={level.id}>{level.label}</option>
        {/each}
      </select>
    </div>
  {/if}

  <div class="field">
    <label for="papikey">
      {t('form.apiKey', { provider: keyPage.name })} <span class="req">*</span>
    </label>
    <p class="help">
      {#if savedKeyUsable}
        {t('form.keySaved', { masked: project?.masked_api_key ?? '' })}
      {:else if editing && project?.has_api_key}
        {t('form.keyOtherProvider', { provider: keyPage.name })}
      {:else}
        {t('form.keyPerProject')}
      {/if}
      <a href={keyPage.url} target="_blank" rel="noopener noreferrer" class="key-link">
        {t('form.getKey')} <Icon name="external" size={10} />
      </a>
    </p>
    <input
      id="papikey"
      type="password"
      class="input mono"
      bind:value={apiKey}
      placeholder={usesDeepseekKey ? 'sk-...' : 'AIzaSy...'}
      autocomplete="off"
      aria-invalid={touched && missing.apiKey ? 'true' : undefined}
    />
    {#if touched && missing.apiKey}<p class="field-error">{t('form.keyError')}</p>{/if}
  </div>

  <div class="field">
    <label for="pfiles">{t('form.docs')}</label>
    <p class="help">
      {t('form.docsHelp')}
      <span class="mono">.md .txt .json .pdf .docx</span>
    </p>

    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="drop"
      class:dragging
      ondragover={(e) => {
        e.preventDefault();
        dragging = true;
      }}
      ondragleave={() => (dragging = false)}
      ondrop={onDrop}
    >
      <Icon name="upload" size={16} />
      <span>
        {t('form.dragFiles')}
        <button type="button" class="linkish" onclick={() => fileInput?.click()}>
          {t('form.pickFromDisk')}
        </button>
      </span>
    </div>
    <input
      id="pfiles"
      bind:this={fileInput}
      type="file"
      multiple
      class="hidden-input"
      onchange={(e) => {
        addFiles(e.currentTarget.files);
        e.currentTarget.value = '';
      }}
    />

    {#if existing.length}
      <ul class="chips">
        {#each existing as path (path)}
          <li class="chip is-saved">
            <Icon name="clip" size={11} />
            {baseName(path)}
          </li>
        {/each}
      </ul>
      <p class="help">{t('form.existingAttachments')}</p>
    {/if}

    {#if files.length}
      <ul class="chips">
        {#each files as file (file.name + file.size)}
          <li class="chip">
            <Icon name="clip" size={11} />
            {file.name}
            <span class="faint mono">{(file.size / 1024).toFixed(0)} KB</span>
            <button
              type="button"
              class="chip-x"
              onclick={() => removeFile(file)}
              aria-label={t('form.removeFile', { name: file.name })}
            >
              <Icon name="close" size={9} />
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  {#if error}
    <p class="field-error" role="alert">{error}</p>
  {/if}

  <div class="form-actions">
    <button type="button" class="btn btn-line" onclick={oncancel} disabled={busy}>
      {t('common.cancel')}
    </button>
    <button type="submit" class="btn btn-solid" disabled={busy}>
      {busy ? t('common.saving') : editing ? t('form.saveChanges') : t('form.create')}
    </button>
  </div>
</form>

<style>
  form {
    display: flex;
    flex-direction: column;
    gap: var(--s5);
    max-width: 46rem;
  }

  .form-actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--s3);
    padding-top: var(--s4);
    border-top: 1px solid var(--rule);
  }

  .drop {
    display: flex;
    align-items: center;
    gap: var(--s3);
    padding: var(--s4);
    border: 1px dashed var(--rule-2);
    color: var(--ink-2);
    font-size: var(--t-small);
    transition:
      border-color var(--fast) var(--ease),
      background var(--fast) var(--ease);
  }

  .drop.dragging {
    border-color: var(--ink);
    background: var(--paper-sunk);
  }

  .linkish {
    padding: 0;
    border: 0;
    background: none;
    color: var(--ink);
    text-decoration: underline;
    text-underline-offset: 2px;
    cursor: pointer;
  }

  .hidden-input {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s2);
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    padding: 0.1875rem 0.375rem;
    border: 1px solid var(--rule-2);
    font-size: var(--t-micro);
  }

  .chip.is-saved {
    border-style: dashed;
    color: var(--ink-2);
  }

  .chip-x {
    display: inline-flex;
    padding: 0;
    margin-left: var(--s1);
    border: 0;
    background: none;
    color: var(--ink-3);
    cursor: pointer;
  }

  .chip-x:hover {
    color: var(--accent);
  }

  .harness-options {
    display: flex;
    flex-direction: column;
    gap: var(--s2);
  }

  .radio-card {
    display: flex;
    align-items: flex-start;
    gap: var(--s3);
    padding: var(--s3);
    border: 1px solid var(--rule-2);
    background: var(--paper);
    cursor: pointer;
    transition:
      border-color var(--fast) var(--ease),
      background var(--fast) var(--ease);
  }

  .radio-card:hover {
    border-color: var(--rule);
  }

  .radio-card.active {
    border-color: var(--ink);
    background: var(--paper-sunk);
  }

  .radio-info {
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
  }

  .radio-title {
    font-size: var(--t-small);
    font-weight: 500;
    color: var(--ink);
  }

  .radio-desc {
    font-size: var(--t-micro);
    color: var(--ink-2);
  }

  /* Plataforma do template: informativa (a escolha fica no campo acima, só na criação). */
  .platform {
    display: block;
    margin-bottom: var(--s1);
    color: var(--ink);
    font-weight: 600;
  }

  .key-link {
    display: inline-flex;
    align-items: center;
    gap: 0.1875rem;
    margin-left: var(--s1);
    color: var(--ink);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .model-select-wrap {
    display: flex;
    flex-direction: column;
    gap: var(--s2);
  }

  .select-input {
    background-color: var(--paper);
    cursor: pointer;
  }

  .notes {
    min-height: 8rem;
  }

  .custom-model-input {
    margin-top: var(--s1);
  }
</style>
