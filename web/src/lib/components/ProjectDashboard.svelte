<script lang="ts">
  import { t, i18n, formatDate, formatNumber } from '$lib/i18n/index.svelte';
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
  import { formatDuration, formatTokens, taskTotals } from '$lib/metrics';

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

  const DEPLOY_LABEL = $derived<Record<DeploymentStatus, string>>({
    PENDING: t('dashboard.deploy.PENDING'),
    BUILDING: t('dashboard.deploy.BUILDING'),
    HEALTHY: t('deploys.stage.HEALTHY'),
    FAILED: t('deploys.stage.FAILED'),
    STOPPED: t('dashboard.deploy.STOPPED')
  });

  /* O status do Coolify manda; sem registro de deploy, vale a URL fixa do projeto. */
  const environments = $derived([
    {
      key: 'production',
      label: t('deploys.env.production'),
      url: env?.production.url ?? project.production_url ?? null,
      status: env?.production.status ?? null,
      branch: env?.production.branch ?? null,
      updated: env?.production.updated_at ?? null
    },
    {
      key: 'test',
      label: t('dashboard.test'),
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

  const SESSION_LABEL = $derived<Record<SessionStatus, string>>({
    PLANNING: t('sessionStatus.PLANNING'),
    BACKLOG: t('sessionStatus.BACKLOG'),
    IN_SPRINT: t('sessionStatus.IN_SPRINT'),
    COMPLETED: t('sessionStatus.COMPLETED')
  });

  function sessionTally(id: string) {
    const own = tasks.filter((t) => t.session_id === id);
    return {
      total: own.length,
      done: own.filter((t) => t.status === 'COMPLETED').length,
      spent: taskTotals(own)
    };
  }

  /* Somatório de todas as sessões: toda tarefa pertence a uma, então é a soma das tarefas. */
  const spent = $derived(taskTotals(tasks));

  /* ---- formatação ---- */

  function money(value: number, code = 'USD'): string {
    const tiny = value !== 0 && Math.abs(value) < 0.01;
    try {
      return new Intl.NumberFormat(i18n.current, {
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

  const compactTokens = (n: number) => formatNumber(n, { notation: 'compact', maximumFractionDigits: 1 });

  function when(iso: string | null | undefined): string {
    if (!iso) return '';
    const date = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
    return formatDate(date, {
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
          {t('dashboard.sessionIn', { number: openSession.number, status: SESSION_LABEL[openSession.status].toLowerCase() })}
        </p>
        <p class="help">{openSession.title}</p>
      {:else}
        <p class="state">{t('dashboard.allClosed')}</p>
        <p class="help">{t('dashboard.allClosedHelp')}</p>
      {/if}
      {#if tally.awaiting}
        <button type="button" class="blocked label" onclick={openBlocked}>
          <span class="dot" aria-hidden="true"></span>
          {t('projects.awaitingAnalyst', { count: tally.awaiting })}
        </button>
      {/if}
    </div>

    <div class="lead-acts">
      {#if openSession}
        <button type="button" class="btn btn-line" onclick={() => openSessionPage(openSession)}>
          {t('dashboard.continueSession', { number: openSession.number })} <Icon name="arrow-right" size={11} />
        </button>
      {/if}
      <button
        type="button"
        class="btn btn-solid"
        onclick={startNextSession}
        disabled={sessionStore.creating}
      >
        <Icon name="plus" size={11} />
        {sessionStore.creating ? t('sessionPicker.creating') : t('sessionPicker.new')}
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
        <h2 class="label">{t('dashboard.published')}</h2>
        {#if !ready}
          <Skeleton rows={2} />
        {:else if published}
          <ul class="envs">
            {#each environments as e (e.key)}
              <li class="env env-{e.key}" class:hatch={e.status === 'FAILED'} class:empty={!e.url}>
                <div class="env-head">
                  <span class="env-ico">
                    <Icon name={e.key === 'production' ? 'globe' : 'flask'} size={16} />
                  </span>
                  <span class="env-name label">{e.label}</span>
                  {#if e.status}
                    <span class="env-status mono" class:live={e.status === 'HEALTHY'}>
                      <span class="env-dot" aria-hidden="true"></span>
                      {DEPLOY_LABEL[e.status]}
                    </span>
                  {/if}
                </div>
                {#if e.url}
                  <a
                    class="env-url mono truncate"
                    href={e.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={e.url}
                  >
                    {host(e.url)}
                  </a>
                  <p class="env-meta mono">
                    {#if e.branch}<span class="truncate" title={e.branch}>{e.branch}</span>{/if}
                    {#if e.updated}<span>{when(e.updated)}</span>{/if}
                  </p>
                  <a class="env-open btn btn-line btn-sm" href={e.url} target="_blank" rel="noopener noreferrer">
                    {t('common.open')} <Icon name="external" size={10} />
                  </a>
                {:else}
                  <p class="env-none">{t('dashboard.notPublished')}</p>
                {/if}
              </li>
            {/each}
          </ul>
        {:else}
          <p class="faint none">{t('dashboard.nothingPublished')}</p>
        {/if}

        {#if deployments.length}
          <h3 class="label sub">{t('dashboard.lastDeploys')}</h3>
          <ul class="deploys divide">
            {#each deployments as d (d.id)}
              <li class="deploy" class:hatch={d.status === 'FAILED'}>
                <span class="mono faint">{when(d.created_at)}</span>
                <span class="label">{d.environment === 'production' ? t('deploys.env.production') : t('dashboard.test')}</span>
                <span class="mono truncate branch" title={d.branch}>{d.branch}</span>
                <span class="mono" class:live={d.status === 'HEALTHY'}>{DEPLOY_LABEL[d.status]}</span>
              </li>
            {/each}
          </ul>
        {/if}
      </section>

      <!-- Sessões -->
      <section class="panel rise" style="--i: 2">
        <h2 class="label">{t('sessionPicker.sessions')}</h2>
        <ul class="sessions divide">
          {#each [...sessionStore.sessions].reverse() as s (s.id)}
            {@const st = sessionTally(s.id)}
            <li>
              <button type="button" class="session" onclick={() => openSessionPage(s)}>
                <span class="mono faint num">#{s.number}</span>
                <span class="s-title truncate" class:closed={s.status === 'COMPLETED'}>{s.title}</span>
                <span class="mono faint s-count">
                  {#if st.total}{t('dashboard.sessionTasks', { done: st.done, total: st.total })}{/if}
                </span>
                <span
                  class="mono faint s-spent"
                  title={t('dashboard.spentTitle')}
                >
                  {#if st.spent.seconds || st.spent.input || st.spent.output}
                    {formatDuration(st.spent.seconds)} · {formatTokens(st.spent.input)} / {formatTokens(st.spent.output)}
                  {/if}
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
        <h2 class="label">{t('projectNav.costs')}</h2>
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
                {t('dashboard.overBudget', { amount: money(-(usage.budget.remaining_usd ?? 0)) })}
              {:else}
                {t('dashboard.available', { remaining: money(usage.budget.remaining_usd ?? 0), budget: money(usage.budget.budget_usd) })}
              {/if}
            </p>
          {:else}
            <p class="faint small">{t('dashboard.noBudget')}</p>
          {/if}

          <p class="mono faint small">
            {t('dashboard.tokensCalls', { tokens: compactTokens(usage.totals.total_tokens), calls: usage.totals.calls })}
            {#if usage.totals.unpriced_calls}· {t('dashboard.unpriced', { count: usage.totals.unpriced_calls })}{/if}
          </p>
        {:else}
          <p class="faint small">{t('dashboard.costsFailed')}</p>
        {/if}
        <a class="more label" href="{base}/costs">{t('dashboard.seeCosts')} <Icon name="arrow-right" size={10} /></a>
      </section>

      <!-- Entregas -->
      <section class="panel rise" style="--i: 2">
        <h2 class="label">{t('dashboard.tasks')}</h2>
        {#if !ready}
          <Skeleton rows={1} variant="lines" />
        {:else}
          <p class="figure">{tally.done}<span class="faint">/{tally.total}</span></p>
          <p class="mono faint small">
            {t('dashboard.completed')}{#if tally.running}&nbsp;· {t('context.tallyRunning', { count: tally.running })}{/if}{#if tally.failed}&nbsp;· {t('context.tallyFailed', { count: tally.failed })}{/if}
          </p>
        {/if}
        <p class="faint small">{t('dashboard.perSession')}</p>
      </section>

      <!-- Tempo e tokens das tarefas, somados de todas as sessões -->
      <section class="panel rise" style="--i: 3">
        <h2 class="label">{t('dashboard.taskTime')}</h2>
        {#if !ready}
          <Skeleton rows={1} variant="lines" />
        {:else}
          <p class="figure">{formatDuration(spent.seconds)}</p>
          <dl class="spent mono small">
            <dt class="faint">{t('dashboard.inputTokens')}</dt>
            <dd title={formatNumber(spent.input)}>{formatTokens(spent.input)}</dd>
            <dt class="faint">{t('dashboard.outputTokens')}</dt>
            <dd title={formatNumber(spent.output)}>{formatTokens(spent.output)}</dd>
          </dl>
          <p class="faint small">{t('dashboard.spentHelp')}</p>
        {/if}
      </section>

      <!-- Repositório -->
      <section class="panel rise" style="--i: 4">
        <h2 class="label">{t('projectNav.repository')}</h2>
        <a
          class="btn btn-line btn-sm download"
          href={authedUrl(`/projects/${project.id}/archive`)}
          download
          title={t('dashboard.zipTitle', { branch: project.default_branch })}
        >
          <Icon name="download" size={12} /> {t('dashboard.downloadZip')}
        </a>
        <ul class="links">
          {#if project.repo_url}
            <li>
              <a href={project.repo_url} target="_blank" rel="noopener noreferrer">
                <Icon name="external" size={11} /> {t('dashboard.codeInGitea')}
              </a>
            </li>
          {/if}
          <li><a href="{base}/artifacts"><Icon name="file-text" size={11} /> {t('projectNav.artifacts')}</a></li>
          <li><a href="{base}/context"><Icon name="info" size={11} /> {t('dashboard.projectContext')}</a></li>
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

  /* Exceção pedida à regra de cor única, como os toasts de deploy: cada ambiente
     ganha um tom próprio — verde para produção, azul para teste. Tons pálidos,
     longe do vermelhão de --accent, que segue reservado para o exit 42. */
  .envs {
    --prod-bg: #eef8f0;
    --prod-rule: #7fb98c;
    --prod-ink: #2f7a43;
    --test-bg: #eef3fb;
    --test-rule: #8aa6d6;
    --test-ink: #2f5596;

    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--s4);
    margin-top: var(--s3);
  }

  :global(:root[data-theme='dark']) .envs {
    --prod-bg: #17261b;
    --prod-rule: #3f7a50;
    --prod-ink: #8fd0a0;
    --test-bg: #161f2c;
    --test-rule: #3f5f8f;
    --test-ink: #9dbbeb;
  }

  .env {
    --env-bg: var(--prod-bg);
    --env-rule: var(--prod-rule);
    --env-ink: var(--prod-ink);

    display: flex;
    flex-direction: column;
    gap: var(--s2);
    min-width: 0;
    padding: var(--s4);
    background-color: var(--env-bg);
    border: 1px solid var(--env-rule);
    border-top-width: 3px;
  }

  .env-test {
    --env-bg: var(--test-bg);
    --env-rule: var(--test-rule);
    --env-ink: var(--test-ink);
  }

  .env.empty {
    background-color: transparent;
    border-style: dashed;
    border-top-style: solid;
  }

  .env-head {
    display: flex;
    align-items: center;
    gap: var(--s2);
  }

  .env-ico {
    display: inline-flex;
    color: var(--env-ink);
  }

  .env-name {
    color: var(--env-ink);
    font-weight: 600;
  }

  .env-status {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    margin-left: auto;
    font-size: var(--t-micro);
    color: var(--ink-2);
  }

  .env-dot {
    width: 6px;
    height: 6px;
    border: 1px solid currentColor;
  }

  .env-status.live {
    color: var(--env-ink);
    font-weight: 600;
  }

  .env-status.live .env-dot {
    background: currentColor;
  }

  .env-url {
    margin-top: var(--s1);
    font-size: var(--t-body);
    color: var(--ink);
    text-decoration: underline;
    text-decoration-color: var(--env-rule);
    text-underline-offset: 3px;
  }

  .env-url:hover {
    text-decoration-color: var(--ink);
  }

  .env-meta {
    display: flex;
    gap: var(--s3);
    font-size: var(--t-micro);
    color: var(--ink-3);
    min-width: 0;
  }

  .env-meta span:last-child {
    white-space: nowrap;
  }

  .env-open {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    align-self: flex-start;
    margin-top: var(--s2);
  }

  .env-none {
    font-size: var(--t-small);
    color: var(--ink-3);
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
    grid-template-columns: 2.25rem minmax(0, 1fr) auto auto auto 6.5rem;
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
  .s-spent,
  .s-date {
    font-size: var(--t-micro);
  }

  .s-spent {
    white-space: nowrap;
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

  .spent {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: var(--s1) var(--s4);
    margin-top: var(--s3);
  }

  .spent dd {
    color: var(--ink);
    text-align: right;
    font-variant-numeric: tabular-nums;
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
    .envs {
      grid-template-columns: 1fr;
    }

    .session {
      grid-template-columns: 2.25rem minmax(0, 1fr) auto;
    }

    .s-count,
    .s-spent,
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
