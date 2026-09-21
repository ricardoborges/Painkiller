<script lang="ts">
  import { page } from '$app/state';
  import { api } from '$lib/api';
  import { STATUS_META, STATUS_ORDER, type Task } from '$lib/types';
  import { pending } from '$lib/stores/pending.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import StatusTag from '$lib/components/StatusTag.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';
  import Elapsed from '$lib/components/Elapsed.svelte';
  import ClarificationPanel from '$lib/components/ClarificationPanel.svelte';

  let { data } = $props();

  let tasks = $state<Task[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let dispatching = $state<string | null>(null);
  let dispatchStart = $state(0);
  let dispatchError = $state<{ id: string; message: string } | null>(null);

  const justCreated = $derived(Number(page.url.searchParams.get('novas') ?? 0));

  const byId = $derived(new Map(tasks.map((t) => [t.id, t])));

  /** Ordena por urgência de leitura, não por data. */
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

  /** Dependências que ainda não concluíram — o orquestrador recusa o dispatch. */
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
    loading = true;
    error = null;
    try {
      tasks = await api.listTasks(data.project.id);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Falha ao carregar o backlog.';
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    load();
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
        message: e instanceof Error ? e.message : 'Falha ao despachar.'
      };
      load();
    } finally {
      dispatching = null;
    }
  }

  let merging = $state<string | null>(null);

  async function merge(task: Task) {
    merging = task.id;
    try {
      replace(await api.mergeTask(task.id));
    } catch (e) {
      dispatchError = {
        id: task.id,
        message: e instanceof Error ? e.message : 'Falha ao aprovar e incorporar (merge).'
      };
    } finally {
      merging = null;
    }
  }
</script>

