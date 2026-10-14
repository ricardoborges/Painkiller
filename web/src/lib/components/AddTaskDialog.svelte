<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import { api } from '$lib/api';
  import type { Task } from '$lib/types';
  import Modal from './Modal.svelte';
  import Icon from './Icon.svelte';

  /**
   * Tarefa escrita à mão pelo analista. Entra no fim da fila da sessão, antes
   * ou depois de as outras rodarem, e segue o mesmo caminho das que vieram da
   * análise (despacho, testes, merge, issue no Gitea).
   */
  let {
    open = $bindable(false),
    projectId,
    sessionId,
    tasks,
    oncreated
  }: {
    open?: boolean;
    projectId: string;
    sessionId?: string;
    /** Tarefas da sessão: as que ainda não concluíram podem virar dependência. */
    tasks: Task[];
    oncreated: (task: Task) => void;
  } = $props();

  let title = $state('');
  let description = $state('');
  let criteria = $state('');
  let files = $state('');
  let dependencies = $state<string[]>([]);
  let more = $state(false);
  let touched = $state(false);
  let saving = $state(false);
  let error = $state<string | null>(null);

  // Depender de uma tarefa já concluída não muda nada: só as pendentes aparecem.
  const pendingTasks = $derived(tasks.filter((x) => x.status !== 'COMPLETED'));
  const missingTitle = $derived(!title.trim());

  // Cada abertura começa de um formulário limpo.
  $effect(() => {
    if (open) {
      title = description = criteria = files = '';
      dependencies = [];
      more = touched = false;
      error = null;
    }
  });

  const lines = (text: string) =>
    text
      .split('\n')
      .map((l) => l.replace(/^\s*[-*]\s+/, '').trim())
      .filter(Boolean);

  async function save(e: SubmitEvent) {
    e.preventDefault();
    touched = true;
    if (missingTitle || saving) return;
    saving = true;
    error = null;
    try {
      const task = await api.createTask(projectId, {
        title: title.trim(),
        description: description.trim(),
        acceptance_criteria: lines(criteria),
        target_files: lines(files),
        dependencies,
        session_id: sessionId
      });
      open = false;
      oncreated(task);
    } catch (err) {
      error = err instanceof Error ? err.message : t('addTask.failed');
    } finally {
      saving = false;
    }
  }
</script>

<Modal bind:open title={t('addTask.title')} width="38rem">
  {#snippet body()}
    <form id="add-task-form" class="form" onsubmit={save} novalidate>
      <div class="field">
        <label for="task-title">{t('addTask.name')} <span class="req">*</span></label>
        <!-- svelte-ignore a11y_autofocus -->
        <input
          id="task-title"
          class="input"
          bind:value={title}
          placeholder={t('addTask.namePlaceholder')}
          aria-invalid={touched && missingTitle ? 'true' : undefined}
          autofocus
        />
        {#if touched && missingTitle}<p class="field-error">{t('addTask.nameError')}</p>{/if}
      </div>

      <div class="field">
        <label for="task-desc">{t('addTask.description')}</label>
        <textarea id="task-desc" class="textarea" rows="4" bind:value={description}></textarea>
        <p class="help">{t('addTask.descriptionHint')}</p>
      </div>

      <div class="field">
        <label for="task-criteria">{t('addTask.criteria')}</label>
        <textarea id="task-criteria" class="textarea short" bind:value={criteria}></textarea>
        <p class="help">{t('addTask.criteriaHint')}</p>
      </div>

      {#if pendingTasks.length}
        <fieldset class="field deps">
          <legend>{t('addTask.dependencies')}</legend>
          <p class="help">{t('addTask.dependenciesHint')}</p>
          <div class="dep-list">
            {#each pendingTasks as dep (dep.id)}
              <label class="dep">
                <input type="checkbox" value={dep.id} bind:group={dependencies} />
                <span class="truncate">{dep.title}</span>
              </label>
            {/each}
          </div>
        </fieldset>
      {/if}

      <button type="button" class="disclose label" aria-expanded={more} onclick={() => (more = !more)}>
        <span class="mono">{more ? '−' : '+'}</span> {t('addTask.more')}
      </button>
      {#if more}
        <div class="field">
          <label for="task-files">{t('addTask.files')}</label>
          <textarea id="task-files" class="textarea short mono" bind:value={files}></textarea>
          <p class="help">{t('addTask.filesHint')}</p>
        </div>
      {/if}

      {#if error}
        <p class="error" role="alert"><Icon name="alert" size={12} /> {error}</p>
      {/if}
      <p class="faint note">{t('addTask.note')}</p>
    </form>
  {/snippet}
  {#snippet footer()}
    <button type="button" class="btn btn-line btn-sm" onclick={() => (open = false)}>
      {t('common.cancel')}
    </button>
    <button type="submit" form="add-task-form" class="btn btn-solid btn-sm" disabled={saving}>
      <Icon name="plus" size={11} />
      {saving ? t('addTask.creating') : t('addTask.create')}
    </button>
  {/snippet}
</Modal>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--s4);
    padding: var(--s4) var(--s5);
  }

  .textarea.short {
    min-height: 4rem;
  }

  .deps {
    border: 0;
    margin: 0;
    padding: 0;
    min-width: 0;
  }

  .deps legend {
    padding: 0;
    margin-bottom: var(--s2);
    font-size: var(--t-label);
    font-weight: 500;
    letter-spacing: 0.085em;
    text-transform: uppercase;
    color: var(--ink-2);
  }

  .dep-list {
    display: flex;
    flex-direction: column;
    max-height: 10rem;
    overflow-y: auto;
    border: 1px solid var(--rule);
  }

  .dep {
    display: flex;
    gap: var(--s3);
    align-items: center;
    min-width: 0;
    padding: var(--s2) var(--s3);
    cursor: pointer;
  }

  .dep + .dep {
    border-top: 1px solid var(--rule);
  }

  .dep input {
    flex: none;
    accent-color: var(--ink);
  }

  .disclose {
    align-self: flex-start;
    padding: 0;
    background: none;
    border: 0;
    color: var(--ink-2);
    cursor: pointer;
  }

  .disclose:hover {
    color: var(--ink);
  }

  /* Falha ao salvar: peso, não o acento (reservado ao agente esperando). */
  .error {
    display: flex;
    gap: var(--s2);
    align-items: center;
    font-size: var(--t-small);
    font-weight: 600;
    color: var(--ink);
  }

  .note {
    font-size: var(--t-micro);
  }
</style>
