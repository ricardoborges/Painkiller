<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import { goto } from '$app/navigation';
  import { api, baseName } from '$lib/api';
  import type { AnalysisSession, Project, Task } from '$lib/types';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import { analysisFor, analysisStorageKey } from '$lib/stores/analysis.svelte';
  import { getProjectSessionStore } from '$lib/stores/session.svelte';

  /* Contexto do projeto (os três campos, anexos, repositório) e o andamento
     da sessão atual. É a página inicial de um projeto sem sessão concluída e
     vive em /context depois disso. */
  let { project }: { project: Project } = $props();

  const sessionStore = $derived(getProjectSessionStore(project.id));

  let restarting = $state(false);

  async function handleRestart() {
    if (!confirm(t('context.confirmRestart'))) {
      return;
    }
    restarting = true;
    try {
      const a = analysisFor(project.id, sessionStore.activeSession?.id);
      await a.restart();
      await goto(`${base}/initial-analysis`);
    } catch (e) {
      alert(e instanceof Error ? e.message : t('context.restartFailed'));
    } finally {
      restarting = false;
    }
  }

  /* Onde o projeto está no caminho Contexto → Análise → Backlog. Deduzido do
     que existe: tarefas importadas mandam; senão, a sessão de análise ativa;
     senão, a última sessão que este navegador lembra (o servidor só expõe a
     ativa). Nada disso → primeira vez. */
  type Stage =
    | { kind: 'new' }
    | { kind: 'analysis'; session: AnalysisSession }
    | { kind: 'analysis-done'; session: AnalysisSession }
    | { kind: 'analysis-failed'; session: AnalysisSession }
    | { kind: 'backlog'; tasks: Task[] };

  let stage = $state<Stage | null>(null);

  function recallSession(projectId: string): string | null {
    const key = analysisStorageKey(projectId, sessionStore.activeSession?.id);
    try {
      return sessionStorage.getItem(key) || localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  async function detect(projectId: string): Promise<Stage> {
    const [tasks, current] = await Promise.all([
      api.listTasks(projectId).catch(() => [] as Task[]),
      api.getCurrentAnalysis(projectId).catch(() => ({ session: null }))
    ]);
    if (tasks.length) return { kind: 'backlog', tasks };
    if (current.session) return { kind: 'analysis', session: current.session };

    const previous = recallSession(projectId);
    if (previous) {
      try {
        const session = await api.getAnalysis(previous);
        if (session.status === 'FINISHED') return { kind: 'analysis-done', session };
        if (session.status === 'FAILED') return { kind: 'analysis-failed', session };
        return { kind: 'analysis', session };
      } catch {
        /* sessão esquecida pelo servidor: conta como primeira vez */
      }
    }
    return { kind: 'new' };
  }

  $effect(() => {
    const id = project.id;
    stage = null;
    detect(id).then((s) => {
      if (project.id === id) stage = s;
    });
  });

  const base = $derived(`/projects/${project.id}`);

  /* 0 = contexto, 1 = análise, 2 = backlog: o passo em que o projeto está. */
  const current = $derived(
    !stage || stage.kind === 'new' ? 0 : stage.kind === 'backlog' ? 2 : 1
  );

  const tally = $derived.by(() => {
    if (stage?.kind !== 'backlog') return null;
    const list = stage.tasks;
    return {
      total: list.length,
      done: list.filter((x) => x.status === 'COMPLETED').length,
      awaiting: list.filter((x) => x.status === 'AWAITING_ANALYST').length,
      running: list.filter((x) => x.status === 'RUNNING').length,
      failed: list.filter((x) => x.status === 'FAILED').length
    };
  });

  const ANALYSIS_DETAIL = $derived<Record<string, string>>({
    STARTING: t('context.detail.STARTING'),
    WAITING_AGENT: t('context.detail.WAITING_AGENT'),
    WAITING_ANALYST: t('context.detail.WAITING_ANALYST')
  });

  const sections = $derived([
    { label: t('form.description'), text: project.description },
    { label: t('context.businessPurpose'), text: project.purpose },
    { label: t('form.solution'), text: project.solution_description }
  ]);
</script>

<!-- Grade assimétrica 2fr/1fr: a prosa carrega o peso, a coluna
     estreita guarda metadados e ações. -->
<div class="grid">
  <div class="prose">
    {#each sections as s, i (s.label)}
      <section class="block rise" style="--i: {i}">
        <h2 class="label">{s.label}</h2>
        {#if s.text}
          <p>{s.text}</p>
        {:else}
          <p class="faint">{t('projects.notProvided')}.</p>
        {/if}
      </section>
    {/each}
  </div>

  <aside>
    <!-- Com o painel do projeto no ar, o andamento mora lá: aqui só o contexto. -->
    {#if !sessionStore.hasCompleted}
      <div class="panel">
        <h2 class="label">{t('context.progress')}</h2>

        <ol class="trail">
          {#each [t('projectNav.context'), t('context.initialAnalysis'), t('projectNav.backlog')] as label, i (label)}
            {@const done = stage !== null && i < current}
            <li class:done class:here={stage !== null && i === current}>
              <span class="mark mono" aria-hidden="true">
                {#if done}<Icon name="check" size={10} />{:else}{i + 1}{/if}
              </span>
              {label}
            </li>
          {/each}
        </ol>

        {#if !stage}
          <Skeleton rows={2} />
        {:else if stage.kind === 'new'}
          <p class="state">{t('context.firstTime')}</p>
          <p class="help">{t('context.firstTimeHelp')}</p>
          <a class="btn btn-solid go" href="{base}/initial-analysis">
            <Icon name="play" size={11} /> {t('context.startAnalysis')}
          </a>
        {:else if stage.kind === 'analysis'}
          <p class="state">{t('context.inProgress')}</p>
          <p class="help">{ANALYSIS_DETAIL[stage.session.status] ?? ''}</p>
          <div class="andamento-actions">
            <a class="btn btn-solid go" href="{base}/initial-analysis">
              {t('context.continue')} <Icon name="arrow-right" size={11} />
            </a>
            <button
              type="button"
              class="btn btn-quiet btn-sm restart-btn"
              onclick={handleRestart}
              disabled={restarting}
              title={t('context.restartTitle')}
            >
              <Icon name="play" size={10} />
              <span>{restarting ? t('context.restarting') : t('context.restart')}</span>
            </button>
          </div>
        {:else if stage.kind === 'analysis-done'}
          <p class="state">{t('context.done')}</p>
          <p class="help">{t('context.notImported')}</p>
          <div class="andamento-actions">
            <a class="btn btn-solid go" href="{base}/initial-analysis">
              {t('context.importBacklog')} <Icon name="arrow-right" size={11} />
            </a>
            <button
              type="button"
              class="btn btn-quiet btn-sm restart-btn"
              onclick={handleRestart}
              disabled={restarting}
              title={t('context.restartTitle')}
            >
              <Icon name="play" size={10} />
              <span>{restarting ? t('context.restarting') : t('context.restart')}</span>
            </button>
          </div>
        {:else if stage.kind === 'analysis-failed'}
          <p class="state">{t('context.failed')}</p>
          {#if stage.session.error}
            <p class="help clamp-2" title={stage.session.error}>{stage.session.error}</p>
          {/if}
          <div class="andamento-actions">
            <a class="btn btn-solid go" href="{base}/initial-analysis">
              {t('context.resume')} <Icon name="arrow-right" size={11} />
            </a>
            <button
              type="button"
              class="btn btn-quiet btn-sm restart-btn"
              onclick={handleRestart}
              disabled={restarting}
              title={t('context.restartTitle')}
            >
              <Icon name="play" size={10} />
              <span>{restarting ? t('context.restarting') : t('context.restart')}</span>
            </button>
          </div>
        {:else if tally}
          <p class="state">
            {tally.done === tally.total ? t('context.backlogDone') : t('context.backlogRunning')}
          </p>
          <p class="help mono counts">
            {t('context.tallyDone', { done: tally.done, total: tally.total })}{#if tally.running}&nbsp;· {t('context.tallyRunning', { count: tally.running })}{/if}{#if tally.failed}&nbsp;· {t('context.tallyFailed', { count: tally.failed })}{/if}
          </p>
          {#if tally.awaiting}
            <a class="blocked label" href="{base}/backlog">
              <span class="dot" aria-hidden="true"></span>
              {t('projects.awaitingAnalyst', { count: tally.awaiting })}
            </a>
          {/if}
          <a class="btn btn-solid go" href="{base}/backlog">
            {t('context.openBacklog')} <Icon name="arrow-right" size={11} />
          </a>
        {/if}
      </div>
    {/if}

    <div class="panel">
      <h2 class="label">{t('context.attachments')}</h2>
      {#if project.attachments.length}
        <ul class="files divide">
          {#each project.attachments as path (path)}
            <li class="file">
              <Icon name="clip" size={12} />
              <span class="truncate" title={baseName(path)}>{baseName(path)}</span>
            </li>
          {/each}
        </ul>
        <p class="help">{t('context.attachmentsHelp')}</p>
      {:else}
        <p class="faint none">{t('context.noAttachments')}</p>
      {/if}
    </div>

    <div class="panel">
      <h2 class="label">{t('projectNav.repository')}</h2>
      <p class="mono path">{project.repo_path}</p>
      <p class="help">{@html t('context.mounted')}</p>
    </div>

    <div class="acts">
      <a class="btn btn-line" href="{base}/edit">
        <Icon name="pencil" size={11} /> {t('common.edit')}
      </a>
    </div>
  </aside>
</div>

<style>
  .grid {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: var(--s9);
    padding-top: var(--s6);
    align-items: start;
  }

  .prose {
    max-width: var(--measure);
  }

  .block + .block {
    margin-top: var(--s6);
    border-top: 1px solid var(--rule);
    padding-top: var(--s5);
  }

  .block p {
    margin-top: var(--s3);
    white-space: pre-wrap;
  }

  aside {
    display: flex;
    flex-direction: column;
    gap: var(--s6);
    position: sticky;
    top: 4.5rem;
  }

  .panel {
    border-top: 1px solid var(--rule-ink);
    padding-top: var(--s3);
  }

  /* Mesma régua das abas do cabeçalho: passo atual preenchido. */
  .trail {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s2) var(--s4);
    margin: var(--s3) 0 var(--s4);
    font-size: var(--t-small);
    color: var(--ink-4);
  }

  .trail li {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
  }

  .trail li.done {
    color: var(--ink-3);
  }

  .trail li.here {
    color: var(--ink);
  }

  .mark {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.125rem;
    height: 1.125rem;
    font-size: var(--t-label);
    border: 1px solid var(--rule-2);
  }

  .here .mark {
    background: var(--ink);
    border-color: var(--ink);
    color: var(--paper);
  }

  .state {
    margin-top: var(--s2);
    font-size: var(--t-small);
    color: var(--ink);
  }

  .counts {
    font-size: var(--t-micro);
  }

  .blocked {
    display: flex;
    width: fit-content;
    align-items: center;
    gap: 0.375rem;
    margin-top: var(--s3);
    color: var(--accent);
  }

  .dot {
    width: 6px;
    height: 6px;
    background: currentColor;
  }

  .andamento-actions {
    display: flex;
    align-items: center;
    gap: var(--s3);
    margin-top: var(--s4);
    flex-wrap: wrap;
  }

  .andamento-actions .go {
    margin-top: 0;
  }

  .restart-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    height: 2rem;
    font-size: var(--t-micro);
    color: var(--ink-3);
  }

  .restart-btn:hover:not(:disabled) {
    color: var(--ink);
  }

  .go {
    display: flex;
    width: fit-content;
    margin-top: var(--s4);
  }

  .files {
    margin-top: var(--s2);
  }

  .file {
    display: flex;
    align-items: center;
    gap: var(--s2);
    padding: var(--s2) 0;
    font-size: var(--t-small);
    color: var(--ink-2);
    min-width: 0;
  }

  .none {
    margin-top: var(--s3);
    font-size: var(--t-small);
  }

  .help {
    margin-top: var(--s3);
  }

  .path {
    margin-top: var(--s3);
    font-size: var(--t-micro);
    color: var(--ink-2);
    word-break: break-all;
  }

  .acts {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s2);
  }

  @media (max-width: 900px) {
    .grid {
      grid-template-columns: 1fr;
      gap: var(--s7);
    }

    aside {
      position: static;
    }
  }
</style>
