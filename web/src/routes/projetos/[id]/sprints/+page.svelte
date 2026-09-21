<script lang="ts">
  import { api } from '$lib/api';
  import { STATUS_META, STATUS_ORDER, type Task } from '$lib/types';
  import { getProjectSessionStore } from '$lib/stores/session.svelte';
  import { pending } from '$lib/stores/pending.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import StatusTag from '$lib/components/StatusTag.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';
  import Elapsed from '$lib/components/Elapsed.svelte';
  import ClarificationPanel from '$lib/components/ClarificationPanel.svelte';
  import Modal from '$lib/components/Modal.svelte';

  let { data } = $props();

  const sessionStore = $derived(getProjectSessionStore(data.project.id));
  const activeSession = $derived(sessionStore.activeSession);

  let tasks = $state<Task[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let dispatching = $state<string | null>(null);
  let dispatchStart = $state(0);
  let dispatchError = $state<{ id: string; message: string } | null>(null);

  let merging = $state<string | null>(null);
  let diffOpen = $state(false);
  let diffLoading = $state(false);
  let diffData = $state<{ task_id: string; branch: string; diff: string; gitea_url: string | null } | null>(null);

  const byId = $derived(new Map(tasks.map((t) => [t.id, t])));

  const ordered = $derived(
    [...tasks].sort((a, b) => {
      const d = STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status);
      return d !== 0 ? d : a.created_at.localeCompare(b.created_at);
    })
  );

  const counts = $derived.by(() => {
    const map = new Map<string, number>();
    for (const t of tasks) map.set(t.status, (map.get(t.status) ?? 0) + 1);
    return STATUS_ORDER.filter((s) => map.has(s)).map((s) => ({
      status: s,
      label: STATUS_META[s].label,
      n: map.get(s)!
    }));
  });

  const completedCount = $derived(tasks.filter((t) => t.status === 'COMPLETED').length);
  const progressPercent = $derived(tasks.length ? Math.round((completedCount / tasks.length) * 100) : 0);

  function blockers(task: Task) {
    return task.dependencies
      .map((id) => byId.get(id))
      .filter((d): d is Task => !!d && d.status !== 'COMPLETED');
  }

  function canDispatch(task: Task) {
    if (dispatching) return false;
    if (task.status === 'RUNNING' || task.status === 'COMPLETED') return false;
    return blockers(task).length === 0;
  }

  async function load() {
    if (!activeSession) return;
    loading = true;
    error = null;
    try {
      tasks = await api.listSessionTasks(data.project.id, activeSession.id);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Falha ao carregar tarefas da sprint.';
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (activeSession?.id) {
      load();
    }
  });

  function replace(updated: Task) {
    tasks = tasks.map((t) => (t.id === updated.id ? updated : t));
    pending.refresh();
  }

  async function dispatch(task: Task) {
    dispatching = task.id;
    dispatchStart = Date.now();
    dispatchError = null;
    try {
      replace(await api.dispatchTask(task.id));
    } catch (e) {
      dispatchError = {
        id: task.id,
        message: e instanceof Error ? e.message : 'Falha ao despachar agente.'
      };
      load();
    } finally {
      dispatching = null;
    }
  }

  async function merge(task: Task) {
    merging = task.id;
    try {
      replace(await api.mergeTask(task.id));
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Falha ao fazer merge da tarefa.');
    } finally {
      merging = null;
    }
  }

  async function openDiff(taskId: string) {
    diffLoading = true;
    diffOpen = true;
    diffData = null;
    try {
      diffData = await api.getTaskDiff(taskId);
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Falha ao obter diff.');
      diffOpen = false;
    } finally {
      diffLoading = false;
    }
  }

  function when(iso: string) {
    const d = new Date(iso);
    return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
  }
</script>

