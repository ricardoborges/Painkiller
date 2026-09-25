<script lang="ts">
  import { api, baseName } from '$lib/api';
  import {
    DEEPSEEK_KEY_HARNESSES,
    EFFORT_HARNESSES,
    EFFORT_LEVELS,
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

  const MODEL_PRESETS: Record<HarnessType, { id: string; label: string }[]> = {
    maki_superpowers: [
      { id: 'deepseek/deepseek-v4-pro', label: 'deepseek/deepseek-v4-pro (Padrão / Recomendado)' },
      { id: 'deepseek/deepseek-v4-flash', label: 'deepseek/deepseek-v4-flash' },
      { id: 'deepseek/deepseek-flash', label: 'deepseek/deepseek-flash' }
    ],
    agy_superpowers: [
      { id: 'gemini-3.8-flash', label: 'gemini-3.8-flash (Padrão)' },
      { id: 'gemini-3.8-pro', label: 'gemini-3.8-pro' },
      { id: 'gemini-2.5-flash', label: 'gemini-2.5-flash' },
      { id: 'gemini-2.5-pro', label: 'gemini-2.5-pro' }
    ],
    deepseek_superpowers: [
      { id: 'deepseek-v4-pro', label: 'deepseek-v4-pro (Recomendado)' },
      { id: 'deepseek-v4-flash', label: 'deepseek-v4-flash' }
    ],
    // A Responses API da DeepSeek recebe o id sem o prefixo `provider/` do maki.
    unreal_superpowers: [
      { id: 'deepseek-v4-pro', label: 'deepseek-v4-pro (Padrão / Recomendado)' },
      { id: 'deepseek-flash', label: 'deepseek-flash' }
    ]
  };

  function defaultModelFor(h: HarnessType): string {
    return MODEL_PRESETS[h]?.[0]?.id ?? '';
  }

  let model = $state('');
  let effort = $state<EffortLevel>('medium');
  const hasEffort = $derived(EFFORT_HARNESSES.includes(harness));
  let isCustomModel = $state(false);
  let customModelText = $state('');

  /** Valor da opção "Outra" em Solução desejada: abre o campo de texto livre. */
  const OTHER_SOLUTION = '__other__';

  let templates = $state<ProjectTemplate[]>([]);
  /** Id do template escolhido, OTHER_SOLUTION ou '' (nada escolhido ainda). */
  let solutionChoice = $state<string>('');
  const selectedTemplate = $derived(templates.find((t) => t.id === solutionChoice) ?? null);
  // Sem templates cadastrados não há o que listar: o campo livre aparece direto.
  const writesSolution = $derived(templates.length === 0 || solutionChoice === OTHER_SOLUTION);

  /** Texto que vai em solution_description quando um template é escolhido. */
  function templateSolution(t: ProjectTemplate): string {
    return (t.prompt || t.description || t.name).trim();
  }

  const effectiveSolution = $derived(
    writesSolution ? solution.trim() : selectedTemplate ? templateSolution(selectedTemplate) : ''
  );

  async function loadTemplates(currentSolution: string) {
    try {
      templates = await api.listActiveTemplates();
    } catch {
      templates = [];
    }
    // Na edição, reconhece o template cuja solução o projeto ainda usa.
    if (currentSolution) {
      const match = templates.find((t) => templateSolution(t) === currentSolution.trim());
      solutionChoice = match ? match.id : OTHER_SOLUTION;
    }
  }

  function onSolutionChoice(id: string) {
    solutionChoice = id;
    const t = templates.find((x) => x.id === id);
    if (t && !description && t.description) description = t.description;
  }

  // Repopula ao montar e sempre que o projeto editado muda
  $effect(() => {
    solutionChoice = project?.solution_description ? OTHER_SOLUTION : '';
    loadTemplates(project?.solution_description ?? '');
    name = project?.name ?? '';
    description = project?.description ?? '';
    purpose = project?.purpose ?? '';
    solution = project?.solution_description ?? '';
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
          error = check.detail ?? 'O provedor recusou a chave.';
          return;
        }
      }
      const body: {
        name: string;
        description: string;
        purpose: string;
        solution_description: string;
        harness: HarnessType;
        api_key?: string;
        model?: string;
        effort?: string;
      } = {
        name: name.trim(),
        description: description.trim(),
        purpose: purpose.trim(),
        solution_description: effectiveSolution,
        harness: harness,
        model: effectiveModel || undefined,
        // Só agy e dsh têm o ajuste; para os demais o backend o descarta.
        effort: hasEffort ? effort : undefined
      };
      if (apiKey.trim()) {
        body.api_key = apiKey.trim();
      }

      let saved = editing
        ? await api.updateProject(project!.id, body)
        : await api.createProject(body);

      for (const file of files) {
        const res = await api.uploadAttachment(saved.id, file);
        saved = res.project;
      }

      onsaved(saved);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Não foi possível salvar o projeto.';
    } finally {
      busy = false;
    }
  }
