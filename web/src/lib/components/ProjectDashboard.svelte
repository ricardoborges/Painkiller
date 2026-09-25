<script lang="ts">
  import { goto } from '$app/navigation';
  import { api, authedUrl } from '$lib/api';
  import type {
    DeploymentRecord,
    DeploymentStatus,
    EnvironmentStatusResponse,
    IterationSession,
    Project,
    SessionStatus,
    Task,
    UsageSummary
  } from '$lib/types';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import { getProjectSessionStore } from '$lib/stores/session.svelte';

  /* Entrada de um projeto que já tem histórico: o que está no ar, quanto custou,
     o que foi entregue e por onde seguir. O contexto fica em /context. */
  let { project }: { project: Project } = $props();

  const base = $derived(`/projects/${project.id}`);
  const sessionStore = $derived(getProjectSessionStore(project.id));

  let usage = $state<UsageSummary | null>(null);
  let env = $state<EnvironmentStatusResponse | null>(null);
  let deployments = $state<DeploymentRecord[]>([]);
  let tasks = $state<Task[]>([]);
  let ready = $state(false);

  $effect(() => {
    const id = project.id;
    ready = false;
    Promise.all([
      api.getProjectUsage(id).catch(() => null),
      api.getEnvironmentStatus(id).catch(() => null),
      api.listDeployments(id, 5).catch(() => [] as DeploymentRecord[]),
      api.listTasks(id).catch(() => [] as Task[])
    ]).then(([u, e, d, t]) => {
      if (project.id !== id) return;
      usage = u;
      env = e;
      deployments = d;
      tasks = t;
      ready = true;
    });
  });

  /* ---- ações ---- */

  /* A sessão em aberto, se houver: a última que ainda não foi encerrada. */
  const openSession = $derived(
    [...sessionStore.sessions].reverse().find((s) => s.status !== 'COMPLETED') ?? null
  );

  async function startNextSession() {
    if (await sessionStore.createNextSession()) await goto(`${base}/initial-analysis`);
  }

  /* Uma sessão ainda na análise abre no chat; as demais, no backlog. */
  function sessionHref(s: IterationSession) {
    return s.status === 'PLANNING' ? `${base}/initial-analysis` : `${base}/backlog`;
  }

  async function openSessionPage(s: IterationSession) {
    sessionStore.selectSession(s.id);
    await goto(sessionHref(s));
  }

  /* O backlog mostra uma sessão por vez: abre a da tarefa que espera o analista. */
  async function openBlocked() {
    const task = tasks.find((t) => t.status === 'AWAITING_ANALYST');
    const s = sessionStore.sessions.find((x) => x.id === task?.session_id);
    if (s) sessionStore.selectSession(s.id);
    await goto(`${base}/backlog`);
  }

  /* ---- ambientes ---- */

  const DEPLOY_LABEL: Record<DeploymentStatus, string> = {
    PENDING: 'Na fila',
    BUILDING: 'Publicando',
    HEALTHY: 'No ar',
    FAILED: 'Falhou',
    STOPPED: 'Parado'
  };

  /* O status do Coolify manda; sem registro de deploy, vale a URL fixa do projeto. */
  const environments = $derived([
    {
      key: 'production',
      label: 'Produção',
      url: env?.production.url ?? project.production_url ?? null,
      status: env?.production.status ?? null,
      branch: env?.production.branch ?? null,
      updated: env?.production.updated_at ?? null
    },
    {
      key: 'test',
      label: 'Teste',
      url: env?.test.url ?? project.test_url ?? null,
      status: env?.test.status ?? null,
      branch: env?.test.branch ?? null,
      updated: env?.test.updated_at ?? null
    }
  ]);

  const published = $derived(environments.some((e) => e.url));

  /* ---- entregas ---- */

  const tally = $derived({
    total: tasks.length,
    done: tasks.filter((t) => t.status === 'COMPLETED').length,
    awaiting: tasks.filter((t) => t.status === 'AWAITING_ANALYST').length,
    running: tasks.filter((t) => t.status === 'RUNNING').length,
    failed: tasks.filter((t) => t.status === 'FAILED').length
  });

  const SESSION_LABEL: Record<SessionStatus, string> = {
    PLANNING: 'Análise',
    BACKLOG: 'Backlog',
    IN_SPRINT: 'Execução',
    COMPLETED: 'Concluída'
  };

  function sessionTally(id: string) {
    const own = tasks.filter((t) => t.session_id === id);
    return { total: own.length, done: own.filter((t) => t.status === 'COMPLETED').length };
  }

  /* ---- formatação ---- */

  function money(value: number, code = 'USD'): string {
    const tiny = value !== 0 && Math.abs(value) < 0.01;
    try {
      return new Intl.NumberFormat('pt-BR', {
        style: 'currency',
        currency: code,
        minimumFractionDigits: tiny ? 4 : 2,
        maximumFractionDigits: tiny ? 4 : 2
      }).format(value);
    } catch {
      return `${code} ${value.toFixed(tiny ? 4 : 2)}`;
    }
  }

  function local(usd: number): string | null {
    const r = usage?.currency.exchange_rate;
    return r ? money(usd * r, usage!.currency.local) : null;
  }

  const tokens = new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 });

  function when(iso: string | null | undefined): string {
    if (!iso) return '';
    const date = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
    return date.toLocaleString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function host(url: string): string {
    return url.replace(/^https?:\/\//, '').replace(/\/$/, '');
  }

  const ratio = $derived(usage?.budget.used_ratio ?? null);
  const over = $derived((usage?.budget.remaining_usd ?? 0) < 0);
</script>

<div class="dash">
  <!-- Faixa de ações: a única ação sólida é começar a próxima iteração. -->
  <section class="lead rise">
    <div class="lead-text">
      {#if openSession}
        <p class="state">
          Sessão #{openSession.number} em {SESSION_LABEL[openSession.status].toLowerCase()}.
        </p>
        <p class="help">{openSession.title}</p>
      {:else}
        <p class="state">Todas as sessões foram encerradas.</p>
        <p class="help">Uma nova sessão abre um chat com o agente sobre o que vem a seguir.</p>
      {/if}
      {#if tally.awaiting}
        <button type="button" class="blocked label" onclick={openBlocked}>
          <span class="dot" aria-hidden="true"></span>
          {tally.awaiting} aguardando analista
        </button>
      {/if}
    </div>

    <div class="lead-acts">
      {#if openSession}
        <button type="button" class="btn btn-line" onclick={() => openSessionPage(openSession)}>
          Continuar sessão #{openSession.number} <Icon name="arrow-right" size={11} />
        </button>
      {/if}
      <button
        type="button"
        class="btn btn-solid"
        onclick={startNextSession}
        disabled={sessionStore.creating}
      >
        <Icon name="plus" size={11} />
        {sessionStore.creating ? 'Criando…' : 'Nova sessão'}
      </button>
    </div>
  </section>
  {#if sessionStore.error}
    <p class="err" role="alert">{sessionStore.error}</p>
  {/if}

  <div class="grid">
    <div class="main">
      <!-- Ambientes publicados -->
      <section class="panel rise" style="--i: 1">
        <h2 class="label">Publicado</h2>
        {#if !ready}
          <Skeleton rows={2} />
        {:else if published}
          <ul class="envs divide">
            {#each environments as e (e.key)}
              <li class="env" class:hatch={e.status === 'FAILED'}>
                <span class="env-name label">{e.label}</span>
                {#if e.url}
                  <a class="env-url mono truncate" href={e.url} target="_blank" rel="noopener noreferrer">
                    {host(e.url)} <Icon name="external" size={10} />
                  </a>
                  <span class="env-meta mono faint">
                    {#if e.status}<span class:live={e.status === 'HEALTHY'}>{DEPLOY_LABEL[e.status]}</span>{/if}
                    {#if e.branch}<span>· {e.branch}</span>{/if}
                    {#if e.updated}<span>· {when(e.updated)}</span>{/if}
                  </span>
                {:else}
                  <span class="faint env-none">Ainda não publicado.</span>
                {/if}
              </li>
            {/each}
          </ul>
        {:else}
          <p class="faint none">
            Nada publicado ainda. Uma tarefa concluída pode ser publicada no ambiente de teste pelo
            botão "Testar" do backlog.
          </p>
        {/if}

        {#if deployments.length}
          <h3 class="label sub">Últimos deploys</h3>
          <ul class="deploys divide">
            {#each deployments as d (d.id)}
              <li class="deploy" class:hatch={d.status === 'FAILED'}>
                <span class="mono faint">{when(d.created_at)}</span>
                <span class="label">{d.environment === 'production' ? 'Produção' : 'Teste'}</span>
                <span class="mono truncate branch" title={d.branch}>{d.branch}</span>
                <span class="mono" class:live={d.status === 'HEALTHY'}>{DEPLOY_LABEL[d.status]}</span>
              </li>
            {/each}
          </ul>
        {/if}
      </section>

      <!-- Sessões -->
      <section class="panel rise" style="--i: 2">
        <h2 class="label">Sessões</h2>
        <ul class="sessions divide">
          {#each [...sessionStore.sessions].reverse() as s (s.id)}
            {@const t = sessionTally(s.id)}
            <li>
              <button type="button" class="session" onclick={() => openSessionPage(s)}>
                <span class="mono faint num">#{s.number}</span>
                <span class="s-title truncate" class:closed={s.status === 'COMPLETED'}>{s.title}</span>
                <span class="mono faint s-count">
                  {#if t.total}{t.done}/{t.total} tarefas{/if}
                </span>
                <span class="badge mono label" class:closed={s.status === 'COMPLETED'}>
                  {SESSION_LABEL[s.status]}
                </span>
                <span class="mono faint s-date">{when(s.updated_at)}</span>
              </button>
            </li>
          {/each}
        </ul>
      </section>
    </div>

    <aside>
      <!-- Custos -->
      <section class="panel rise" style="--i: 1">
        <h2 class="label">Custos</h2>
        {#if !ready}
          <Skeleton rows={2} variant="lines" />
        {:else if usage}
          <p class="figure">{money(usage.totals.cost_usd)}</p>
          {#if local(usage.totals.cost_usd)}
            <p class="mono faint small">{local(usage.totals.cost_usd)}</p>
          {/if}

          {#if usage.budget.budget_usd !== null}
            <div class="meter" class:hatch={over} aria-hidden="true">
              <span style="width: {Math.min(100, (ratio ?? 0) * 100)}%"></span>
            </div>
            <p class="small" class:over>
              {#if over}
                Orçamento estourado em {money(-(usage.budget.remaining_usd ?? 0))}
              {:else}
                {money(usage.budget.remaining_usd ?? 0)} disponíveis de {money(usage.budget.budget_usd)}
              {/if}
            </p>
          {:else}
            <p class="faint small">Sem orçamento definido.</p>
          {/if}

          <p class="mono faint small">
            {tokens.format(usage.totals.total_tokens)} tokens · {usage.totals.calls} chamadas
            {#if usage.totals.unpriced_calls}· {usage.totals.unpriced_calls} sem preço{/if}
          </p>
        {:else}
          <p class="faint small">Não foi possível ler os custos.</p>
        {/if}
        <a class="more label" href="{base}/costs">Ver custos <Icon name="arrow-right" size={10} /></a>
      </section>

      <!-- Entregas -->
      <section class="panel rise" style="--i: 2">
        <h2 class="label">Tarefas</h2>
        {#if !ready}
          <Skeleton rows={1} variant="lines" />
        {:else}
          <p class="figure">{tally.done}<span class="faint">/{tally.total}</span></p>
          <p class="mono faint small">
            concluídas{#if tally.running}&nbsp;· {tally.running} executando{/if}{#if tally.failed}&nbsp;· {tally.failed} com falha{/if}
          </p>
        {/if}
        <p class="faint small">Por sessão, na lista ao lado.</p>
      </section>

      <!-- Repositório -->
      <section class="panel rise" style="--i: 3">
        <h2 class="label">Repositório</h2>
        <a
          class="btn btn-line btn-sm download"
          href={authedUrl(`/projects/${project.id}/archive`)}
          download
          title="Arquivos versionados da branch {project.default_branch}, sem .git"
        >
          <Icon name="download" size={12} /> Baixar .zip
        </a>
        <ul class="links">
          {#if project.repo_url}
            <li>
              <a href={project.repo_url} target="_blank" rel="noopener noreferrer">
                <Icon name="external" size={11} /> Código no Gitea
              </a>
            </li>
          {/if}
          <li><a href="{base}/artifacts"><Icon name="file-text" size={11} /> Artefatos</a></li>
          <li><a href="{base}/context"><Icon name="info" size={11} /> Contexto do projeto</a></li>
        </ul>
      </section>
    </aside>
  </div>
</div>

<style>
  .dash {
    padding-top: var(--s6);
  }

  .lead {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s5);
    flex-wrap: wrap;
    padding-bottom: var(--s5);
    border-bottom: 1px solid var(--rule);
  }

  .lead-acts {
    display: flex;
    gap: var(--s3);
    flex-wrap: wrap;
  }

  .lead-acts .btn {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
  }

  .state {
    font-size: var(--t-title);
    color: var(--ink);
  }

  .help {
    margin-top: var(--s2);
    color: var(--ink-3);
  }

  .err {
    margin-top: var(--s3);
    font-size: var(--t-small);
  }

  .blocked {
    padding: 0;
    background: none;
    border: 0;
    cursor: pointer;
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

  .grid {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: var(--s9);
    padding-top: var(--s6);
    align-items: start;
  }

  .main,
  aside {
    display: flex;
    flex-direction: column;
    gap: var(--s7);
    min-width: 0;
  }

  .panel {
    border-top: 1px solid var(--rule-ink);
    padding-top: var(--s3);
  }

  .sub {
    margin-top: var(--s5);
    color: var(--ink-3);
  }

  .none {
    margin-top: var(--s3);
    font-size: var(--t-small);
  }

  /* ---- ambientes ---- */

  .envs {
    margin-top: var(--s2);
  }

  .env {
    display: grid;
    grid-template-columns: 5.5rem minmax(0, 1fr) auto;
    align-items: baseline;
    gap: var(--s4);
    padding: var(--s3) 0;
  }

  .env-name {
    color: var(--ink-3);
  }

  .env-url {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    font-size: var(--t-body);
    color: var(--ink);
    text-decoration: underline;
    text-decoration-color: var(--rule-2);
    text-underline-offset: 3px;
  }

  .env-url:hover {
    text-decoration-color: var(--ink);
  }

  .env-meta,
  .env-none {
    font-size: var(--t-micro);
  }

  .env-meta {
    display: flex;
    gap: 0.375rem;
    white-space: nowrap;
  }

  /* No ar = peso, não cor. */
  .live {
    color: var(--ink);
    font-weight: 600;
  }

  .deploys {
    margin-top: var(--s2);
  }

  .deploy {
    display: grid;
    grid-template-columns: 6.5rem 5rem minmax(0, 1fr) auto;
    gap: var(--s3);
    align-items: baseline;
    padding: var(--s2) 0;
    font-size: var(--t-micro);
    color: var(--ink-2);
  }

  .branch {
    color: var(--ink-3);
  }

  /* ---- sessões ---- */

  .sessions {
    margin-top: var(--s2);
  }

  .session {
    display: grid;
    grid-template-columns: 2.25rem minmax(0, 1fr) auto auto 6.5rem;
    align-items: baseline;
    gap: var(--s4);
    width: 100%;
    padding: var(--s3) 0;
    background: none;
    border: 0;
    text-align: left;
    color: var(--ink);
    cursor: pointer;
  }

  .session:hover .s-title {
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  .s-title.closed {
    color: var(--ink-2);
  }

  .s-count,
  .s-date {
    font-size: var(--t-micro);
  }

  .s-date {
    text-align: right;
  }

  .badge {
    padding: 0.0625rem 0.375rem;
    border: 1px solid var(--ink);
    color: var(--ink);
  }

  .badge.closed {
    border-color: var(--rule-2);
    color: var(--ink-3);
  }

  /* ---- coluna lateral ---- */

  .figure {
    margin-top: var(--s3);
    font-size: var(--t-display);
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
    color: var(--ink);
  }

  .small {
    margin-top: var(--s2);
    font-size: var(--t-micro);
  }

  .over {
    font-weight: 600;
    color: var(--ink);
  }

  .meter {
    margin-top: var(--s4);
    height: 4px;
    background: var(--rule);
  }

  .meter span {
    display: block;
    height: 100%;
    background: var(--ink);
  }

  .more {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    margin-top: var(--s4);
    color: var(--ink-3);
    transition: color var(--fast) var(--ease);
  }

  .more:hover {
    color: var(--ink);
  }

  .download {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    margin-top: var(--s3);
  }

  .links {
    margin-top: var(--s4);
    display: flex;
    flex-direction: column;
    gap: var(--s2);
    font-size: var(--t-small);
  }

  .links a {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    color: var(--ink-2);
  }

  .links a:hover {
    color: var(--ink);
  }

  @media (max-width: 900px) {
    .grid {
      grid-template-columns: 1fr;
      gap: var(--s7);
    }
  }

  @media (max-width: 640px) {
    .env {
      grid-template-columns: 1fr;
      gap: var(--s1);
    }

    .session {
      grid-template-columns: 2.25rem minmax(0, 1fr) auto;
    }

    .s-count,
    .s-date {
      display: none;
    }

    .deploy {
      grid-template-columns: auto minmax(0, 1fr) auto;
    }

    .deploy > :first-child {
      display: none;
    }
  }
</style>