{#if justCreated > 0}
  <p class="created label" role="status">
    <Icon name="check" size={12} />
    {justCreated}
    {justCreated === 1 ? 'tarefa decomposta' : 'tarefas decompostas'} a partir da especificação
  </p>
{/if}

{#if loading}
  <div class="pad"><Skeleton variant="table" rows={4} /></div>
{:else if error}
  <Placeholder kind="error" title="Não foi possível carregar o backlog" detail={error}>
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={load}>Tentar de novo</button>
    {/snippet}
  </Placeholder>
{:else if tasks.length === 0}
  <Placeholder
    title="Backlog vazio"
    detail="As tarefas nascem da análise inicial: quando o agente fecha a especificação, ele a decompõe em tarefas atômicas com critérios de aceitação e arquivos alvo."
  >
    {#snippet action()}
      <a class="btn btn-solid" href="/projetos/{data.project.id}/analise-inicial">
        <Icon name="play" size={11} /> Ir para a análise inicial
      </a>
    {/snippet}
  </Placeholder>
{:else}
  <div class="tally">
    {#each counts as c (c.status)}
      <div class="count" class:accent={STATUS_META[c.status].accent}>
        <span class="n mono">{String(c.n).padStart(2, '0')}</span>
        <span class="label">{c.label}</span>
      </div>
    {/each}
  </div>

  <ul class="list divide">
    {#each ordered as task, i (task.id)}
      {@const stuck = blockers(task)}
      {@const running = dispatching === task.id}
      <li class="task rise" style="--i: {Math.min(i, 8)}">
        <span class="idx mono" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>

        <div class="body">
          <div class="head">
            <h3 class="title">{task.title}</h3>
            <StatusTag status={task.status} size="sm" />
          </div>

          <p class="desc muted">{task.description}</p>

          <div class="facts mono">
            <span title="Identificador da tarefa">{task.id}</span>
            {#if task.assigned_branch}
              <span class="sep" aria-hidden="true">·</span>
              {#if data.project.repo_url}
                <a
                  href="{data.project.repo_url}/src/branch/{task.assigned_branch}"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="branch-link"
                  title="Ver branch no Gitea"
                >
                  {task.assigned_branch} <Icon name="external" size={9} />
                </a>
              {:else}
                <span>{task.assigned_branch}</span>
              {/if}
            {/if}
            {#if task.target_files.length}
              <span class="sep" aria-hidden="true">·</span>
              <span>{task.target_files.length} arquivo{task.target_files.length > 1 ? 's' : ''}</span>
            {/if}
          </div>

          {#if task.target_files.length || task.acceptance_criteria.length}
            <details>
              <summary class="label">Critérios e arquivos alvo</summary>
              <div class="detail-grid">
                {#if task.acceptance_criteria.length}
                  <div>
                    <span class="label">Critérios de aceitação</span>
                    <ul class="bullets">
                      {#each task.acceptance_criteria as c, ci (ci)}
                        <li>{c}</li>
                      {/each}
                    </ul>
                  </div>
                {/if}
                {#if task.target_files.length}
                  <div>
                    <span class="label">Arquivos alvo</span>
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

          {#if stuck.length}
            <p class="blocked-note">
              Travada por
              {#each stuck as d, di (d.id)}<span class="mono">{d.title}</span>{#if di < stuck.length - 1}, {/if}{/each}
              — o orquestrador recusa o dispatch enquanto a dependência não concluir.
            </p>
          {/if}

          {#if task.status === 'AWAITING_ANALYST' && !running}
            <div class="clar">
              <ClarificationPanel {task} onresolved={replace} />
            </div>
          {/if}

          {#if running}
            <div class="running">
              <span class="pulse" aria-hidden="true"></span>
              <span>
                Contêiner em execução. A requisição fica aberta até o agente sair — saída
                <span class="mono">0</span> roda os testes,
                <span class="mono">42</span> devolve uma pergunta.
              </span>
              <Elapsed from={dispatchStart} />
            </div>
          {/if}

          {#if dispatchError?.id === task.id}
            <p class="error-line" role="alert">
              <Icon name="alert" size={12} />
              {dispatchError.message}
            </p>
          {/if}
        </div>

        <div class="side">
          {#if task.status === 'IN_REVIEW'}
            {#if data.project.repo_url && task.assigned_branch}
              <a
                href="{data.project.repo_url}/compare/{data.project.default_branch}...{task.assigned_branch}"
                target="_blank"
                rel="noopener noreferrer"
                class="btn btn-line btn-sm"
                title="Comparar e ver diff no Gitea"
              >
                <Icon name="external" size={11} /> Ver Diff
              </a>
            {/if}
            <button
              type="button"
              class="btn btn-solid btn-sm"
              onclick={() => merge(task)}
              disabled={merging === task.id}
              title="Aprovar e incorporar branch na principal"
            >
              {#if merging === task.id}
                Incorporando…
              {:else}
                <Icon name="check" size={11} /> Aprovar & Merge
              {/if}
            </button>
          {:else}
            <button
              type="button"
              class="btn btn-line btn-sm"
              onclick={() => dispatch(task)}
              disabled={!canDispatch(task)}
              title={stuck.length ? 'Dependências pendentes' : 'Executar no contêiner'}
            >
              {#if running}
                Executando…
              {:else if task.status === 'FAILED'}
                <Icon name="play" size={11} /> Repetir
              {:else}
                <Icon name="play" size={11} /> Despachar
              {/if}
            </button>
          {/if}
        </div>
      </li>
    {/each}
  </ul>
{/if}

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

  /* Placar do backlog: números grandes em mono, separados por filete */
  .tally {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s6);
    padding: var(--s5) 0;
    border-bottom: 1px solid var(--rule-ink);
    margin-top: var(--s5);
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

  .list {
    border-bottom: 1px solid var(--rule);
  }

  .task {
    display: grid;
    grid-template-columns: 2.75rem 1fr auto;
    gap: var(--s4);
    padding: var(--s5) 0;
  }

  .idx {
    font-size: var(--t-small);
    color: var(--ink-4);
    padding-top: 0.2rem;
  }

  .body {
    min-width: 0;
  }

  .head {
    display: flex;
    align-items: center;
    gap: var(--s3);
    flex-wrap: wrap;
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

  .running {
    display: flex;
    align-items: center;
    gap: var(--s3);
    margin-top: var(--s4);
    padding: var(--s3) var(--s4);
    background: var(--paper-sunk);
    border-left: 2px solid var(--ink);
    font-size: var(--t-small);
    color: var(--ink-2);
    max-width: 44rem;
  }

  .pulse {
    width: 6px;
    height: 6px;
    flex: none;
    background: var(--ink);
    animation: blink 1.3s var(--ease) infinite;
  }

  .error-line {
    display: flex;
    align-items: flex-start;
    gap: var(--s2);
    margin-top: var(--s3);
    font-size: var(--t-small);
    color: var(--accent);
    max-width: var(--measure);
  }

  .side {
    padding-top: 0.1rem;
    display: flex;
    flex-direction: column;
    gap: var(--s2);
    align-items: flex-end;
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

  @media (max-width: 760px) {
    .task {
      grid-template-columns: 1.75rem 1fr;
    }

    .side {
      grid-column: 2;
    }

    .detail-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