</script>

<form id="project-form" onsubmit={save} novalidate>
  <div class="field">
    <label for="pname">Nome <span class="req">*</span></label>
    <input
      id="pname"
      class="input"
      bind:value={name}
      placeholder="Nome do projeto"
      aria-invalid={touched && missing.name ? 'true' : undefined}
    />
    {#if touched && missing.name}<p class="field-error">Informe um nome.</p>{/if}
  </div>

  <div class="field">
    <label for="pdesc">Descrição geral</label>
    <textarea
      id="pdesc"
      class="textarea"
      bind:value={description}
      placeholder="Visão panorâmica do que o projeto contempla."
    ></textarea>
  </div>

  <div class="field">
    <label for="ppurp">Propósito <span class="req">*</span></label>
    <textarea
      id="ppurp"
      class="textarea"
      bind:value={purpose}
      placeholder="Que dor de negócio isto resolve?"
      aria-invalid={touched && missing.purpose ? 'true' : undefined}
    ></textarea>
    {#if touched && missing.purpose}<p class="field-error">Informe o propósito.</p>{/if}
  </div>

  <div class="field">
    <label for={templates.length ? 'psol-options' : 'psol'}>
      Solução desejada <span class="req">*</span>
    </label>
    {#if templates.length}
      <p class="help">Escolha um template cadastrado ou descreva outra solução.</p>
      <div id="psol-options" class="harness-options">
        {#each templates as t (t.id)}
          <label class="radio-card" class:active={solutionChoice === t.id}>
            <input
              type="radio"
              name="solution"
              value={t.id}
              checked={solutionChoice === t.id}
              onchange={() => onSolutionChoice(t.id)}
            />
            <div class="radio-info">
              <span class="radio-title">{t.name}</span>
              <span class="radio-desc">
                {PROJECT_TYPE_META[t.project_type]?.label || t.project_type}
                {#if t.coolify_compatible}· Compatível com Coolify{/if}
                {#if t.description}· {t.description}{/if}
              </span>
            </div>
          </label>
        {/each}
        <label class="radio-card" class:active={solutionChoice === OTHER_SOLUTION}>
          <input
            type="radio"
            name="solution"
            value={OTHER_SOLUTION}
            checked={solutionChoice === OTHER_SOLUTION}
            onchange={() => onSolutionChoice(OTHER_SOLUTION)}
          />
          <div class="radio-info">
            <span class="radio-title">Outra</span>
            <span class="radio-desc">Descrever a solução com as próprias palavras</span>
          </div>
        </label>
      </div>
    {/if}
    {#if writesSolution}
      <textarea
        id="psol"
        class="textarea"
        bind:value={solution}
        placeholder="Como a arquitetura e as regras devem se comportar?"
        aria-invalid={touched && missing.solution ? 'true' : undefined}
      ></textarea>
    {/if}
    {#if touched && missing.solution}
      <p class="field-error">
        {writesSolution ? 'Descreva a solução.' : 'Escolha um template ou descreva outra solução.'}
      </p>
    {/if}
  </div>

  <div class="field">
    <label for="pharness-options">Harness do Agente</label>
    <p class="help">
      Escolha o motor de execução que rodará a análise e as tarefas de desenvolvimento.
    </p>
    <div id="pharness-options" class="harness-options">
      <label class="radio-card" class:active={harness === 'agy_superpowers'}>
        <input
          type="radio"
          name="harness"
          value="agy_superpowers"
          bind:group={harness}
        />
        <div class="radio-info">
          <span class="radio-title">Antigravity CLI (agy) + Superpowers</span>
          <span class="radio-desc">Google Gemini (3.8 Flash / Thinking) via agy CLI oficial</span>
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
          <span class="radio-title">DeepSeek Harness (dsh) + Superpowers</span>
          <span class="radio-desc">DeepSeek V4 via @deepseek-ai/dsh oficial</span>
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
          <span class="radio-title">Maki + Superpowers</span>
          <span class="radio-desc">DeepSeek V4 via maki.sh, com a mesma chave DeepSeek</span>
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
          <span class="radio-title">Unreal Agent + Superpowers</span>
          <span class="radio-desc">DeepSeek V4 via Unreal Agent runner em Go, com chave DeepSeek</span>
        </div>
      </label>
    </div>
  </div>

  <div class="field">
    <label for="pmodel">Modelo de IA</label>
    <p class="help">
      Modelo que o harness executará. Para o Maki, o padrão selecionado é <span class="mono">deepseek/deepseek-v4-pro</span>; para o Unreal Agent, <span class="mono">deepseek-v4-pro</span>.
    </p>
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
        <option value="__custom__">Outro modelo (personalizado)…</option>
      </select>
      {#if isCustomModel}
        <input
          type="text"
          class="input mono custom-model-input"
          placeholder={harness === 'maki_superpowers' ? 'deepseek/deepseek-v4-pro' : harness === 'unreal_superpowers' ? 'deepseek-v4-pro' : 'nome-do-modelo'}
          bind:value={customModelText}
        />
      {/if}
    </div>
  </div>

  {#if hasEffort}
    <div class="field">
      <label for="peffort">Esforço de raciocínio</label>
      <p class="help">Quanto o modelo pensa antes de responder. Mais esforço custa mais tokens.</p>
      <select id="peffort" class="input select-input" bind:value={effort}>
        {#each EFFORT_LEVELS as level (level.id)}
          <option value={level.id}>{level.label}</option>
        {/each}
      </select>
    </div>
  {/if}

  <div class="field">
    <label for="papikey">
      Chave de API {keyPage.name} <span class="req">*</span>
    </label>
    <p class="help">
      {#if savedKeyUsable}
        Chave configurada ({project?.masked_api_key}). Deixe em branco para mantê-la.
      {:else if editing && project?.has_api_key}
        Este harness usa outra conta de provedor: informe uma chave {keyPage.name}.
      {:else}
        Cada projeto usa a própria chave; o consumo sai da conta dona dela.
      {/if}
      <a href={keyPage.url} target="_blank" rel="noopener noreferrer" class="key-link">
        Obter uma chave <Icon name="external" size={10} />
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
    {#if touched && missing.apiKey}<p class="field-error">Informe a chave de API.</p>{/if}
  </div>

  <div class="field">
    <label for="pfiles">Documentos de contexto</label>
    <p class="help">
      Lidos e injetados no prompt do agente de análise.
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
        Arraste arquivos ou
        <button type="button" class="linkish" onclick={() => fileInput?.click()}>
          escolha do disco
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
      <p class="help">
        Anexos já enviados. A API não expõe remoção — novos arquivos são acrescentados.
      </p>
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
              aria-label="Remover {file.name}"
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
      Cancelar
    </button>
    <button type="submit" class="btn btn-solid" disabled={busy}>
      {busy ? 'Salvando…' : editing ? 'Salvar alterações' : 'Criar projeto'}
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

  .custom-model-input {
    margin-top: var(--s1);
  }
</style>
