<script lang="ts">
  import { goto } from '$app/navigation';
  import { api, baseName } from '$lib/api';
  import type { AnalysisSession, Task } from '$lib/types';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import { analysisFor, analysisStorageKey } from '$lib/stores/analysis.svelte';
  import { getProjectSessionStore } from '$lib/stores/session.svelte';

  let { data } = $props();

  const sessionStore = $derived(getProjectSessionStore(data.project.id));

  let restarting = $state(false);

  async function handleRestart() {
    if (!confirm('Descartar a sessão atual e iniciar uma nova análise do zero?')) {
      return;
    }
    restarting = true;
    try {
      const a = analysisFor(data.project.id, sessionStore.activeSession?.id);
      await a.restart();
      await goto(`${base}/initial-analysis`);
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Falha ao reiniciar análise.');
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
    const id = data.project.id;
    stage = null;
    detect(id).then((s) => {
      if (data.project.id === id) stage = s;
    });
  });

  const base = $derived(`/projects/${data.project.id}`);

  /* 0 = contexto, 1 = análise, 2 = backlog: o passo em que o projeto está. */
  const current = $derived(
    !stage || stage.kind === 'new' ? 0 : stage.kind === 'backlog' ? 2 : 1
  );

  const tally = $derived.by(() => {
    if (stage?.kind !== 'backlog') return null;
    const t = stage.tasks;
    return {
      total: t.length,
      done: t.filter((x) => x.status === 'COMPLETED').length,
      awaiting: t.filter((x) => x.status === 'AWAITING_ANALYST').length,
      running: t.filter((x) => x.status === 'RUNNING').length,
      failed: t.filter((x) => x.status === 'FAILED').length
    };
  });

  const ANALYSIS_DETAIL: Record<string, string> = {
    STARTING: 'Subindo o contêiner do agente.',
    WAITING_AGENT: 'O agente está trabalhando.',
    WAITING_ANALYST: 'O agente aguarda a sua resposta.'
  };

  const sections = $derived([
    { label: 'Descrição geral', text: data.project.description },
    { label: 'Propósito de negócio', text: data.project.purpose },
    { label: 'Solução desejada', text: data.project.solution_description }
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
          <p class="faint">Não informado.</p>
        {/if}
      </section>
    {/each}
  </div>

  <aside>
    <div class="panel">
      <h2 class="label">Andamento</h2>

      <ol class="trail">
        {#each ['Contexto', 'Análise inicial', 'Backlog'] as label, i (label)}
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
        <p class="state">Primeira vez neste projeto.</p>
        <p class="help">
          O agente vai entrevistar você a partir do contexto ao lado e propor o backlog.
        </p>
        <a class="btn btn-solid go" href="{base}/initial-analysis">
          <Icon name="play" size={11} /> Iniciar análise
        </a>
      {:else if stage.kind === 'analysis'}
        <p class="state">Análise inicial em andamento.</p>
        <p class="help">{ANALYSIS_DETAIL[stage.session.status] ?? ''}</p>
        <div class="andamento-actions">
          <a class="btn btn-solid go" href="{base}/initial-analysis">
            Continuar análise <Icon name="arrow-right" size={11} />
          </a>
          <button
            type="button"
            class="btn btn-quiet btn-sm restart-btn"
            onclick={handleRestart}
            disabled={restarting}
            title="Descartar a análise atual e recomeçar do zero"
          >
            <Icon name="play" size={10} />
            <span>{restarting ? 'Reiniciando…' : 'Reiniciar do zero'}</span>
          </button>
        </div>
      {:else if stage.kind === 'analysis-done'}
        <p class="state">Análise concluída.</p>
        <p class="help">O backlog proposto pelo agente ainda não foi importado.</p>
        <div class="andamento-actions">
          <a class="btn btn-solid go" href="{base}/initial-analysis">
            Importar backlog <Icon name="arrow-right" size={11} />
          </a>
          <button
            type="button"
            class="btn btn-quiet btn-sm restart-btn"
            onclick={handleRestart}
            disabled={restarting}
            title="Descartar e recomeçar análise do zero"
          >
            <Icon name="play" size={10} />
            <span>{restarting ? 'Reiniciando…' : 'Reiniciar do zero'}</span>
          </button>
        </div>
      {:else if stage.kind === 'analysis-failed'}
        <p class="state">A última análise falhou.</p>
        {#if stage.session.error}
          <p class="help clamp-2" title={stage.session.error}>{stage.session.error}</p>
        {/if}
        <div class="andamento-actions">
          <a class="btn btn-solid go" href="{base}/initial-analysis">
            Retomar análise <Icon name="arrow-right" size={11} />
          </a>
          <button
            type="button"
            class="btn btn-quiet btn-sm restart-btn"
            onclick={handleRestart}
            disabled={restarting}
            title="Descartar e recomeçar análise do zero"
          >
            <Icon name="play" size={10} />
            <span>{restarting ? 'Reiniciando…' : 'Reiniciar do zero'}</span>
          </button>
        </div>
      {:else if tally}
        <p class="state">
          {tally.done === tally.total ? 'Backlog concluído.' : 'Backlog em execução.'}
        </p>
        <p class="help mono counts">
          {tally.done}/{tally.total} concluídas{#if tally.running}&nbsp;· {tally.running} executando{/if}{#if tally.failed}&nbsp;· {tally.failed} com falha{/if}
        </p>
        {#if tally.awaiting}
          <a class="blocked label" href="{base}/backlog">
            <span class="dot" aria-hidden="true"></span>
            {tally.awaiting} aguardando analista
          </a>
        {/if}
        <a class="btn btn-solid go" href="{base}/backlog">
          Abrir backlog <Icon name="arrow-right" size={11} />
        </a>
      {/if}
    </div>

    <div class="panel">
      <h2 class="label">Anexos de contexto</h2>
      {#if data.project.attachments.length}
        <ul class="files divide">
          {#each data.project.attachments as path (path)}
            <li class="file">
              <Icon name="clip" size={12} />
              <span class="truncate" title={baseName(path)}>{baseName(path)}</span>
            </li>
          {/each}
        </ul>
        <p class="help">
          Extraídos como texto e concatenados ao prompt inicial da análise.
        </p>
      {:else}
        <p class="faint none">
          Nenhum documento anexado. O agente vai trabalhar só com os três campos ao lado.
        </p>
      {/if}
    </div>

    <div class="panel">
      <h2 class="label">Repositório</h2>
      <p class="mono path">{data.project.repo_path}</p>
      <p class="help">Montado em <span class="mono">/workspace</span> dentro do contêiner.</p>
    </div>

    <div class="acts">
      <a class="btn btn-line" href="{base}/edit">
        <Icon name="pencil" size={11} /> Editar
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
