<script lang="ts">
  import { t, tp, formatNumber } from '$lib/i18n/index.svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api';
  import {
    STATUS_META,
    STATUS_ORDER,
    type Task,
    type EnvironmentStatusResponse,
    type DeploymentRecord
  } from '$lib/types';
  import { pending } from '$lib/stores/pending.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import StatusTag from '$lib/components/StatusTag.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';
  import TaskActivity from '$lib/components/TaskActivity.svelte';
  import ClarificationPanel from '$lib/components/ClarificationPanel.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import { getProjectSessionStore } from '$lib/stores/session.svelte';
  import { deploys, isDeployActive, deployStage, lastLogLine } from '$lib/stores/deploys.svelte';
  import { formatDuration, formatTokens, taskTotals } from '$lib/metrics';
  import { onDestroy } from 'svelte';

  let { data } = $props();

  const sessionStore = $derived(getProjectSessionStore(data.project.id));
  const activeSession = $derived(sessionStore.activeSession);
  // Só a sessão mais recente ainda tem as branches das tarefas: ao abrir a
  // próxima, o backend finaliza a anterior e apaga as branches incorporadas.
  const branchesAlive = $derived(
    !!activeSession &&
      activeSession.status !== 'COMPLETED' &&
      activeSession.id === sessionStore.sessions[sessionStore.sessions.length - 1]?.id
  );

  let tasks = $state<Task[]>([]);
  let candidatesForMigration = $state<Task[]>([]);
  let loading = $state(true);
  let migrating = $state(false);
  let error = $state<string | null>(null);
  let syncingIssues = $state(false);
  let finalizing = $state(false);
  let issuesNote = $state<string | null>(null);

  // Execução individual
  let dispatching = $state<string | null>(null);
  let dispatchError = $state<{ id: string; message: string } | null>(null);
  let merging = $state<string | null>(null);
  let stoppingTaskId = $state<string | null>(null);
  let abbreviatingTaskId = $state<string | null>(null);

  // Fila sequencial (Executar Todas)
  let isQueueRunning = $state(false);
  let queueMessage = $state<string | null>(null);

  // Modal de Diff
  let diffOpen = $state(false);
  let diffLoading = $state(false);
  let diffData = $state<{ task_id: string; branch: string; base_branch: string; diff: string; gitea_url: string | null } | null>(null);

  // Deploys (Coolify)
  let envStatus = $state<EnvironmentStatusResponse | null>(null);
  let deployingEnv = $state<'test' | 'production' | null>(null);
  let deployingTaskId = $state<string | null>(null);
  let deploymentModalOpen = $state(false);
  // O registro vive no rastreador (que consulta o Coolify até terminar); aqui
  // só se guarda qual deploy o modal mostra.
  let shownDeploymentId = $state<string | null>(null);
  const currentDeployment = $derived<DeploymentRecord | null>(
    (shownDeploymentId && deploys.records[shownDeploymentId]) || deploys.latest(data.project.id)
  );
  const runningDeploy = $derived(deploys.active(data.project.id));
  const productionDeploy = $derived(deploys.active(data.project.id, 'production'));
  let logBox = $state<HTMLPreElement | null>(null);

  const justCreated = $derived(Number(page.url.searchParams.get('new') ?? 0));
  const byId = $derived(new Map(tasks.map((t) => [t.id, t])));

  /**
   * Ordena as tarefas em fila sequencial válida de execução.
   * Realiza ordenação topológica garantindo que pré-requisitos/dependências
   * sempre apareçam e sejam executados antes de suas dependentes.
   */
  const ordered = $derived.by(() => {
    const result: Task[] = [];
    const visited = new Set<string>();
    const taskMap = new Map(tasks.map((t) => [t.id, t]));

    function visit(task: Task, stack = new Set<string>()) {
      if (visited.has(task.id) || stack.has(task.id)) return;
      stack.add(task.id);
      for (const depId of task.dependencies) {
        const depTask = taskMap.get(depId);
        if (depTask && !visited.has(depId)) {
          visit(depTask, stack);
        }
      }
      visited.add(task.id);
      result.push(task);
    }

    // Ponto de partida: ordem cronológica de planejamento
    const base = [...tasks].sort((a, b) => a.created_at.localeCompare(b.created_at));
    for (const t of base) {
      visit(t);
    }
    return result;
  });

  const completedCount = $derived(tasks.filter((t) => t.status === 'COMPLETED').length);
  const allDone = $derived(tasks.length > 0 && completedCount === tasks.length);
  const sessionClosed = $derived(activeSession?.status === 'COMPLETED');
  const progressPercent = $derived(tasks.length ? Math.round((completedCount / tasks.length) * 100) : 0);
  const sessionTotals = $derived(taskTotals(tasks));

  const counts = $derived.by(() => {
    const map = new Map<string, number>();
    for (const t of tasks) map.set(t.status, (map.get(t.status) ?? 0) + 1);
    return STATUS_ORDER.filter((s) => map.has(s)).map((s) => ({
      status: s,
      label: STATUS_META[s].label,
      n: map.get(s)!
    }));
  });

  /** Dependências que ainda não concluíram — orquestrador exige que estejam COMPLETED. */
  function blockers(task: Task): Task[] {
    return task.dependencies
      .map((id) => byId.get(id))
      .filter((d): d is Task => !!d && d.status !== 'COMPLETED');
  }

  function canDispatch(task: Task): boolean {
    if (dispatching || isQueueRunning) return false;
    if (task.status === 'RUNNING' || task.status === 'COMPLETED' || task.status === 'IN_REVIEW') return false;
    return blockers(task).length === 0;
  }

  /* Linhas começam recolhidas. Tarefa em execução ou esperando o analista
     abre sozinha; a escolha do usuário prevalece até a tarefa voltar a
     precisar de atenção (ex.: um novo despacho). */
  let expandOverride = $state<Record<string, boolean>>({});
  let wasActive = new Set<string>();

  function needsAttention(task: Task): boolean {
    return (
      dispatching === task.id ||
      task.status === 'RUNNING' ||
      task.status === 'AWAITING_ANALYST' ||
      dispatchError?.id === task.id
    );
  }

  function isOpen(task: Task): boolean {
    return expandOverride[task.id] ?? needsAttention(task);
  }

  function toggle(task: Task) {
    expandOverride[task.id] = !isOpen(task);
  }

  function setAll(open: boolean) {
    expandOverride = Object.fromEntries(tasks.map((t) => [t.id, open]));
  }

  /* O erro chega como um parágrafo de resumo e, às vezes, o log bruto inteiro
     (falhas anteriores guardavam centenas de KB). Mostra só o resumo; o resto
     fica recolhido, rolando dentro de uma caixa de altura fixa. */
  const ERROR_TAIL = 20_000;

  function splitError(message: string): { head: string; rest: string; huge: boolean } {
    const text = message.trim();
    const cut = text.indexOf('\n\n') >= 0 ? text.indexOf('\n\n') : text.indexOf('\n');
    let head = (cut >= 0 ? text.slice(0, cut) : text).replace(/^❌\s*/, '');
    let rest = cut >= 0 ? text.slice(cut).trim() : '';
    if (head.length > 400) {
      rest = head.slice(400) + (rest ? '\n\n' + rest : '');
      head = head.slice(0, 400) + '…';
    }
    const legacy = head.match(/exit code (\d+)/);
    if (legacy) {
      head =
        legacy[1] === '137'
          ? t('backlog.killed137')
          : t('backlog.exitCode', { code: legacy[1] });
    }
    const huge = rest.length > 2000;
    if (rest.length > ERROR_TAIL) rest = '…\n' + rest.slice(-ERROR_TAIL);
    return { head, rest, huge };
  }

  function stepLabel(id: string): string {
    const idx = ordered.findIndex((t) => t.id === id);
    return idx < 0 ? '' : `#${String(idx + 1).padStart(2, '0')}`;
  }

  $effect(() => {
    const active = new Set(tasks.filter(needsAttention).map((t) => t.id));
    for (const id of active) {
      if (!wasActive.has(id) && id in expandOverride) delete expandOverride[id];
    }
    wasActive = active;
  });

  async function load() {
    loading = true;
    error = null;
    try {
      if (activeSession?.id) {
        tasks = await api.listSessionTasks(data.project.id, activeSession.id);
        const all = await api.listTasks(data.project.id);
        candidatesForMigration = all.filter(
          (t) => t.session_id !== activeSession.id && t.status !== 'COMPLETED'
        );
      } else {
        tasks = await api.listTasks(data.project.id);
        candidatesForMigration = [];
      }
    } catch (e) {
      error = e instanceof Error ? e.message : t('backlog.loadFailed');
    } finally {
      loading = false;
    }
  }

  /* As tarefas novas já viram issues sozinhas; isto cobre as anteriores à
     integração e realinha estado e rótulos de todas. */
  async function syncIssues() {
    syncingIssues = true;
    issuesNote = null;
    try {
      const res = await api.syncIssues(data.project.id);
      issuesNote = !res.enabled
        ? t('backlog.noGiteaRepo')
        : res.created
          ? tp('backlog.issuesCreated', res.created)
          : t('backlog.issuesInSync');
      await load();
    } catch (e) {
      issuesNote = e instanceof Error ? e.message : t('backlog.syncFailed');
    } finally {
      syncingIssues = false;
    }
  }

  async function finalizeSession() {
    if (!activeSession || finalizing) return;
    const ok = confirm(t('backlog.confirmFinalize', { title: activeSession.title }));
    if (!ok) return;
    finalizing = true;
    try {
      if (!(await sessionStore.finalizeSession(activeSession.id))) {
        alert(sessionStore.error ?? t('analysisStore.closeFailed'));
        return;
      }
      // Com uma sessão encerrada a entrada do projeto é o painel.
      await goto(`/projects/${data.project.id}`);
    } finally {
      finalizing = false;
    }
  }

  async function startNextSession() {
    if (await sessionStore.createNextSession()) {
      await goto(`/projects/${data.project.id}/initial-analysis`);
    }
  }

  async function migratePendingTasks() {
    if (!activeSession?.id || !candidatesForMigration.length) return;
    migrating = true;
    try {
      await api.migrateTasksToSession(
        data.project.id,
        activeSession.id,
        candidatesForMigration.map((t) => t.id)
      );
      await load();
    } catch (e) {
      alert(e instanceof Error ? e.message : t('backlog.migrateFailed'));
    } finally {
      migrating = false;
    }
  }

  async function loadEnvStatus() {
    try {
      envStatus = await api.getEnvironmentStatus(data.project.id);
      // Um deploy disparado antes de um F5 (ou em outra aba) continua sendo
      // acompanhado daqui.
      for (const env of [envStatus.test, envStatus.production]) {
        if (env.deployment_id && (env.status === 'PENDING' || env.status === 'BUILDING')) {
          deploys.resume(env.deployment_id);
        }
      }
    } catch {
      // Ignora erro para não bloquear interface
    }
  }

  function showDeployment(id: string) {
    shownDeploymentId = id;
    deploymentModalOpen = true;
  }

  // Deploy encerrado: as URLs e os pontos de status da barra de ambientes mudam.
  $effect(() => {
    if (deploys.settled) loadEnvStatus();
  });

  // O log acompanha o fim enquanto chega, como um terminal.
  $effect(() => {
    void currentDeployment?.logs;
    if (logBox && deploymentModalOpen) logBox.scrollTop = logBox.scrollHeight;
  });

  async function deployTest(taskId: string) {
    const running = deploys.activeForTask(taskId);
    if (running) {
      showDeployment(running.id);
      return;
    }
    deployingEnv = 'test';
    deployingTaskId = taskId;
    try {
      const record = await api.triggerDeploy(
        data.project.id,
        'test',
        taskId,
        activeSession?.id
      );
      deploys.track(record);
      showDeployment(record.id);
      await loadEnvStatus();
    } catch (e) {
      alert(e instanceof Error ? e.message : t('backlog.deployTestFailed'));
    } finally {
      deployingEnv = null;
      deployingTaskId = null;
    }
  }

  async function deployProduction() {
    if (productionDeploy) {
      showDeployment(productionDeploy.id);
      return;
    }
    if (!confirm(t('backlog.confirmProduction'))) {
      return;
    }
    deployingEnv = 'production';
    try {
      const record = await api.triggerDeploy(
        data.project.id,
        'production',
        undefined,
        activeSession?.id
      );
      deploys.track(record);
      showDeployment(record.id);
      await loadEnvStatus();
    } catch (e) {
      alert(e instanceof Error ? e.message : t('backlog.deployProductionFailed'));
    } finally {
      deployingEnv = null;
    }
  }

  $effect(() => {
    if (activeSession?.id || !sessionStore.loading) {
      load();
      loadEnvStatus();
    }
  });

  $effect(() => {
    // Auto-merge é regra: qualquer tarefa em IN_REVIEW é incorporada imediatamente
    const pendingReview = tasks.filter((t) => t.status === 'IN_REVIEW' && merging !== t.id);
    for (const t of pendingReview) {
      merge(t);
    }
  });

  function replace(updated: Task) {
    tasks = tasks.map((t) => (t.id === updated.id ? updated : t));
    pending.refresh();
  }

  async function dispatch(task: Task): Promise<Task | null> {
    dispatching = task.id;
    dispatchError = null;

    // Se sessão ainda estava em BACKLOG, avança status para IN_SPRINT
    if (activeSession && activeSession.status === 'BACKLOG') {
      api.updateSession(data.project.id, activeSession.id, { status: 'IN_SPRINT' as any }).catch(() => {});
    }

    try {
      const updated = await api.dispatchTask(task.id);
      replace(updated);

      // Auto-merge é regra: passou nos testes (IN_REVIEW) → incorpora na branch
      // principal e conclui a tarefa
      if (updated.status === 'IN_REVIEW') {
        const merged = await merge(updated);
        return merged;
      }

      return updated;
    } catch (e) {
      const msg = e instanceof Error ? e.message : t('backlog.dispatchFailed');
      dispatchError = { id: task.id, message: msg };
      await load();
      return null;
    } finally {
      dispatching = null;
    }
  }

  async function merge(task: Task): Promise<Task | null> {
    merging = task.id;
    try {
      const updated = await api.mergeTask(task.id);
      replace(updated);
      return updated;
    } catch (e) {
      const msg = e instanceof Error ? e.message : t('backlog.mergeFailed');
      dispatchError = { id: task.id, message: msg };
      return null;
    } finally {
      merging = null;
    }
  }

  async function abbreviateTests(task: Task) {
    if (abbreviatingTaskId === task.id) return;
    const ok = confirm(t('backlog.confirmAbbreviate'));
    if (!ok) return;
    abbreviatingTaskId = task.id;
    try {
      const res = await api.abbreviateTests(task.id);
      replace({ ...task, skip_tests: true });
      // Sem execução viva neste servidor (ex.: após um restart), a tarefa foi
      // liberada e é despachada de novo daqui, já sem testes.
      if (!res.restarting) {
        await load();
        const fresh = tasks.find((t) => t.id === task.id);
        if (fresh && fresh.status !== 'RUNNING' && fresh.status !== 'COMPLETED') await dispatch(fresh);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : t('backlog.abbreviateFailed');
      dispatchError = { id: task.id, message: msg };
    } finally {
      abbreviatingTaskId = null;
    }
  }

  async function stopTask(id: string) {
    if (stoppingTaskId === id) return;
    stoppingTaskId = id;
    if (isQueueRunning) {
      isQueueRunning = false;
      queueMessage = t('backlog.queue.stopped');
    }
    try {
      await api.stopTask(id);
    } catch (e) {
      console.error('Failed to stop task:', e);
    } finally {
      setTimeout(() => {
        if (stoppingTaskId === id) stoppingTaskId = null;
        load();
      }, 1500);
    }
  }

  /**
   * Executador Sequencial da Fila ("Executar Todas").
   * Roda estritamente 1 tarefa por vez na ordem de execução.
   */
  async function toggleRunAll() {
    if (isQueueRunning) {
      isQueueRunning = false;
      queueMessage = t('backlog.queue.paused');
      return;
    }

    isQueueRunning = true;
    queueMessage = t('backlog.queue.starting');

    try {
      while (isQueueRunning) {
        // Encontra a próxima tarefa não concluída na ordem de execução
        const uncompleted = ordered.filter((t) => t.status !== 'COMPLETED');
        if (uncompleted.length === 0) {
          queueMessage = t('backlog.queue.allDone');
          isQueueRunning = false;
          break;
        }

        const candidate = uncompleted[0];

        // Caso a tarefa já esteja em revisão (ex: rodou e aguarda merge)
        if (candidate.status === 'IN_REVIEW') {
          queueMessage = t('backlog.queue.merging', { title: candidate.title });
          const merged = await merge(candidate);
          if (!merged) {
            queueMessage = t('backlog.queue.mergeFailed', { title: candidate.title });
            isQueueRunning = false;
            break;
          }
          await new Promise((r) => setTimeout(r, 600));
          continue;
        }

        // Caso a tarefa esteja esperando esclarecimento humano
        if (candidate.status === 'AWAITING_ANALYST') {
          queueMessage = t('backlog.queue.needsClarification', { title: candidate.title });
          isQueueRunning = false;
          break;
        }

        // Verifica bloqueios de dependência
        const stuck = blockers(candidate);
        if (stuck.length > 0) {
          queueMessage = t('backlog.queue.blocked', { title: candidate.title, deps: stuck.map((s) => s.title).join(', ') });
          isQueueRunning = false;
          break;
        }

        // Despacha a tarefa no contêiner
        queueMessage = t('backlog.queue.running', { title: candidate.title });
        const updated = await dispatch(candidate);

        if (!isQueueRunning) break; // Usuário pausou durante a execução

        if (!updated) {
          queueMessage = t('backlog.queue.runFailed', { title: candidate.title });
          isQueueRunning = false;
          break;
        }

        // Processa o resultado
        if (updated.status === 'IN_REVIEW') {
          // dispatch() já tentou o merge; se voltou IN_REVIEW, ele falhou
          queueMessage = t('backlog.queue.autoMergeError', { title: updated.title });
          isQueueRunning = false;
          break;
        } else if (updated.status === 'AWAITING_ANALYST') {
          queueMessage = t('backlog.queue.question', { title: updated.title });
          isQueueRunning = false;
          break;
        } else if (updated.status === 'FAILED') {
          queueMessage = t('backlog.queue.failed', { title: updated.title });
          isQueueRunning = false;
          break;
        }

        // Pausa breve entre execuções
        await new Promise((r) => setTimeout(r, 600));
      }
    } finally {
      if (ordered.length > 0 && ordered.every((t) => t.status === 'COMPLETED')) {
        queueMessage = t('backlog.queue.allTasksDone');
        isQueueRunning = false;
      }
    }
  }

  async function openDiff(taskId: string) {
    diffLoading = true;
    diffOpen = true;
    diffData = null;
    try {
      diffData = await api.getTaskDiff(taskId);
    } catch (e) {
      alert(e instanceof Error ? e.message : t('backlog.diffFailed'));
      diffOpen = false;
    } finally {
      diffLoading = false;
    }
  }

  onDestroy(() => {
    isQueueRunning = false;
  });
</script>

{#if justCreated > 0}
  <p class="created label" role="status">
    <Icon name="check" size={12} />
    {tp('backlog.justCreated', justCreated)}
  </p>
{/if}

{#if loading && !tasks.length}
  <div class="pad"><Skeleton variant="table" rows={5} /></div>
{:else if error}
  <Placeholder kind="error" title={t('backlog.loadFailedTitle')} detail={error}>
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={load}>{t('common.retry')}</button>
    {/snippet}
  </Placeholder>
{:else if tasks.length === 0}
  <Placeholder
    title={t('backlog.emptyTitle')}
    detail={t('backlog.emptyDetail')}
  >
    {#snippet action()}
      <a class="btn btn-solid" href="/projects/{data.project.id}/initial-analysis">
        <Icon name="play" size={11} /> {t('backlog.goToAnalysis')}
      </a>
    {/snippet}
  </Placeholder>
{:else}
  {#if candidatesForMigration.length > 0}
    <div class="migration-banner spread">
      <span class="mono label">
        {tp('backlog.migrationPending', candidatesForMigration.length)}
      </span>
      <button
        type="button"
        class="btn btn-line btn-sm"
        onclick={migratePendingTasks}
        disabled={migrating}
      >
        <Icon name="upload" size={11} />
        {migrating ? t('backlog.migrating') : t('backlog.migrateTo', { title: activeSession?.title ?? t('backlog.thisSession') })}
      </button>
    </div>
  {/if}

  <!-- Barra de Progresso da Sessão Ativa -->
  <div class="progress-bar-card">
    <div class="spread progress-meta">
      <div class="meta-left">
        <span class="session-badge mono bold">
          {activeSession ? `#${activeSession.number} ${activeSession.title}` : t('backlog.activeSession')}
        </span>
        <span class="sep" aria-hidden="true">·</span>
        <span class="label mono">
          {t('backlog.progress', { done: completedCount, total: tasks.length })}
        </span>
        <span class="sep" aria-hidden="true">·</span>
        <span
          class="label mono"
          title={t('backlog.sessionTotalsTitle', { input: formatNumber(sessionTotals.input), output: formatNumber(sessionTotals.output) })}
        >
          {formatDuration(sessionTotals.seconds)} · {t('backlog.inOut', { input: formatTokens(sessionTotals.input), output: formatTokens(sessionTotals.output) })}
        </span>
      </div>
      <span class="mono bold">{progressPercent}%</span>
    </div>
    <div class="progress-track">
      <div class="progress-fill" style:width="{progressPercent}%"></div>
    </div>

    {#if activeSession && (sessionClosed || (allDone && branchesAlive))}
      <div class="session-close spread">
        {#if sessionClosed}
          <span class="mono">{t('backlog.sessionClosed')}</span>
          {#if activeSession.id === sessionStore.sessions[sessionStore.sessions.length - 1]?.id}
            <button
              type="button"
              class="btn btn-solid btn-sm"
              onclick={startNextSession}
              disabled={sessionStore.creating}
            >
              <Icon name="plus" size={11} />
              {sessionStore.creating ? t('sessionPicker.creating') : t('sessionPicker.new')}
            </button>
          {/if}
        {:else}
          <span class="mono">{t('backlog.allDoneClose')}</span>
          <button
            type="button"
            class="btn btn-solid btn-sm"
            onclick={finalizeSession}
            disabled={finalizing || isQueueRunning}
            title={t('backlog.finalizeTitle')}
          >
            <Icon name="check" size={11} />
            {finalizing ? t('analysis.closing') : t('analysis.close')}
          </button>
        {/if}
      </div>
    {/if}
  </div>

  <!-- Painel de Controle de Execução e Status -->
  <div class="control-panel">
    <div class="spread control-top">
      <div class="tally">
        {#each counts as c (c.status)}
          <div class="count" class:accent={STATUS_META[c.status].accent}>
            <span class="n mono">{String(c.n).padStart(2, '0')}</span>
            <span class="label">{c.label}</span>
          </div>
        {/each}
      </div>

      <div class="runner-controls">
        <button
          type="button"
          class="btn btn-solid btn-sm"
          onclick={deployProduction}
          disabled={deployingEnv === 'production' ||
            (!productionDeploy && (isQueueRunning || (tasks.length > 0 && completedCount < tasks.length)))}
          title={productionDeploy
            ? t('backlog.prodInProgress')
            : completedCount < tasks.length
              ? t('backlog.prodLocked')
              : t('backlog.prodTrigger')}
        >
          {#if deployingEnv === 'production'}
            <span class="spinner-inline" aria-hidden="true"></span> {t('backlog.preparing')}
          {:else if productionDeploy}
            <span class="spinner-inline" aria-hidden="true"></span> {t('dashboard.deploy.BUILDING')}
            <span class="mono tabular">{deploys.elapsed(productionDeploy)}</span>
          {:else}
            <Icon name="upload" size={11} /> Deploy
          {/if}
        </button>

        {#if data.project.repo_url}
          <a
            class="btn btn-line btn-sm"
            href="{data.project.repo_url}/issues?labels=&state=all"
            target="_blank"
            rel="noopener noreferrer"
            title={t('backlog.issuesTitle')}
          >
            <Icon name="external" size={11} /> Issues
          </a>
          <button
            type="button"
            class="btn btn-line btn-sm"
            onclick={syncIssues}
            disabled={syncingIssues}
            title={t('backlog.syncTitle')}
          >
            {syncingIssues ? t('backlog.syncing') : t('backlog.sync')}
          </button>
        {/if}

        <span class="ctrl-sep" aria-hidden="true">|</span>

        <button
          type="button"
          class="btn {isQueueRunning ? 'btn-line active-pulse' : 'btn-line'} btn-sm"
          onclick={toggleRunAll}
          disabled={tasks.length === 0 || (completedCount === tasks.length && !isQueueRunning)}
          title={isQueueRunning ? t('backlog.pauseQueueTitle') : t('backlog.runAllTitle')}
        >
          {#if isQueueRunning}
            <Icon name="close" size={11} /> {t('backlog.pauseQueue')}
          {:else}
            <Icon name="play" size={11} /> {t('backlog.runAll')}
          {/if}
        </button>
      </div>
    </div>

    {#if issuesNote}
      <p class="issues-note mono" role="status">{issuesNote}</p>
    {/if}

    <!-- Barra de Ambientes Coolify -->
    <div class="env-bar spread">
      <div class="env-group">
        <span class="label mono">{t('backlog.environments')}:</span>

        <div class="env-item">
          <span class="env-name mono">{t('dashboard.test')}:</span>
          {#if envStatus?.test?.url}
            <a
              href={envStatus.test.url}
              target="_blank"
              rel="noopener noreferrer"
              class="env-url mono"
              title={t('backlog.openTestEnv')}
            >
              <span class="dot {envStatus.test.status === 'HEALTHY' ? 'dot-green' : 'dot-amber'}" aria-hidden="true"></span>
              {envStatus.test.url}
              <Icon name="external" size={9} />
            </a>
          {:else}
            <span class="env-url mono dim">{t('backlog.notProvisioned')}</span>
          {/if}
        </div>

        <span class="sep" aria-hidden="true">·</span>

        <div class="env-item">
          <span class="env-name mono">{t('deploys.env.production')}:</span>
          {#if envStatus?.production?.url}
            <a
              href={envStatus.production.url}
              target="_blank"
              rel="noopener noreferrer"
              class="env-url mono"
              title={t('backlog.openProdEnv')}
            >
              <span class="dot {envStatus.production.status === 'HEALTHY' ? 'dot-green' : 'dot-amber'}" aria-hidden="true"></span>
              {envStatus.production.url}
              <Icon name="external" size={9} />
            </a>
          {:else}
            <span class="env-url mono dim">{t('backlog.notProvisioned')}</span>
          {/if}
        </div>
      </div>

      {#if currentDeployment && !runningDeploy}
        <button
          type="button"
          class="btn btn-ghost btn-xs mono"
          onclick={() => showDeployment(currentDeployment.id)}
        >
          {t('backlog.lastDeploy')}
        </button>
      {/if}
    </div>

    {#if runningDeploy}
      {@const tail = lastLogLine(runningDeploy.logs)}
      <!-- Deploy em andamento: fica visível até o Coolify responder que terminou -->
      <div class="deploy-progress" role="status" aria-live="polite">
        <div class="deploy-progress-row">
          <span class="spinner-inline" aria-hidden="true"></span>
          <span class="mono deploy-progress-title">
            {runningDeploy.environment === 'test' ? t('dashboard.test') : t('deploys.env.production')} · {deployStage(runningDeploy.status)}
            <span class="faint">· {runningDeploy.branch}</span>
          </span>
          <span class="mono tabular deploy-progress-clock">{deploys.elapsed(runningDeploy)}</span>
          <button
            type="button"
            class="btn btn-ghost btn-xs mono"
            onclick={() => showDeployment(runningDeploy.id)}
          >
            {t('backlog.seeLog')}
          </button>
        </div>
        {#if tail}
          <p class="deploy-progress-tail mono faint" title={tail}>{tail}</p>
        {/if}
        <span class="indeterminate" aria-hidden="true"></span>
      </div>
    {/if}

    {#if queueMessage}
      <div class="queue-status-banner" class:running={isQueueRunning}>
        {#if isQueueRunning}
          <span class="spinner-inline" aria-hidden="true"></span>
        {:else}
          <Icon name="info" size={12} />
        {/if}
        <span class="mono">{queueMessage}</span>
      </div>
    {/if}
  </div>

  <!-- Lista de Tarefas em Ordem de Execução Sequencial -->
  <div class="list-tools">
    <span class="label mono">{tp('backlog.inOrder', ordered.length)}</span>
    <div class="list-tools-actions">
      <button type="button" class="btn-link label" onclick={() => setAll(true)}>{t('backlog.expandAll')}</button>
      <span class="sep" aria-hidden="true">·</span>
      <button type="button" class="btn-link label" onclick={() => setAll(false)}>{t('backlog.collapseAll')}</button>
    </div>
  </div>

  <ol class="list divide">
    {#each ordered as task, i (task.id)}
      {@const stuck = blockers(task)}
      {@const isRunning = dispatching === task.id || task.status === 'RUNNING'}
      {@const isAwaiting = task.status === 'AWAITING_ANALYST'}
      {@const isCompleted = task.status === 'COMPLETED'}
      {@const isMerging = merging === task.id || task.status === 'IN_REVIEW'}
      {@const hasError = dispatchError?.id === task.id || (task.status === 'FAILED' && !!(task.error || task.last_comment))}
      {@const open = isOpen(task)}
      <li
        class="task rise"
        class:is-running={isRunning}
        class:open
        class:completed={isCompleted}
        style="--i: {Math.min(i, 8)}"
      >
        <!-- Número de Ordem de Execução Sequencial -->
        <div class="step-col">
          <span class="step-num mono" class:done={isCompleted} title={t('backlog.orderTitle')}>
            {#if isCompleted}
              <Icon name="check" size={12} />
            {:else}
              #{String(i + 1).padStart(2, '0')}
            {/if}
          </span>
        </div>

        <div class="body">
          <button
            type="button"
            class="row-toggle"
            aria-expanded={open}
            aria-controls="task-detail-{task.id}"
            onclick={() => toggle(task)}
          >
            <span class="chev" class:rot={open} aria-hidden="true"><Icon name="arrow-right" size={11} /></span>
            <span class="title">{task.title}</span>
            <StatusTag status={task.status} size="sm" />
            {#if !open}
              <span class="row-hint mono">
                {#if isRunning}
                  <span class="spinner-inline" aria-hidden="true"></span> {t('backlog.hint.running')}
                {:else if isMerging}
                  {t('backlog.hint.merging')}
                {:else if hasError}
                  <Icon name="alert" size={10} /> {t('check.fail')}
                {:else if stuck.length}
                  {t('backlog.hint.waits', { steps: stuck.map((d) => stepLabel(d.id)).join(', ') })}
                {/if}
              </span>
            {/if}
          </button>

          {#if open}
            <div class="detail" id="task-detail-{task.id}">
              <p class="desc muted">{task.description}</p>

              <div class="facts mono">
                <span title={t('backlog.taskId')}>{task.id}</span>
                {#if task.issue_url}
                  <span class="sep" aria-hidden="true">·</span>
                  <a
                    href={task.issue_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    class="branch-link"
                    title={t('backlog.issueTitle')}
                  >
                    #{task.issue_number} <Icon name="external" size={9} />
                  </a>
                {/if}
                {#if task.assigned_branch}
                  <span class="sep" aria-hidden="true">·</span>
                  {#if data.project.repo_url}
                    <a
                      href="{data.project.repo_url}/src/branch/{task.assigned_branch}"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="branch-link"
                      title={t('backlog.branchTitle')}
                    >
                      {task.assigned_branch} <Icon name="external" size={9} />
                    </a>
                  {:else}
                    <span>{task.assigned_branch}</span>
                  {/if}
                {/if}
                {#if task.target_files.length}
                  <span class="sep" aria-hidden="true">·</span>
                  <span>{tp('backlog.files', task.target_files.length)}</span>
                {/if}
                {#if task.elapsed_seconds || task.input_tokens || task.output_tokens}
                  <span class="sep" aria-hidden="true">·</span>
                  <span title={t('backlog.taskTotalsTitle')}>
                    {formatDuration(task.elapsed_seconds ?? 0)} · {t('backlog.inOut', { input: formatTokens(task.input_tokens ?? 0), output: formatTokens(task.output_tokens ?? 0) })}
                  </span>
                {/if}
                {#if task.skip_tests}
                  <span class="sep" aria-hidden="true">·</span>
                  <span class="skip-tests" title={t('backlog.skipTestsTitle')}>{t('backlog.skipTests')}</span>
                {/if}
              </div>

              {#if task.target_files.length || task.acceptance_criteria.length}
                <details>
                  <summary class="label">{t('backlog.criteriaFiles')}</summary>
                  <div class="detail-grid">
                    {#if task.acceptance_criteria.length}
                      <div>
                        <span class="label">{t('backlog.criteria')}</span>
                        <ul class="bullets">
                          {#each task.acceptance_criteria as c, ci (ci)}
                            <li>{c}</li>
                          {/each}
                        </ul>
                      </div>
                    {/if}
                    {#if task.target_files.length}
                      <div>
                        <span class="label">{t('backlog.targetFiles')}</span>
                        <ul class="bullets mono files">
                          {#each task.target_files as f (f)}
                            <li>{f}</li>
                          {/each}
                        </ul>
                      </div>
                    {/if}
                  </div>
                </details>
              {/if}

              {#if stuck.length > 0}
                <p class="blocked-note">
                  {t('backlog.blockedBy')}
                  {#each stuck as d, di (d.id)}
                    <span class="mono bold">{stepLabel(d.id)} {d.title}</span>{#if di < stuck.length - 1}, {/if}
                  {/each}
                  {t('backlog.blockedTail')}
                </p>
              {/if}

              {#if isAwaiting && !isRunning}
                <div class="clar">
                  <ClarificationPanel {task} onresolved={replace} />
                </div>
              {/if}
            </div>
          {/if}

          <!-- Montado mesmo recolhido: o stream precisa seguir vivo para o
               onclosed recarregar a lista quando o contêiner termina. -->
          {#if isRunning}
            <div class="activity" hidden={!open}>
              <!-- Quem disparou recebe o resultado pela própria requisição; quem só
                   abriu a página recarrega quando o stream encerra. -->
              <TaskActivity
                taskId={task.id}
                starting={dispatching === task.id}
                onclosed={() => {
                  if (dispatching !== task.id) load();
                }}
              />
            </div>
          {/if}

          {#if open}
            {#if isMerging}
              <div class="merging-banner">
                <span class="spinner-inline" aria-hidden="true"></span>
                <span>{t('backlog.mergingBanner', { branch: data.project.default_branch || 'main' })}</span>
              </div>
            {/if}

            {#if dispatchError?.id === task.id || (task.status === 'FAILED' && (task.error || task.last_comment))}
              {@const full = dispatchError?.id === task.id ? dispatchError.message : (task.error || task.last_comment || '')}
              {@const err = splitError(full)}
              <div class="error-box" role="alert">
                <p class="error-head">
                  <Icon name="alert" size={12} />
                  <span>{err.head}</span>
                </p>
                {#if err.rest}
                  <details class="error-more">
                    <summary class="label">
                      {err.huge ? t('backlog.rawLog') : t('backlog.details')}
                    </summary>
                    <pre class="error-pre mono">{err.rest}</pre>
                  </details>
                {/if}
              </div>
            {:else if isCompleted && task.last_comment}
              <p class="completed-note mono faint">
                {task.last_comment}
              </p>
            {/if}
          {/if}
        </div>

        <div class="side">
          {#if isCompleted}
            {#if branchesAlive}
            {@const taskDeploy = deploys.activeForTask(task.id)}
            <button
              type="button"
              class="btn btn-line btn-xs test-task-btn"
              onclick={() => deployTest(task.id)}
              disabled={deployingTaskId === task.id || (isQueueRunning && !taskDeploy)}
              title={taskDeploy
                ? t('backlog.testInProgress')
                : t('backlog.testTitle')}
            >
              {#if deployingTaskId === task.id}
                <span class="spinner-inline" aria-hidden="true"></span> {t('backlog.preparing')}
              {:else if taskDeploy}
                <span class="spinner-inline" aria-hidden="true"></span> {t('dashboard.deploy.BUILDING')}
                <span class="mono tabular">{deploys.elapsed(taskDeploy)}</span>
              {:else}
                <Icon name="play" size={10} /> {t('backlog.test')}
              {/if}
            </button>
            {/if}
          {:else if isMerging}
            <span class="completed-tag label mono">
              <span class="spinner-inline" aria-hidden="true"></span> {t('backlog.merging')}
            </span>
          {:else if isRunning}
            <button
              type="button"
              class="btn btn-line btn-sm danger"
              onclick={() => stopTask(task.id)}
              disabled={stoppingTaskId === task.id}
              title={t('backlog.stopTitle')}
            >
              <Icon name="square" size={10} />
              <span>{stoppingTaskId === task.id ? t('activity.stopping') : t('activity.stop')}</span>
            </button>
            {#if !task.skip_tests}
              <button
                type="button"
                class="btn btn-line btn-sm"
                onclick={() => abbreviateTests(task)}
                disabled={abbreviatingTaskId === task.id || stoppingTaskId === task.id}
                title={t('backlog.abbreviateTitle')}
              >
                <span>{abbreviatingTaskId === task.id ? t('backlog.abbreviating') : t('backlog.abbreviate')}</span>
              </button>
            {/if}
          {:else}
            <button
              type="button"
              class="btn btn-line btn-sm"
              onclick={() => dispatch(task)}
              disabled={!canDispatch(task)}
              title={stuck.length ? t('backlog.waitingDeps') : t('backlog.runOne')}
            >
              {#if task.status === 'FAILED'}
                <Icon name="play" size={11} /> {t('backlog.retry')}
              {:else}
                <Icon name="play" size={11} /> {t('backlog.run')}
              {/if}
            </button>
          {/if}
        </div>
      </li>
    {/each}
  </ol>
{/if}

<!-- Modal de Diff -->
<Modal bind:open={diffOpen} title={t('backlog.diffTitle')}>
  {#snippet body()}
    {#if diffLoading}
      <Skeleton variant="lines" rows={8} />
    {:else if diffData}
      <div class="diff-container">
        <div class="diff-meta spread mono faint">
          <span>{t('deploys.branch', { branch: `${diffData.branch} → ${diffData.base_branch}` })}</span>
          {#if diffData.gitea_url}
            <a href={diffData.gitea_url} target="_blank" rel="noopener noreferrer" class="link-ext">
              {t('backlog.openInRepo')} <Icon name="external" size={10} />
            </a>
          {/if}
        </div>
        <pre class="diff-code mono">{diffData.diff || t('backlog.noChanges')}</pre>
      </div>
    {/if}
  {/snippet}
  {#snippet footer()}
    <div class="spread modal-foot">
      <div></div>
      <button type="button" class="btn btn-line btn-sm" onclick={() => (diffOpen = false)}>
        {t('common.close')}
      </button>
    </div>
  {/snippet}
</Modal>

<!-- Modal de Deploy Coolify -->
<Modal bind:open={deploymentModalOpen} title={t('backlog.deployModal')}>
  {#snippet body()}
    {#if currentDeployment}
      <div class="deploy-modal-content">
        <div class="spread mono faint deploy-meta">
          <span>{t('backlog.environment')}: <strong class="upper">{currentDeployment.environment === 'test' ? t('dashboard.test') : t('deploys.env.production')}</strong></span>
          <span>Branch: <strong>{currentDeployment.branch}</strong></span>
        </div>

        <div class="deploy-status-box mono" class:hatch={currentDeployment.status === 'FAILED'}>
          <div class="spread">
            <span class="deploy-stage">
              {#if isDeployActive(currentDeployment)}
                <span class="spinner-inline" aria-hidden="true"></span>
              {/if}
              <strong>{deployStage(currentDeployment.status)}</strong>
              <span class="faint tabular">{deploys.elapsed(currentDeployment)}</span>
            </span>
            {#if currentDeployment.url && currentDeployment.status === 'HEALTHY'}
              <a href={currentDeployment.url} target="_blank" rel="noopener noreferrer" class="link-ext bold">
                {t('deploys.openApp')} <Icon name="external" size={10} />
              </a>
            {/if}
          </div>
          {#if isDeployActive(currentDeployment)}
            <p class="faint deploy-hint">{t('backlog.deployHint')}</p>
          {/if}
          {#if currentDeployment.url}
            <div class="deploy-url-line">
              <span class="muted">URL:</span>
              <a href={currentDeployment.url} target="_blank" rel="noopener noreferrer" class="app-url">
                {currentDeployment.url}
              </a>
            </div>
          {/if}
        </div>

        {#if currentDeployment.logs}
          <div class="deploy-logs">
            <span class="label mono">{t('backlog.deployLogs')}</span>
            <pre class="log-pre mono" bind:this={logBox}>{currentDeployment.logs}</pre>
          </div>
        {/if}
      </div>
    {:else}
      <p class="muted">{t('backlog.noDeploy')}</p>
    {/if}
  {/snippet}
  {#snippet footer()}
    <div class="spread modal-foot">
      <div></div>
      <button type="button" class="btn btn-line btn-sm" onclick={() => (deploymentModalOpen = false)}>
        {t('common.close')}
      </button>
    </div>
  {/snippet}
</Modal>

<style>
  .pad {
    padding-top: var(--s6);
  }

  .created {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    margin-top: var(--s5);
    padding: var(--s2) var(--s3);
    border: 1px solid var(--rule-2);
    color: var(--ink);
  }

  .migration-banner {
    align-items: center;
    padding: var(--s3) var(--s4);
    background: var(--paper-2);
    border: 1px solid var(--rule-2);
    margin-top: var(--s5);
  }

  /* Barra de Progresso */
  .progress-bar-card {
    margin-top: var(--s5);
    padding: var(--s4);
    background: var(--paper-2);
    border: 1px solid var(--rule-2);
  }

  .progress-meta {
    font-size: var(--t-small);
    margin-bottom: var(--s2);
  }

  .meta-left {
    display: flex;
    align-items: center;
    gap: var(--s2);
  }

  .session-badge {
    color: var(--ink);
  }

  .progress-track {
    height: 6px;
    background: var(--rule-2);
    overflow: hidden;
  }

  .session-close {
    align-items: center;
    gap: var(--s3);
    flex-wrap: wrap;
    margin-top: var(--s4);
    padding-top: var(--s3);
    border-top: 1px solid var(--rule-2);
    font-size: var(--t-small);
    color: var(--ink-2);
  }

  .progress-fill {
    height: 100%;
    background: var(--progress);
    transition: width 0.3s ease-out;
  }

  /* Painel de Controle de Execução */
  .control-panel {
    margin-top: var(--s4);
    border-bottom: 1px solid var(--rule-ink);
    padding-bottom: var(--s4);
  }

  .control-top {
    align-items: flex-end;
    gap: var(--s4);
    flex-wrap: wrap;
  }

  .tally {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s6);
    padding: var(--s3) 0;
  }

  .count {
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
  }

  .n {
    font-size: 1.375rem;
    font-weight: 500;
    line-height: 1;
    letter-spacing: -0.03em;
  }

  .count.accent .n,
  .count.accent :global(.label) {
    color: var(--accent);
  }

  .runner-controls {
    display: flex;
    align-items: center;
    gap: var(--s3);
    padding-bottom: var(--s2);
    flex-wrap: wrap;
  }

  .ctrl-sep {
    color: var(--rule-ink);
    margin: 0 var(--s1);
  }

  /* Barra de Ambientes */
  .env-bar {
    align-items: center;
    margin-top: var(--s3);
    padding: var(--s2) var(--s3);
    background: var(--paper-sunk);
    border: 1px solid var(--rule-2);
    font-size: var(--t-small);
    flex-wrap: wrap;
    gap: var(--s3);
  }

  .env-group {
    display: flex;
    align-items: center;
    gap: var(--s3);
    flex-wrap: wrap;
  }

  .env-item {
    display: flex;
    align-items: center;
    gap: var(--s2);
  }

  .env-name {
    color: var(--ink-3);
  }

  .env-url {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    color: var(--ink);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .env-url.dim {
    color: var(--ink-4);
    text-decoration: none;
  }

  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    display: inline-block;
  }

  .dot-green {
    background: #10b981;
  }

  .dot-amber {
    background: #f59e0b;
  }

  .btn-ghost {
    background: transparent;
    border: none;
    cursor: pointer;
    color: var(--ink-2);
    text-decoration: underline;
  }

  .test-task-btn {
    font-size: var(--t-micro);
  }

  /* Modal de Deploy */
  .deploy-modal-content {
    display: flex;
    flex-direction: column;
    gap: var(--s4);
  }

  .deploy-meta {
    font-size: var(--t-small);
  }

  .upper {
    text-transform: uppercase;
  }

  .deploy-status-box {
    padding: var(--s3) var(--s4);
    background: var(--paper-sunk);
    border: 1px solid var(--rule-2);
    display: flex;
    flex-direction: column;
    gap: var(--s2);
  }

  .deploy-stage {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
  }

  .deploy-hint {
    font-size: var(--t-micro);
    margin: 0;
  }

  .tabular {
    font-variant-numeric: tabular-nums;
  }

  /* Faixa de deploy em andamento, sob a barra de ambientes */
  .deploy-progress {
    position: relative;
    margin-top: var(--s3);
    padding: var(--s2) var(--s4) calc(var(--s2) + 2px);
    border: 1px solid var(--rule-2);
    background: var(--paper-sunk);
    overflow: hidden;
  }

  .deploy-progress-row {
    display: flex;
    align-items: center;
    gap: var(--s3);
  }

  .deploy-progress-title {
    font-size: var(--t-small);
    flex: 1;
    min-width: 0;
  }

  .deploy-progress-clock {
    font-size: var(--t-small);
    color: var(--ink-2);
  }

  .deploy-progress-tail {
    margin: var(--s1) 0 0;
    padding-left: calc(12px + var(--s3));
    font-size: var(--t-micro);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* Barra indeterminada: o Coolify não informa porcentagem de progresso */
  .indeterminate {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent 0%, var(--ink) 50%, transparent 100%) 0 0 / 40% 100%
      no-repeat;
    animation: sweep 1.6s var(--ease) infinite;
  }

  @keyframes sweep {
    from {
      background-position: -60% 0;
    }
    to {
      background-position: 160% 0;
    }
  }

  .deploy-url-line {
    display: flex;
    align-items: center;
    gap: var(--s2);
    word-break: break-all;
  }

  .app-url {
    color: var(--ink);
    text-decoration: underline;
    font-weight: 500;
  }

  .deploy-logs {
    display: flex;
    flex-direction: column;
    gap: var(--s2);
  }

  .log-pre {
    max-height: 20rem;
    overflow: auto;
    font-size: var(--t-micro);
    background: var(--paper-sunk);
    padding: var(--s3);
    border: 1px solid var(--rule);
    white-space: pre-wrap;
    word-break: break-all;
  }

  .active-pulse {
    border-color: var(--accent);
    color: var(--accent);
    animation: pulse-border 1.5s infinite ease-in-out;
  }

  @keyframes pulse-border {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
  }

  .queue-status-banner {
    display: flex;
    align-items: center;
    gap: var(--s3);
    margin-top: var(--s3);
    padding: var(--s3) var(--s4);
    background: var(--paper-sunk);
    border-left: 3px solid var(--rule-2);
    font-size: var(--t-small);
    color: var(--ink-2);
  }

  .queue-status-banner.running {
    border-left-color: var(--accent);
    color: var(--ink);
  }

  .spinner-inline {
    width: 12px;
    height: 12px;
    border: 2px solid var(--rule-2);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* Lista de Tarefas e Conectores Sequenciais */
  .list {
    border-bottom: 1px solid var(--rule);
    padding: 0;
    list-style: none;
  }

  .list-tools {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s3);
    margin-top: var(--s5);
    padding-bottom: var(--s2);
    border-bottom: 1px solid var(--rule);
    color: var(--ink-3);
  }

  .list-tools-actions {
    display: flex;
    align-items: center;
  }

  .btn-link {
    background: none;
    border: 0;
    padding: 0;
    cursor: pointer;
    color: var(--ink-2);
  }

  .btn-link:hover {
    color: var(--ink);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .task {
    display: grid;
    grid-template-columns: 2.75rem 1fr auto;
    gap: var(--s4);
    align-items: start;
    padding: var(--s3) 0;
    position: relative;
    transition: background-color 0.2s ease;
  }

  .task.open {
    padding: var(--s4) 0 var(--s5);
  }

  .task.is-running {
    background: var(--paper-sunk);
    box-shadow: inset 2px 0 0 var(--ink);
    margin-inline: -1rem;
    padding-inline: 1rem;
  }

  .step-col {
    display: flex;
    justify-content: center;
  }

  .step-num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: var(--t-micro);
    width: 1.85rem;
    height: 1.85rem;
    border: 1px solid var(--rule-2);
    background: var(--paper);
    color: var(--ink-3);
    font-weight: 500;
  }

  .step-num.done {
    background: var(--paper-2);
    color: var(--ink);
    border-color: var(--rule-ink);
  }

  .row-toggle {
    display: flex;
    align-items: center;
    gap: var(--s3);
    width: 100%;
    min-height: 1.85rem;
    padding: 0;
    background: none;
    border: 0;
    text-align: left;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }

  .row-toggle:hover .title {
    text-decoration: underline;
    text-underline-offset: 3px;
    text-decoration-thickness: 1px;
  }

  .row-toggle:focus-visible {
    outline: 1px solid var(--ink);
    outline-offset: 2px;
  }

  .chev {
    display: inline-flex;
    flex: none;
    color: var(--ink-3);
    transition: transform 0.15s ease;
  }

  .chev.rot {
    transform: rotate(90deg);
  }

  .title {
    font-weight: 500;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .task.open .title {
    white-space: normal;
  }

  .task.completed:not(.open) .title {
    color: var(--ink-3);
  }

  .row-hint {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    margin-left: auto;
    padding-left: var(--s3);
    flex: none;
    font-size: var(--t-micro);
    color: var(--ink-3);
  }

  .detail,
  .activity {
    padding-left: calc(11px + var(--s3));
  }

  .body {
    min-width: 0;
  }

  .desc {
    margin-top: var(--s2);
    font-size: var(--t-small);
    max-width: var(--measure);
  }

  .facts {
    margin-top: var(--s3);
    font-size: var(--t-micro);
    color: var(--ink-3);
  }

  .sep {
    margin-inline: 0.375rem;
  }

  details {
    margin-top: var(--s3);
  }

  summary {
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    color: var(--ink-2);
    list-style: none;
  }

  summary::-webkit-details-marker {
    display: none;
  }

  summary::before {
    content: '+';
    font-family: var(--font-mono);
    color: var(--ink-3);
  }

  details[open] summary::before {
    content: '−';
  }

  summary:hover {
    color: var(--ink);
  }

  .detail-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--s5);
    margin-top: var(--s3);
    padding: var(--s4);
    background: var(--paper-sunk);
  }

  .bullets {
    margin-top: var(--s2);
    display: flex;
    flex-direction: column;
    gap: var(--s1);
    font-size: var(--t-small);
    color: var(--ink-2);
  }

  .bullets li {
    padding-left: var(--s4);
    position: relative;
  }

  .bullets li::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0.5rem;
    width: 6px;
    height: 1px;
    background: var(--ink-4);
  }

  .files li {
    font-size: var(--t-micro);
    overflow-wrap: anywhere;
  }

  .blocked-note {
    margin-top: var(--s3);
    padding-left: var(--s3);
    border-left: 2px solid var(--rule-2);
    font-size: var(--t-small);
    color: var(--ink-2);
    max-width: var(--measure);
  }

  .clar {
    margin-top: var(--s4);
    max-width: 44rem;
  }

  .merging-banner {
    display: flex;
    align-items: center;
    gap: var(--s3);
    margin-top: var(--s4);
    padding: var(--s3) var(--s4);
    background: var(--paper-2);
    border-left: 2px solid var(--accent);
    font-size: var(--t-small);
    color: var(--ink);
    max-width: 44rem;
  }

  .review-banner {
    margin-top: var(--s4);
    padding: var(--s3) var(--s4);
    background: var(--paper-2);
    border: 1px solid var(--rule-2);
    border-left: 3px solid var(--ink);
    max-width: 44rem;
  }

  .review-info {
    display: flex;
    align-items: flex-start;
    gap: var(--s2);
  }

  .check-icon {
    display: inline-flex;
    margin-top: 0.15rem;
    color: var(--ink);
  }

  .review-text {
    font-size: var(--t-small);
    line-height: 1.45;
    color: var(--ink-2);
  }

  .review-text strong {
    color: var(--ink);
  }

  .review-text code {
    font-family: var(--font-mono);
    font-size: var(--t-micro);
    background: var(--paper-sunk);
    padding: 0.1rem 0.3rem;
  }

  .completed-note {
    margin-top: var(--s2);
    font-size: var(--t-micro);
    color: var(--ink-3);
  }

  .error-box {
    margin-top: var(--s3);
    max-width: 44rem;
    padding: var(--s3) var(--s4);
    border-left: 2px solid var(--ink);
    background: repeating-linear-gradient(
      -45deg,
      var(--paper-sunk) 0 6px,
      var(--paper) 6px 12px
    );
  }

  .error-head {
    display: flex;
    align-items: flex-start;
    gap: var(--s2);
    font-size: var(--t-small);
    color: var(--ink);
    white-space: pre-line;
    overflow-wrap: anywhere;
  }

  .error-head :global(svg) {
    flex: none;
    margin-top: 0.2rem;
  }

  .error-more {
    margin-top: var(--s2);
  }

  .error-pre {
    margin-top: var(--s2);
    max-height: 16rem;
    overflow: auto;
    padding: var(--s3);
    background: var(--paper);
    border: 1px solid var(--rule);
    font-size: var(--t-micro);
    color: var(--ink-2);
    white-space: pre-wrap;
    word-break: break-all;
  }

  .side {
    padding-top: 0.1rem;
    display: flex;
    flex-direction: column;
    gap: var(--s2);
    align-items: flex-end;
  }

  /* Peso, não cor: o acento é reservado ao agente parado à espera do analista. */
  .skip-tests {
    font-weight: 600;
    color: var(--ink);
  }

  .btn-group {
    display: flex;
    align-items: center;
    gap: var(--s2);
  }

  .completed-tag {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    color: var(--ink-3);
    font-size: var(--t-micro);
    padding: var(--s1) var(--s2);
    border: 1px solid var(--rule);
  }

  .branch-link {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    color: var(--ink-2);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .issues-note {
    margin: 0;
    padding: var(--s2) var(--s4);
    border-top: 1px solid var(--rule);
    font-size: var(--t-micro);
    color: var(--ink-2);
  }

  .branch-link:hover {
    color: var(--ink);
  }

  /* Modal de Diff */
  .diff-container {
    display: flex;
    flex-direction: column;
    gap: var(--s3);
  }

  .diff-meta {
    font-size: var(--t-small);
  }

  .link-ext {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    color: var(--ink);
    text-decoration: underline;
  }

  .diff-code {
    max-height: 28rem;
    overflow: auto;
    font-size: var(--t-micro);
    background: var(--paper-sunk);
    padding: var(--s4);
    border: 1px solid var(--rule);
    white-space: pre-wrap;
    word-break: break-all;
  }

  .modal-foot {
    width: 100%;
  }

  @media (max-width: 760px) {
    .task {
      grid-template-columns: 2rem 1fr;
    }

    .side {
      grid-column: 2;
      align-items: flex-start;
    }

    .detail-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