<div class="grid">
  <div class="main">
    <div class="spread head">
      <div>
        <h2 class="title-session">
          {activeSession ? activeSession.title : 'Sessão'} · Painel de Sprints
        </h2>
        <p class="help">
          Execução ativa de tarefas delegadas para agentes conteinerizados Antigravity CLI (agy) com Superpowers nesta iteração.
        </p>
      </div>

      <div class="head-actions">
        <button type="button" class="btn btn-line btn-sm" onclick={load} disabled={loading}>
          <Icon name="upload" size={12} /> Recarregar
        </button>
      </div>
    </div>

    <!-- Barra de Progresso da Sprint -->
    <div class="progress-bar-card">
      <div class="spread progress-meta">
        <span class="label mono">Progresso da Sprint: {completedCount} de {tasks.length} concluídas</span>
        <span class="mono bold">{progressPercent}%</span>
      </div>
      <div class="progress-track">
        <div class="progress-fill" style:width="{progressPercent}%"></div>
      </div>
    </div>

    {#if loading && !tasks.length}
      <Skeleton variant="lines" rows={6} />
    {:else if error}
      <Placeholder kind="error" title="Não foi possível carregar a sprint" detail={error}>
        {#snippet action()}
          <button type="button" class="btn btn-solid" onclick={load}>Tentar de novo</button>
        {/snippet}
      </Placeholder>
    {:else if !tasks.length}
      <Placeholder
        kind="empty"
        title="Nenhuma tarefa na sprint desta sessão"
        detail="Conclua a análise na aba 'Análise' e importe o backlog na aba 'Backlog' para começar a executar tarefas."
      >
        {#snippet action()}
          <a class="btn btn-solid" href="/projetos/{data.project.id}/analise-inicial">
            <Icon name="play" size={11} /> Ir para a Análise
          </a>
        {/snippet}
      </Placeholder>
    {:else}
      <ol class="task-list">
        {#each ordered as task (task.id)}
          {@const unready = blockers(task)}
          {@const isRunning = task.status === 'RUNNING' || dispatching === task.id}
          {@const needsHelp = task.status === 'AWAITING_ANALYST'}
          <li class="task-item" class:running={isRunning} class:needs-help={needsHelp}>
            <div class="task-header">
              <div class="title-row">
                <span class="mono faint">{task.id}</span>
                <span class="sep">·</span>
                <h3 class="task-title">{task.title}</h3>
                <StatusTag status={task.status} />
              </div>

              <div class="task-actions">
                {#if task.status === 'IN_REVIEW'}
                  <button
                    type="button"
                    class="btn btn-line btn-sm"
                    onclick={() => openDiff(task.id)}
                  >
                    Ver Diff
                  </button>
                  <button
                    type="button"
                    class="btn btn-solid btn-sm"
                    onclick={() => merge(task)}
                    disabled={merging === task.id}
                  >
                    {merging === task.id ? 'Integrando…' : 'Aprovar & Merge'}
                  </button>
                {:else if canDispatch(task)}
                  <button
                    type="button"
                    class="btn btn-solid btn-sm"
                    onclick={() => dispatch(task)}
                    disabled={!!dispatching}
                  >
                    <Icon name="play" size={11} /> Executar
                  </button>
                {/if}
              </div>
            </div>

            <p class="task-desc">{task.description}</p>

            {#if isRunning}
              <div class="running-banner">
                <span class="spinner-inline" aria-hidden="true"></span>
                <span>Agente executando no contêiner…</span>
                {#if dispatchStart}
                  <Elapsed from={dispatchStart} />
                {/if}
              </div>
            {/if}

            {#if needsHelp}
              <div class="clarification-box">
                <ClarificationPanel task={task} onresolved={(updated) => replace(updated)} />
              </div>
            {/if}

            {#if unready.length > 0}
              <div class="blocker-hint faint mono">
                Bloqueada por: {unready.map((b) => b.title).join(', ')}
              </div>
            {/if}

            {#if dispatchError && dispatchError.id === task.id}
              <div class="error-banner mono">
                Erro de execução: {dispatchError.message}
              </div>
            {:else if task.status === 'FAILED' && (task.error || task.last_comment)}
              <div class="error-banner mono">
                {task.error || task.last_comment}
              </div>
            {/if}

            <div class="task-foot faint mono">
              <span>Criada em {when(task.created_at)}</span>
              {#if task.assigned_branch}
                <span class="sep">·</span>
                <span>branch: {task.assigned_branch}</span>
              {/if}
            </div>
          </li>
        {/each}
      </ol>
    {/if}
  </div>

  <aside class="sidebar">
    <div class="side-block">
      <h3 class="label">Status das Tarefas</h3>
      <ul class="counts-list">
        {#each counts as c}
          <li class="spread count-row mono">
            <span>{c.label}</span>
            <span class="bold">{c.n}</span>
          </li>
        {/each}
      </ul>
    </div>
  </aside>
</div>

<!-- Modal de Diff -->
<Modal bind:open={diffOpen} title="Diff da Tarefa">
  {#snippet body()}
    {#if diffLoading}
      <Skeleton variant="lines" rows={8} />
    {:else if diffData}
      <div class="diff-container">
        <div class="diff-meta spread mono faint">
          <span>Branch: {diffData.branch}</span>
          {#if diffData.gitea_url}
            <a href={diffData.gitea_url} target="_blank" rel="noopener noreferrer">
              Abrir no Git <Icon name="external" size={10} />
            </a>
          {/if}
        </div>
        <pre class="diff-code mono">{diffData.diff || 'Sem alterações identificadas.'}</pre>
      </div>
    {/if}
  {/snippet}
</Modal>

<style>
  .grid {
    display: grid;
    grid-template-columns: 1fr 18rem;
    gap: var(--s6);
    padding-top: var(--s5);
  }

  .head {
    align-items: flex-start;
    margin-bottom: var(--s4);
  }

  .title-session {
    font-size: var(--t-h3);
    margin-bottom: var(--s1);
  }

  .progress-bar-card {
    border: 1px solid var(--rule-2);
    padding: var(--s3) var(--s4);
    margin-bottom: var(--s5);
    background: var(--paper-2);
  }

  .progress-track {
    height: 6px;
    background: var(--rule-2);
    margin-top: var(--s2);
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: var(--ink);
    transition: width var(--fast) var(--ease);
  }

  .task-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: var(--s4);
  }

  .task-item {
    border: 1px solid var(--rule-2);
    padding: var(--s4);
    background: var(--paper);
    transition: border-color var(--fast) var(--ease);
  }

  .task-item.running {
    border-color: var(--ink);
  }

  .task-item.needs-help {
    border-color: var(--accent);
  }

  .task-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--s4);
    margin-bottom: var(--s2);
  }

  .title-row {
    display: flex;
    align-items: center;
    gap: var(--s2);
    flex-wrap: wrap;
  }

  .task-title {
    font-size: var(--t-body);
    font-weight: 500;
  }

  .task-desc {
    color: var(--ink-2);
    font-size: var(--t-small);
    line-height: 1.5;
    margin-bottom: var(--s3);
  }

  .running-banner {
    display: flex;
    align-items: center;
    gap: var(--s2);
    padding: var(--s2) var(--s3);
    background: var(--paper-2);
    border-left: 2px solid var(--ink);
    font-size: var(--t-small);
    margin-bottom: var(--s3);
  }

  .clarification-box {
    margin-block: var(--s3);
  }

  .blocker-hint {
    font-size: var(--t-micro);
    color: var(--ink-4);
    margin-bottom: var(--s2);
  }

  .error-banner {
    padding: var(--s2);
    background: var(--paper-2);
    border: 1px solid var(--accent);
    color: var(--accent);
    font-size: var(--t-small);
    margin-bottom: var(--s3);
  }

  .task-foot {
    font-size: var(--t-micro);
    border-top: 1px solid var(--rule-2);
    padding-top: var(--s2);
  }

  .sep {
    margin-inline: 0.25rem;
  }

  .sidebar {
    border-left: 1px solid var(--rule-2);
    padding-left: var(--s6);
  }

  .side-block {
    display: flex;
    flex-direction: column;
    gap: var(--s3);
  }

  .counts-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: var(--s2);
  }

  .count-row {
    font-size: var(--t-small);
  }

  .diff-container {
    display: flex;
    flex-direction: column;
    gap: var(--s3);
  }

  .diff-code {
    max-height: 60vh;
    overflow: auto;
    padding: var(--s3);
    background: var(--paper-2);
    border: 1px solid var(--rule-2);
    font-size: var(--t-micro);
    line-height: 1.4;
  }

  @media (max-width: 900px) {
    .grid {
      grid-template-columns: 1fr;
    }
    .sidebar {
      border-left: none;
      border-top: 1px solid var(--rule-2);
      padding-left: 0;
      padding-top: var(--s4);
    }
  }
</style>
