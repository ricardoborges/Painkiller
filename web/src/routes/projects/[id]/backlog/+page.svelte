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
  import TaskChanges from '$lib/components/TaskChanges.svelte';
  import ClarificationPanel from '$lib/components/ClarificationPanel.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import AddTaskDialog from '$lib/components/AddTaskDialog.svelte';
  import ApkControls from '$lib/components/ApkControls.svelte';
  import { testDevice } from '$lib/stores/testDevice.svelte';
  import AppPreview from '$lib/components/AppPreview.svelte';
  import { getProjectSessionStore } from '$lib/stores/session.svelte';
  import DeployTerminal from '$lib/components/DeployTerminal.svelte';
  import { deploys, isDeployActive, deployStage, lastLogLine } from '$lib/stores/deploys.svelte';
  import { formatDuration, formatTokens, taskTotals } from '$lib/metrics';
  import { onDestroy, tick } from 'svelte';

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
  let addTaskOpen = $state(false);

  // Execução individual
  let dispatching = $state<string | null>(null);
  let dispatchError = $state<{ id: string; message: string } | null>(null);
  let merging = $state<string | null>(null);
  let stoppingTaskId = $state<string | null>(null);
  let togglingSuperpowers = $state(false);

  // Fila sequencial (Executar Todas)
  let isQueueRunning = $state(false);
  let queueMessage = $state<string | null>(null);

  // Deploys (Coolify)
  let envStatus = $state<EnvironmentStatusResponse | null>(null);
  let deployingEnv = $state<'test' | null>(null);
  let deletingTaskId = $state<string | null>(null);
  /** O ambiente de teste abre num celular simulado, em modal. */
  function openDevice() {
    testDevice.show(envStatus?.test.url ?? currentDeployment?.url ?? data.project.test_url);
  }
  let deploymentModalOpen = $state(false);
  let fixingDeploy = $state(false);
  // O registro vive no rastreador (que consulta o Coolify até terminar); aqui
  // só se guarda qual deploy o modal mostra.
  let shownDeploymentId = $state<string | null>(null);
  const currentDeployment = $derived<DeploymentRecord | null>(
    (shownDeploymentId && deploys.records[shownDeploymentId]) || deploys.latest(data.project.id)
  );
  const runningDeploy = $derived(deploys.active(data.project.id));
  const testDeploy = $derived(deploys.active(data.project.id, 'test'));

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

  // Prévia do app ao lado das tarefas: cada tarefa concluída a relê. Ocultá-la
  // vale para todos os projetos, como o tema.
  const PREVIEW_HIDDEN_KEY = 'pk_preview_hidden';
  let previewCollapsed = $state(localStorage.getItem(PREVIEW_HIDDEN_KEY) === '1');
  $effect(() => {
    localStorage.setItem(PREVIEW_HIDDEN_KEY, previewCollapsed ? '1' : '0');
  });

  const counts = $derived.by(() => {
    const map = new Map<string, number>();
    for (const t of tasks) map.set(t.status, (map.get(t.status) ?? 0) + 1);
    return STATUS_ORDER.filter((s) => map.has(s)).map((s) => ({
      status: s,
      label: STATUS_META[s].label,
      n: map.get(s)!
    }));
  });

  // Posição de cada tarefa na fila: o número do card não muda com o filtro.
  const orderIndex = $derived(new Map(ordered.map((t, i) => [t.id, i])));

  let filter = $state<'ALL' | Task['status']>('ALL');
  const visible = $derived(filter === 'ALL' ? ordered : ordered.filter((t) => t.status === filter));

  // O filtro de um estado que esvaziou volta para "Todas".
  $effect(() => {
    if (filter !== 'ALL' && !tasks.some((t) => t.status === filter)) filter = 'ALL';
  });

  // O que depende do analista, e pode estar fora da tela.
  const awaiting = $derived(ordered.filter((t) => t.status === 'AWAITING_ANALYST'));
  const failed = $derived(ordered.filter((t) => t.status === 'FAILED'));

  /** Abre o card e rola até ele, limpando o filtro se ele o esconderia. */
  async function reveal(id: string) {
    const task = byId.get(id);
    if (task && filter !== 'ALL' && task.status !== filter) filter = 'ALL';
    expandOverride[id] = true;
    await tick();
    document.getElementById(`task-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // Descrição longa: durante a execução o que importa é o log, então ela fica
  // em poucas linhas até o analista pedir o resto.
  let descOpen = $state<Record<string, boolean>>({});

  let menuOpen = $state(false);

  /* Menu sem biblioteca: fecha no clique fora e no Esc, como na análise. */
  $effect(() => {
    if (!menuOpen) return;
    const away = (e: MouseEvent) => {
      if (!(e.target as HTMLElement)?.closest('.menu')) menuOpen = false;
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') menuOpen = false;
    };
    window.addEventListener('click', away, true);
    window.addEventListener('keydown', esc);
    return () => {
      window.removeEventListener('click', away, true);
      window.removeEventListener('keydown', esc);
    };
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

  // O layout do projeto pergunta guiada/direta, cria e leva ao Chat.
  function startNextSession() {
    sessionStore.requestNextSession();
  }

  /* Tarefa escrita à mão: entra no fim da fila. Se a sessão ainda estava em
     PLANNING o backend a passou para BACKLOG, então o passo da análise muda. */
  async function onTaskCreated(task: Task) {
    queueMessage = null;
    if (activeSession?.status === 'PLANNING') {
      await sessionStore.loadSessions(activeSession.id);
    }
    await load();
    await reveal(task.id);
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

  /**
   * Deploy falhou: vira uma tarefa (na sessão aberta, ou numa nova se todas
   * estão encerradas) com o log, e o agente começa já. O card fica à vista.
   */
  async function fixWithAgent(record: DeploymentRecord) {
    fixingDeploy = true;
    try {
      const task = await api.createDeployFixTask(record.id);
      deploymentModalOpen = false;
      await sessionStore.loadSessions(task.session_id ?? undefined);
      await load();
      const current = byId.get(task.id) ?? task;
      if (current.status === 'BACKLOG' || current.status === 'READY' || current.status === 'FAILED') {
        void dispatch(current);
      }
      await reveal(task.id);
    } catch (e) {
      alert(e instanceof Error ? e.message : t('backlog.fixWithAgentFailed'));
    } finally {
      fixingDeploy = false;
    }
  }

  function showDeployment(id: string) {
    shownDeploymentId = id;
    deploymentModalOpen = true;
    void deploys.refresh(id);
  }

  // Deploy encerrado: as URLs e os pontos de status da barra de ambientes mudam.
  $effect(() => {
    if (deploys.settled) loadEnvStatus();
  });

  /**
   * Um só "Testar" para o backlog: sem tarefa indicada, o backend publica a
   * branch da última concluída da sessão — que já traz as anteriores, porque
   * cada tarefa nasce da branch padrão depois do merge das outras.
   */
  async function deployTest() {
    if (testDeploy) {
      showDeployment(testDeploy.id);
      return;
    }
    deployingEnv = 'test';
    try {
      const record = await api.triggerDeploy(
        data.project.id,
        'test',
        undefined,
        activeSession?.id
      );
      deploys.track(record);
      showDeployment(record.id);
      if (data.project.has_backend) void deployBackendTest();
      await loadEnvStatus();
    } catch (e) {
      alert(e instanceof Error ? e.message : t('backlog.deployTestFailed'));
    } finally {
      deployingEnv = null;
    }
  }

  /* O backend vai junto, como aplicação própria no Coolify; o modal segue o app,
     e o fim do backend chega como toast. */
  async function deployBackendTest() {
    if (deploys.active(data.project.id, 'test', 'backend')) return;
    try {
      deploys.track(
        await api.triggerDeploy(data.project.id, 'test', undefined, activeSession?.id, 'backend')
      );
    } catch (e) {
      alert(e instanceof Error ? e.message : t('backlog.deployTestFailed'));
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
    // A requisição só volta no fim da execução: até lá a lista ainda diria
    // FAILED e mostraria o erro da tentativa anterior.
    replace({ ...task, status: 'RUNNING', error: null });

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

  /* Superpowers vale para a próxima execução: só tarefas que ainda vão rodar
     podem mudar. O agente é one-shot, então mudar no meio não o alcançaria. */
  function superpowersEditable(task: Task): boolean {
    return (
      dispatching !== task.id &&
      task.status !== 'RUNNING' &&
      task.status !== 'COMPLETED' &&
      task.status !== 'IN_REVIEW'
    );
  }

  const superpowersPending = $derived(tasks.filter(superpowersEditable));
  const superpowersOn = $derived(superpowersPending.filter((t) => t.use_superpowers !== false).length);

  async function setSuperpowers(targets: Task[], enabled: boolean) {
    if (togglingSuperpowers) return;
    togglingSuperpowers = true;
    try {
      for (const task of targets) {
        if ((task.use_superpowers !== false) === enabled) continue;
        replace(await api.setTaskSuperpowers(task.id, enabled));
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : t('backlog.superpowersFailed');
      dispatchError = { id: targets[0]?.id ?? '', message: msg };
      await load();
    } finally {
      togglingSuperpowers = false;
    }
  }

  /** Só as tarefas escritas à mão; o backend recusa as do backlog importado. */
  async function deleteTask(task: Task) {
    if (!confirm(t('backlog.confirmDelete', { title: task.title }))) return;
    deletingTaskId = task.id;
    try {
      await api.deleteTask(task.id);
      delete expandOverride[task.id];
      await load();
    } catch (e) {
      alert(e instanceof Error ? e.message : t('backlog.deleteFailed'));
    } finally {
      deletingTaskId = null;
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
        // A fila avança sozinha: leva o leitor até a tarefa que começou.
        const started = dispatch(candidate);
        void reveal(candidate.id);
        const updated = await started;

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

<div class="workspace" class:collapsed={previewCollapsed}>
<div class="work">
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
      {#if !sessionClosed}
        <button type="button" class="btn btn-line" onclick={() => (addTaskOpen = true)}>
          <Icon name="plus" size={11} /> {t('backlog.addTask')}
        </button>
      {/if}
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

  <!-- Barra da sessão: progresso, a ação que avança a etapa e o resto num
       menu. Fica presa no topo para que pausar a fila não exija rolar. -->
  <div class="runbar">
    <div class="runbar-main">
      <span class="session-badge mono bold">
        {activeSession ? `#${activeSession.number} ${activeSession.title}` : t('backlog.activeSession')}
      </span>

      <div class="progress" title={t('backlog.progress', { done: completedCount, total: tasks.length })}>
        <span class="mono tabular">{completedCount}/{tasks.length}</span>
        <div class="progress-track" aria-hidden="true">
          <div class="progress-fill" style:width="{progressPercent}%"></div>
        </div>
        <span class="mono tabular bold">{progressPercent}%</span>
      </div>

      <span
        class="totals label mono"
        title={t('backlog.sessionTotalsTitle', { input: formatNumber(sessionTotals.input), output: formatNumber(sessionTotals.output) })}
      >
        {formatDuration(sessionTotals.seconds)} · {t('backlog.inOut', { input: formatTokens(sessionTotals.input), output: formatTokens(sessionTotals.output) })}
      </span>

      <div class="runbar-actions">
        <!-- Um só botão sólido: o que leva a etapa adiante agora. -->
        {#if activeSession && sessionClosed}
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
        {:else if activeSession && allDone && branchesAlive}
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
        {:else}
          {#if superpowersPending.length}
            <label class="sp-toggle label" title={t('backlog.superpowersAllTitle')}>
              <input
                type="checkbox"
                checked={superpowersOn === superpowersPending.length}
                indeterminate={superpowersOn > 0 && superpowersOn < superpowersPending.length}
                disabled={togglingSuperpowers || isQueueRunning || !!dispatching}
                onchange={(e) => setSuperpowers(superpowersPending, e.currentTarget.checked)}
              />
              <span>{t('backlog.superpowers')}</span>
            </label>
          {/if}
          <button
            type="button"
            class="btn {isQueueRunning ? 'btn-line' : 'btn-solid'} btn-sm"
            onclick={toggleRunAll}
            disabled={tasks.length === 0 || (allDone && !isQueueRunning)}
            title={isQueueRunning ? t('backlog.pauseQueueTitle') : t('backlog.runAllTitle')}
          >
            {#if isQueueRunning}
              <Icon name="square" size={10} /> {t('backlog.pauseQueue')}
            {:else}
              <Icon name="play" size={11} /> {t('backlog.runAll')}
            {/if}
          </button>
        {/if}

        {#if completedCount > 0}
          <ApkControls projectId={data.project.id} />
        {/if}

        {#if branchesAlive && completedCount > 0}
          <button
            type="button"
            class="btn btn-line btn-sm"
            onclick={deployTest}
            disabled={deployingEnv === 'test' || (isQueueRunning && !testDeploy)}
            title={testDeploy ? t('backlog.testInProgress') : t('backlog.testTitle')}
          >
            {#if deployingEnv === 'test'}
              <span class="spinner-inline" aria-hidden="true"></span> {t('backlog.preparing')}
            {:else if testDeploy}
              <span class="spinner-inline" aria-hidden="true"></span> {t('dashboard.deploy.BUILDING')}
              <span class="mono tabular">{deploys.elapsed(testDeploy)}</span>
            {:else}
              <Icon name="flask" size={11} /> {t('backlog.test')}
            {/if}
          </button>
        {/if}

        <div class="menu">
          <button
            type="button"
            class="btn btn-line btn-sm more"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onclick={() => (menuOpen = !menuOpen)}
            title={t('analysis.moreActions')}
          >
            <span aria-hidden="true">···</span>
            <span class="sr">{t('analysis.moreActions')}</span>
          </button>
          {#if menuOpen}
            <div class="sheet" role="menu">
              {#each [{ name: t('dashboard.test'), env: envStatus?.test }] as e (e.name)}
                {#if e.env?.url}
                  <button
                    type="button"
                    role="menuitem"
                    onclick={() => {
                      menuOpen = false;
                      openDevice();
                    }}
                    title={t('testDevice.openTitle')}
                  >
                    <Icon name="phone" size={12} />
                    <span class="env-text">
                      <span>{e.name}{#if e.env.status && e.env.status !== 'HEALTHY'}<span class="faint"> · {deployStage(e.env.status)}</span>{/if}</span>
                      <span class="mono faint env-url">{e.env.url}</span>
                    </span>
                  </button>
                {:else}
                  <span role="menuitem" aria-disabled="true" class="faint">
                    <Icon name="globe" size={12} />
                    <span>{e.name} · {t('backlog.notProvisioned')}</span>
                  </span>
                {/if}
              {/each}

              {#if currentDeployment}
                <button
                  type="button"
                  role="menuitem"
                  onclick={() => {
                    menuOpen = false;
                    if (currentDeployment) showDeployment(currentDeployment.id);
                  }}
                >
                  <Icon name="file-text" size={12} />
                  <span>{t('backlog.lastDeploy')}</span>
                </button>
              {/if}

              {#if data.project.repo_url}
                <a
                  role="menuitem"
                  href="{data.project.repo_url}/issues?labels=&state=all"
                  target="_blank"
                  rel="noopener noreferrer"
                  title={t('backlog.issuesTitle')}
                >
                  <Icon name="external" size={12} />
                  <span>Issues</span>
                </a>
                <button
                  type="button"
                  role="menuitem"
                  onclick={() => {
                    menuOpen = false;
                    syncIssues();
                  }}
                  disabled={syncingIssues}
                  title={t('backlog.syncTitle')}
                >
                  <Icon name="copy" size={12} />
                  <span>{syncingIssues ? t('backlog.syncing') : t('backlog.sync')}</span>
                </button>
              {/if}
            </div>
          {/if}
        </div>
      </div>
    </div>

    {#if runningDeploy}
      {@const tail = lastLogLine(runningDeploy.logs)}
      <!-- Deploy em andamento: fica visível até o Coolify responder que terminou -->
      <div class="runbar-line deploy-progress" role="status" aria-live="polite">
        <span class="spinner-inline" aria-hidden="true"></span>
        <span class="mono deploy-progress-title">
          {runningDeploy.environment === 'test' ? t('dashboard.test') : t('deploys.env.production')} · {deployStage(runningDeploy.status)}
          <span class="faint">· {runningDeploy.branch}</span>
        </span>
        <span class="mono tabular deploy-progress-clock">{deploys.elapsed(runningDeploy)}</span>
        {#if tail}<span class="deploy-progress-tail mono faint" title={tail}>{tail}</span>{/if}
        <button type="button" class="btn-link label" onclick={() => showDeployment(runningDeploy.id)}>
          {t('backlog.seeLog')}
        </button>
        <span class="indeterminate" aria-hidden="true"></span>
      </div>
    {/if}

    {#if queueMessage || issuesNote}
      <div class="runbar-line" role="status">
        {#if isQueueRunning}
          <span class="spinner-inline" aria-hidden="true"></span>
        {:else}
          <Icon name="info" size={12} />
        {/if}
        <span class="mono">{queueMessage ?? issuesNote}</span>
      </div>
    {:else if activeSession && (sessionClosed || (allDone && branchesAlive))}
      <div class="runbar-line">
        <Icon name="info" size={12} />
        <span class="mono">{sessionClosed ? t('backlog.sessionClosed') : t('backlog.allDoneClose')}</span>
      </div>
    {/if}
  </div>

  <!-- O que depende do analista sobe para cá: a tarefa pode estar fora da tela.
       Esperar resposta é o único uso do acento; falha é peso e hachura. -->
  {#if awaiting.length || failed.length}
    <div class="attention">
      {#if awaiting.length}
        <button type="button" class="attn attn-await" onclick={() => reveal(awaiting[0].id)}>
          <span class="attn-mark" aria-hidden="true"></span>
          <span>{tp('backlog.awaitingYou', awaiting.length)}</span>
          <span class="mono">{awaiting.map((x) => stepLabel(x.id)).join(' ')}</span>
          <Icon name="arrow-right" size={11} />
        </button>
      {/if}
      {#if failed.length}
        <button type="button" class="attn attn-failed" onclick={() => reveal(failed[0].id)}>
          <Icon name="alert" size={12} />
          <span>{tp('backlog.failedCount', failed.length)}</span>
          <span class="mono">{failed.map((x) => stepLabel(x.id)).join(' ')}</span>
          <Icon name="arrow-right" size={11} />
        </button>
      {/if}
    </div>
  {/if}

  <!-- Filtro por estado: no lugar da antiga contagem, que só repetia o progresso. -->
  <div class="list-tools">
    <div class="filters" role="group" aria-label={t('backlog.filterTitle')}>
      <button
        type="button"
        class="chip label"
        class:on={filter === 'ALL'}
        aria-pressed={filter === 'ALL'}
        onclick={() => (filter = 'ALL')}
      >
        {t('backlog.filterAll')} <span class="mono">{tasks.length}</span>
      </button>
      {#each counts as c (c.status)}
        <button
          type="button"
          class="chip label"
          class:on={filter === c.status}
          class:accent={STATUS_META[c.status].accent}
          aria-pressed={filter === c.status}
          title={t('backlog.filterTitle')}
          onclick={() => (filter = filter === c.status ? 'ALL' : c.status)}
        >
          {c.label} <span class="mono">{c.n}</span>
        </button>
      {/each}
    </div>
    <div class="list-tools-actions">
      {#if !sessionClosed}
        <button
          type="button"
          class="btn btn-line btn-sm"
          onclick={() => (addTaskOpen = true)}
          title={t('backlog.addTaskTitle')}
        >
          <Icon name="plus" size={11} /> {t('backlog.addTask')}
        </button>
      {/if}
      <button type="button" class="btn-link label" onclick={() => setAll(true)}>{t('backlog.expandAll')}</button>
      <span class="sep" aria-hidden="true">·</span>
      <button type="button" class="btn-link label" onclick={() => setAll(false)}>{t('backlog.collapseAll')}</button>
    </div>
  </div>

  {#if visible.length === 0}
    <p class="filter-empty muted">{t('backlog.filterEmpty')}</p>
  {/if}

  <ol class="list divide">
    {#each visible as task (task.id)}
      {@const i = orderIndex.get(task.id) ?? 0}
      {@const stuck = blockers(task)}
      {@const isRunning = dispatching === task.id || task.status === 'RUNNING'}
      {@const isAwaiting = task.status === 'AWAITING_ANALYST'}
      {@const isCompleted = task.status === 'COMPLETED'}
      {@const isMerging = merging === task.id || task.status === 'IN_REVIEW'}
      {@const hasError = dispatchError?.id === task.id || (task.status === 'FAILED' && !!(task.error || task.last_comment))}
      {@const open = isOpen(task)}
      <li
        id="task-{task.id}"
        class="task rise"
        class:is-running={isRunning}
        class:open
        class:completed={isCompleted}
        style="--i: {Math.min(i, 8)}"
      >
        <!-- Número de Ordem de Execução Sequencial -->
        <div class="step-col">
          <span class="step-num mono" class:done={isCompleted} title="{t('backlog.orderTitle')} · {task.id}">
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
            <StatusTag status={isRunning ? 'RUNNING' : task.status} size="sm" />
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
              <p class="desc muted" class:clamp={isRunning && !descOpen[task.id]} lang={data.project.language || undefined}>{task.description}</p>
              {#if isRunning && task.description.length > 280}
                <button
                  type="button"
                  class="btn-link label read-more"
                  onclick={() => (descOpen[task.id] = !descOpen[task.id])}
                >
                  {descOpen[task.id] ? t('backlog.readLess') : t('backlog.readMore')}
                </button>
              {/if}

              <!-- O id da tarefa fica no título do número: aqui era só ruído. -->
              <div class="facts mono">
                {#if task.issue_url}
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
                {#if task.use_superpowers === false}
                  <span class="sep" aria-hidden="true">·</span>
                  <span class="no-superpowers" title={t('backlog.noSuperpowersTitle')}>{t('backlog.noSuperpowers')}</span>
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

          {#if open && (task.assigned_branch || isRunning)}
            <!-- Rodando, relê a branch a cada poucos segundos: é onde se vê o que
                 o agente já escreveu, inclusive sem commit. -->
            <TaskChanges taskId={task.id} title={`${stepLabel(task.id)} ${task.title}`} live={isRunning} />
          {/if}

          {#if open}
            {#if isMerging}
              <div class="merging-banner">
                <span class="spinner-inline" aria-hidden="true"></span>
                <span>{t('backlog.mergingBanner', { branch: data.project.default_branch || 'main' })}</span>
              </div>
            {/if}

            {#if !isRunning && (dispatchError?.id === task.id || (task.status === 'FAILED' && (task.error || task.last_comment)))}
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
          <!-- Concluída não tem ação própria: o teste é um só, na barra da sessão. -->
          {#if isMerging}
            <span class="completed-tag label mono">
              <span class="spinner-inline" aria-hidden="true"></span> {t('backlog.merging')}
            </span>
          {:else if isRunning}
            <button
              type="button"
              class="btn btn-line btn-sm"
              onclick={() => stopTask(task.id)}
              disabled={stoppingTaskId === task.id}
              title={t('backlog.stopTitle')}
            >
              <Icon name="square" size={10} />
              <span>{stoppingTaskId === task.id ? t('activity.stopping') : t('activity.stop')}</span>
            </button>
          {:else if !isCompleted}
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
            {#if superpowersEditable(task)}
              <label class="sp-toggle label" title={t('backlog.superpowersTitle')}>
                <input
                  type="checkbox"
                  checked={task.use_superpowers !== false}
                  disabled={togglingSuperpowers || isQueueRunning}
                  onchange={(e) => setSuperpowers([task], e.currentTarget.checked)}
                />
                <span>{t('backlog.superpowers')}</span>
              </label>
            {/if}
            {#if task.manual}
              <button
                type="button"
                class="btn-link label delete-task"
                onclick={() => deleteTask(task)}
                disabled={deletingTaskId === task.id || isQueueRunning}
                title={t('backlog.deleteTitle')}
              >
                <Icon name="trash" size={11} />
                <span>{deletingTaskId === task.id ? t('backlog.deleting') : t('backlog.delete')}</span>
              </button>
            {/if}
          {/if}
        </div>
      </li>
    {/each}
  </ol>
{/if}
</div>

<aside class="phone-col">
  <AppPreview projectId={data.project.id} version={completedCount} bind:collapsed={previewCollapsed} />
</aside>
</div>

<AddTaskDialog
  bind:open={addTaskOpen}
  projectId={data.project.id}
  sessionId={activeSession?.id}
  {tasks}
  oncreated={onTaskCreated}
/>

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
              <button
                type="button"
                class="btn-link link-ext bold"
                onclick={() => {
                  openDevice();
                }}
              >
                <Icon name="phone" size={10} /> {t('deploys.openApp')}
              </button>
            {/if}
          </div>
          {#if isDeployActive(currentDeployment)}
            <p class="faint deploy-hint">{t('backlog.deployHint')}</p>
          {/if}
          {#if currentDeployment.url}
            <div class="deploy-url-line">
              <span class="muted">URL:</span>
              <a href={currentDeployment.url} class="app-url" onclick={(e) => { e.preventDefault(); openDevice(); }}>
                {currentDeployment.url}
              </a>
            </div>
          {/if}
        </div>

        {#if currentDeployment.logs}
          <DeployTerminal
            logs={currentDeployment.logs}
            active={isDeployActive(currentDeployment)}
            failed={currentDeployment.status === 'FAILED'}
            branch={currentDeployment.branch}
          />
        {/if}
      </div>
    {:else}
      <p class="muted">{t('backlog.noDeploy')}</p>
    {/if}
  {/snippet}
  {#snippet footer()}
    <div class="spread modal-foot">
      {#if currentDeployment?.status === 'FAILED'}
        <div class="fix-action">
          <button
            type="button"
            class="btn btn-solid btn-sm"
            disabled={fixingDeploy}
            onclick={() => currentDeployment && fixWithAgent(currentDeployment)}
          >
            {fixingDeploy ? t('backlog.fixingWithAgent') : t('backlog.fixWithAgent')}
          </button>
          <span class="faint fix-hint">{t('backlog.fixWithAgentHint')}</span>
        </div>
      {:else}
        <div></div>
      {/if}
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

  /* Tarefas à esquerda, o app num smartphone à direita, preso na tela
     enquanto a lista rola. */
  .workspace {
    display: grid;
    grid-template-columns: minmax(0, 1fr) clamp(17rem, 27vw, 25rem);
    gap: var(--s6);
    align-items: start;
  }

  .workspace.collapsed {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .work {
    min-width: 0;
  }

  .phone-col {
    position: sticky;
    top: calc(3.25rem + 1px + var(--s5));
    margin-top: var(--s5);
  }

  /* Tela estreita: a prévia sobe para antes da lista, com altura própria. */
  @media (max-width: 1100px) {
    .workspace,
    .workspace.collapsed {
      grid-template-columns: minmax(0, 1fr);
    }

    .phone-col {
      position: static;
      order: -1;
    }
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

  /* Barra da sessão: presa sob o cabeçalho global (3.25rem + filete). */
  .runbar {
    position: sticky;
    top: calc(3.25rem + 1px);
    z-index: 10;
    margin-top: var(--s5);
    background: var(--paper);
    border-bottom: 1px solid var(--rule-ink);
  }

  .runbar-main {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--s3) var(--s5);
    padding: var(--s3) 0;
  }

  .session-badge {
    color: var(--ink);
    font-size: var(--t-small);
  }

  .progress {
    display: flex;
    align-items: center;
    gap: var(--s2);
    flex: 1 1 10rem;
    min-width: 8rem;
    font-size: var(--t-small);
  }

  .progress-track {
    flex: 1;
    height: 4px;
    background: var(--rule-2);
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: var(--ink);
    transition: width 0.3s ease-out;
  }

  .totals {
    color: var(--ink-3);
  }

  .runbar-actions {
    display: flex;
    align-items: center;
    gap: var(--s2);
    margin-left: auto;
  }

  .runbar-line {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--s2) var(--s3);
    padding: var(--s2) 0;
    border-top: 1px solid var(--rule);
    font-size: var(--t-small);
    color: var(--ink-2);
  }

  .menu {
    position: relative;
  }

  .more {
    letter-spacing: 0.1em;
  }

  .sheet {
    position: absolute;
    right: 0;
    top: calc(100% + var(--s2));
    z-index: 30;
    min-width: 16rem;
    max-width: min(24rem, calc(100vw - 2rem));
    background: var(--paper);
    border: 1px solid var(--rule-ink);
    display: flex;
    flex-direction: column;
    box-shadow: 0 16px 36px -12px var(--shadow);
  }

  .sheet > :global(*) {
    display: flex;
    align-items: center;
    gap: var(--s2);
    padding: var(--s2) var(--s3);
    text-align: left;
    font-size: var(--t-small);
    color: var(--ink);
    background: transparent;
    border: 0;
    cursor: pointer;
    text-decoration: none;
  }

  .sheet > :global(* + *) {
    border-top: 1px solid var(--rule);
  }

  .sheet > :global(*:hover:not(:disabled):not([aria-disabled='true'])) {
    background: var(--paper-sunk);
  }

  .sheet > :global(:disabled),
  .sheet > :global([aria-disabled='true']) {
    color: var(--ink-4);
    cursor: default;
  }

  .env-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .env-url {
    font-size: var(--t-micro);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }

  .attention {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s2);
    margin-top: var(--s4);
  }

  .attn {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    padding: var(--s2) var(--s3);
    font-size: var(--t-small);
    color: var(--ink);
    background: transparent;
    border: 1px solid var(--rule-ink);
    cursor: pointer;
  }

  /* Agente parado à espera do analista: o único lugar do acento. */
  .attn-await {
    border-color: var(--accent);
    color: var(--accent);
    font-weight: 600;
  }

  .attn-await:hover {
    background: var(--accent);
    color: var(--on-accent);
  }

  .attn-mark {
    width: 6px;
    height: 6px;
    background: currentColor;
  }

  .attn-failed {
    background: repeating-linear-gradient(-45deg, transparent 0 6px, var(--rule) 6px 7px);
  }

  .attn-failed:hover {
    border-color: var(--ink);
  }

  .filters {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s1);
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 0.4em;
    padding: 0.2rem 0.5rem;
    color: var(--ink-3);
    background: transparent;
    border: 1px solid transparent;
    cursor: pointer;
  }

  .chip:hover {
    color: var(--ink);
  }

  .chip.on {
    color: var(--ink);
    border-color: var(--rule-ink);
  }

  .chip.accent {
    color: var(--accent);
  }

  .filter-empty {
    padding: var(--s5) 0;
    font-size: var(--t-small);
  }

  .desc.clamp {
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .read-more {
    margin-top: var(--s1);
  }

  /* Sem issue, o primeiro item visível começava por um separador. */
  .facts > .sep:first-child {
    display: none;
  }

  @media (max-width: 760px) {
    .runbar {
      position: static;
    }

    .runbar-actions {
      margin-left: 0;
    }
  }

  .migration-banner {
    align-items: center;
    padding: var(--s3) var(--s4);
    background: var(--paper-2);
    border: 1px solid var(--rule-2);
    margin-top: var(--s5);
  }


























  .delete-task {
    display: inline-flex;
    align-items: center;
    gap: var(--s1);
  }

  /* Modal de Deploy */
  .deploy-modal-content {
    display: flex;
    flex-direction: column;
    gap: var(--s4);
    min-width: 0;
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
    padding-bottom: calc(var(--s2) + 2px);
    overflow: hidden;
  }

  .deploy-progress-tail {
    flex: 1 1 12rem;
    min-width: 0;
    font-size: var(--t-micro);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }


  .deploy-progress-title {
    font-size: var(--t-small);
    min-width: 0;
  }

  .deploy-progress-clock {
    font-size: var(--t-small);
    color: var(--ink-2);
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

  .fix-action {
    display: flex;
    align-items: center;
    gap: var(--s3);
    min-width: 0;
  }

  .fix-hint {
    font-size: var(--t-micro);
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






  .spinner-inline {
    width: 12px;
    height: 12px;
    border: 2px solid var(--rule-2);
    border-top-color: var(--ink);
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

  .list-tools-actions > .btn {
    margin-right: var(--s4);
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
    /* Tudo o que o card abre ocupa a largura toda da coluna: descrição,
       atividade, alterações e erros alinham pela mesma borda direita. */
    --task-col: none;
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

  /* Recuo único sob o título (depois da seta), para todos os blocos — inclusive
     os componentes filhos, que o seletor com escopo não alcançaria. */
  .body > :global(:not(.row-toggle)) {
    margin-left: calc(11px + var(--s3));
  }

  .body {
    min-width: 0;
  }

  .desc {
    margin-top: var(--s2);
    font-size: var(--t-small);
    line-height: 1.6;
    max-width: var(--task-col);
    text-align: justify;
    hyphens: auto;
    overflow-wrap: break-word;
  }

  /* Faixa entre réguas: separa a descrição do que vem abaixo dela. */
  .facts {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    row-gap: var(--s1);
    margin-top: var(--s3);
    padding: var(--s2) 0;
    border-block: 1px solid var(--rule);
    font-size: var(--t-micro);
    color: var(--ink-3);
  }

  .facts > .sep {
    align-self: stretch;
    width: 1px;
    margin-inline: var(--s3);
    background: var(--rule-2);
    font-size: 0;
  }

  .facts > .sep:first-child {
    display: none;
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
    max-width: var(--task-col);
  }

  .clar {
    margin-top: var(--s4);
    max-width: var(--task-col);
  }

  .merging-banner {
    display: flex;
    align-items: center;
    gap: var(--s3);
    margin-top: var(--s4);
    padding: var(--s3) var(--s4);
    background: var(--paper-2);
    border-left: 2px solid var(--ink);
    font-size: var(--t-small);
    color: var(--ink);
    max-width: var(--task-col);
  }







  .completed-note {
    margin-top: var(--s2);
    font-size: var(--t-micro);
    color: var(--ink-3);
  }

  .error-box {
    margin-top: var(--s3);
    max-width: var(--task-col);
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

  .sp-toggle {
    display: inline-flex;
    align-items: center;
    gap: var(--s1);
    cursor: pointer;
    white-space: nowrap;
  }

  /* Nada de azul do navegador: o acento é reservado ao exit 42. */
  .sp-toggle input {
    margin: 0;
    accent-color: var(--ink);
    cursor: pointer;
  }

  .sp-toggle:has(input:disabled) {
    cursor: default;
    color: var(--ink-3);
  }

  /* Peso, não cor: o acento é reservado ao agente parado à espera do analista. */
  .no-superpowers {
    font-weight: 600;
    color: var(--ink);
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


  .branch-link:hover {
    color: var(--ink);
  }



  .link-ext {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    color: var(--ink);
    text-decoration: underline;
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
