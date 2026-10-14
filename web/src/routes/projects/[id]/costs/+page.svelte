<script lang="ts">
  import { t, tp, i18n, formatDate, formatNumber } from '$lib/i18n/index.svelte';
  import { api } from '$lib/api';
  import { auth } from '$lib/stores/auth.svelte';
  import {
    HARNESS_NAMES,
    type ModelPrice,
    type ProjectPrices,
    type UsageEntry,
    type UsageSource,
    type UsageSummary
  } from '$lib/types';
  import { fromRows, parseAmount, toRows, type PriceRow } from '$lib/prices';
  import Icon from '$lib/components/Icon.svelte';
  import PriceRows from '$lib/components/PriceRows.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';

  let { data } = $props();
  const projectId = $derived(data.project.id);

  const SOURCE_LABEL = $derived<Record<UsageSource, string>>({
    ANALYSIS: t('context.initialAnalysis'),
    TASK: t('costs.source.TASK'),
    LLM: t('costs.source.LLM')
  });

  let summary = $state<UsageSummary | null>(null);
  let records = $state<UsageEntry[]>([]);
  let loading = $state(true);
  let error = $state('');

  // Formulário: orçamento e preços que este projeto sobrescreve; o resto vem do admin.
  let budget = $state('');
  let pricing = $state<ProjectPrices | null>(null);
  let priceRows = $state<PriceRow[]>([]);
  let saving = $state(false);
  let saveError = $state('');
  let savedAt = $state<Date | null>(null);

  let hover = $state<number | null>(null);

  $effect(() => {
    load();
  });

  async function load() {
    loading = true;
    error = '';
    try {
      const [s, r, p] = await Promise.all([
        api.getProjectUsage(projectId),
        api.listProjectUsageRecords(projectId, 30),
        api.getProjectPrices(projectId)
      ]);
      summary = s;
      records = r;
      fillForm(p, s.budget.budget_usd);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  function fillForm(p: ProjectPrices, budgetUsd: number | null) {
    budget = budgetUsd == null ? '' : String(budgetUsd);
    pricing = p;
    priceRows = toRows(p.overrides);
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    saveError = '';
    const budgetN = parseAmount(budget);
    if (Number.isNaN(budgetN) || (budgetN ?? 0) < 0) {
      saveError = t('costs.budgetInvalid');
      return;
    }
    const { prices, invalid } = fromRows(priceRows);
    if (invalid) {
      saveError = t('costs.priceInvalid', { model: invalid });
      return;
    }

    saving = true;
    try {
      const [savedPrices, savedBudget] = await Promise.all([
        api.saveProjectPrices(projectId, prices),
        api.saveProjectBudget(projectId, budgetN)
      ]);
      fillForm(savedPrices, savedBudget.budget_usd);
      savedAt = new Date();
      // Preço novo muda o custo de tudo que já foi gasto: recalcula.
      const [s, r] = await Promise.all([
        api.getProjectUsage(projectId),
        api.listProjectUsageRecords(projectId, 30)
      ]);
      summary = s;
      records = r;
    } catch (e) {
      saveError = e instanceof Error ? e.message : String(e);
    } finally {
      saving = false;
    }
  }

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
    const r = summary?.currency.exchange_rate;
    if (!r) return null;
    return money(usd * r, summary!.currency.local);
  }

  const full = { format: (n: number) => formatNumber(n) };
  const tokens = (n: number) => formatNumber(n, { notation: 'compact', maximumFractionDigits: 1 });

  function day(iso: string): string {
    const [y, m, d] = iso.split('-').map(Number);
    return formatDate(new Date(y, m - 1, d), { day: '2-digit', month: '2-digit' });
  }

  function when(iso: string): string {
    const date = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
    return formatDate(date, {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  /* ---- derivados ---- */

  const ratio = $derived(summary?.budget.used_ratio ?? null);
  const over = $derived((summary?.budget.remaining_usd ?? 0) < 0);
  const dailyMax = $derived(Math.max(0, ...(summary?.daily.map((d) => d.cost_usd) ?? [])));
  const dailyTotal = $derived(summary?.daily.reduce((a, d) => a + d.cost_usd, 0) ?? 0);
  const inheritedRows = $derived(Object.entries(pricing?.inherited ?? {}));
  const overridden = $derived(new Set(priceRows.map((r) => r.model.trim())));
  /** Atalhos: o modelo do projeto, os herdados e os que já consumiram tokens. */
  const suggestions = $derived<{ model: string; price?: ModelPrice | null }[]>([
    ...(pricing ? [{ model: pricing.model, price: pricing.inherited[pricing.model] }] : []),
    ...inheritedRows.map(([model, price]) => ({ model, price })),
    ...(summary?.by_model ?? []).filter((m) => m.key).map((m) => ({ model: m.key, price: m.price }))
  ]);
</script>

<div class="spread head">
  <p class="help">{t('costs.lede')}</p>
  <button
    type="button"
    class="btn btn-line btn-sm"
    onclick={load}
    disabled={loading}
  >
    {loading ? t('costs.refreshing') : t('costs.refresh')}
  </button>
</div>

{#if loading && !summary}
  <Skeleton variant="table" rows={3} />
{:else if error}
  <Placeholder kind="error" title={t('costs.loadFailed')} detail={error}>
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={load}>{t('common.retry')}</button>
    {/snippet}
  </Placeholder>
{:else if summary}
  <!-- ---- números principais ---- -->
  <section class="stats" aria-label={t('costs.summary')}>
    <div class="stat">
      <span class="label">{t('costs.credit')}</span>
      {#if summary.budget.remaining_usd == null}
        <p class="big mono faint">—</p>
        <p class="help">
          {t('costs.noBudget')} <a class="link" href="#configuracao">{t('costs.setBudget')}</a>
        </p>
      {:else}
        <p class="big mono" class:over>{money(summary.budget.remaining_usd)}</p>
        <p class="help mono">
          {#if local(summary.budget.remaining_usd)}{local(summary.budget.remaining_usd)} ·
          {/if}{t('costs.of', { budget: money(summary.budget.budget_usd ?? 0) })}
        </p>
      {/if}
    </div>

    <div class="stat">
      <span class="label">{t('costs.spent')}</span>
      <p class="big mono">{money(summary.totals.cost_usd)}</p>
      <p class="help mono">
        {local(summary.totals.cost_usd) ?? t('costs.setRate')}
      </p>
    </div>

    <div class="stat">
      <span class="label">Tokens</span>
      <p class="big mono" title={`${full.format(summary.totals.total_tokens)} tokens`}>
        {tokens(summary.totals.total_tokens)}
      </p>
      <p class="help mono">
        {t('costs.tokensBreakdown', { input: tokens(summary.totals.input_tokens), output: tokens(summary.totals.output_tokens), records: full.format(summary.totals.calls) })}
      </p>
    </div>
  </section>

  {#if ratio != null}
    <div class="meter-wrap">
      <div
        class="meter"
        class:full={over}
        role="meter"
        aria-label={t('costs.budgetUsed')}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(Math.min(ratio, 1) * 100)}
      >
        <span class="fill" style="width: {Math.min(ratio, 1) * 100}%"></span>
      </div>
      <p class="meter-note mono">
        {#if over}
          {t('dashboard.overBudget', { amount: money(-(summary.budget.remaining_usd ?? 0)) })}
        {:else}
          {t('costs.percentUsed', { percent: formatNumber(ratio * 100, { maximumFractionDigits: 1 }) })}
        {/if}
      </p>
    </div>
  {/if}

  {#if summary.totals.unpriced_calls > 0}
    <p class="notice help">
      <Icon name="alert" size={12} />
      <span>
        {tp('costs.unpricedNotice', summary.totals.unpriced_calls)}
        <a class="link" href="#configuracao">{t('costs.configuration')}</a>{t('costs.unpricedNoticeTail')}
      </span>
    </p>
  {/if}

  <!-- ---- gasto diário ---- -->
  <section class="block">
    <div class="spread">
      <h2 class="label section-title">{t('costs.daily')}</h2>
      <span class="help mono">{t('costs.inPeriod', { amount: money(dailyTotal) })}</span>
    </div>
    {#if dailyMax === 0}
      <p class="help">{t('costs.noDaily')}</p>
    {:else}
      <div class="chart" role="img" aria-label={t('costs.dailyAria')}>
        <span class="y-max mono">{money(dailyMax)}</span>
        <div class="bars" onmouseleave={() => (hover = null)} role="presentation">
          {#each summary.daily as d, i (d.date)}
            <button
              type="button"
              class="col"
              class:active={hover === i}
              onmouseenter={() => (hover = i)}
              onfocus={() => (hover = i)}
              onblur={() => (hover = null)}
              aria-label={`${day(d.date)}: ${money(d.cost_usd)}, ${full.format(d.tokens)} tokens`}
            >
              <span class="bar" style="height: {(d.cost_usd / dailyMax) * 100}%"></span>
              {#if hover === i}
                <span class="tip mono" class:left={i > 22} class:right={i < 7}>
                  <strong>{day(d.date)}</strong>
                  {money(d.cost_usd)}<br />{tokens(d.tokens)} tokens
                </span>
              {/if}
            </button>
          {/each}
        </div>
        <div class="x mono">
          <span>{day(summary.daily[0].date)}</span>
          <span>{day(summary.daily[14].date)}</span>
          <span>{t('costs.today')}</span>
        </div>
      </div>
    {/if}
  </section>

  <!-- ---- quebras ---- -->
  <section class="block">
    <h2 class="label section-title">{t('costs.byStep')}</h2>
    <table class="table">
      <thead><tr><th>{t('costs.step')}</th><th class="num">Tokens</th><th class="num">{t('costs.cost')}</th></tr></thead>
      <tbody>
        {#each summary.by_source as s (s.key)}
          <tr class:faint={s.calls === 0}>
            <td>{SOURCE_LABEL[s.key]}</td>
            <td class="num mono">{tokens(s.input_tokens + s.output_tokens)}</td>
            <td class="num mono">
              {money(s.cost_usd)}{#if s.unpriced_calls > 0}<span class="faint">*</span>{/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </section>

  <section class="block">
    <h2 class="label section-title">{t('costs.byModel')}</h2>
    {#if summary.by_model.length === 0}
      <p class="help">{t('costs.noUsage')}</p>
    {:else}
      <div class="scroll">
      <table class="table">
        <thead>
          <tr>
            <th>{t('costs.model')}</th>
            <th class="num">{t('costs.input')}</th>
            <th class="num">{t('costs.output')}</th>
            <th class="num">{t('costs.pricePerM')}</th>
            <th class="num">{t('costs.cost')}</th>
          </tr>
        </thead>
        <tbody>
          {#each summary.by_model as m (m.key)}
            <tr>
              <td class="mono nowrap">{m.key || t('costs.unknown')}</td>
              <td class="num mono">{tokens(m.input_tokens)}</td>
              <td class="num mono">{tokens(m.output_tokens)}</td>
              <td class="num mono">
                {#if m.price}
                  {money(m.price.input_per_mtok)} / {money(m.price.output_per_mtok)}
                  <span class="tag">
                    {m.price_source === 'project'
                      ? t('costs.priceProject')
                      : m.price_source === 'settings'
                        ? t('costs.priceAdmin')
                        : t('costs.catalog')}
                  </span>
                {:else}
                  <span class="tag unpriced">{t('costs.noPrice')}</span>
                {/if}
              </td>
              <td class="num mono">
                {money(m.cost_usd)}{#if m.unpriced_calls > 0}<span class="faint">*</span>{/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
      </div>
      <p class="help foot">{t('costs.priceOrder')}</p>
    {/if}
  </section>

  <!-- ---- registros recentes ---- -->
  <section class="block">
    <h2 class="label section-title">{t('costs.recent')}</h2>
    {#if records.length === 0}
      <p class="help">{t('costs.noRecords')}</p>
    {:else}
      <div class="scroll">
        <table class="table">
          <thead>
            <tr>
              <th>{t('costs.when')}</th>
              <th>{t('costs.step')}</th>
              <th>{t('costs.task')}</th>
              <th>{t('costs.model')}</th>
              <th class="num">{t('costs.input')}</th>
              <th class="num">{t('costs.output')}</th>
              <th class="num">{t('costs.cost')}</th>
            </tr>
          </thead>
          <tbody>
            {#each records as r (r.id)}
              <tr>
                <td class="mono nowrap">{when(r.created_at)}</td>
                <td class="nowrap">{SOURCE_LABEL[r.source]}</td>
                <td class="mono nowrap">{r.task_id ?? '—'}</td>
                <td class="mono nowrap">{r.model || '—'}</td>
                <td class="num mono">{full.format(r.input_tokens)}</td>
                <td class="num mono">{full.format(r.output_tokens)}</td>
                <td class="num mono">{r.cost_usd == null ? '—' : money(r.cost_usd)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>

  <!-- ---- configuração ---- -->
  <section class="block" id="configuracao">
    <h2 class="label section-title">{t('costs.configuration')}</h2>
    <p class="help intro">{t('costs.noBalanceApi')}</p>

    <form class="settings" onsubmit={save}>
      <div class="fields">
        <div class="field">
          <label for="budget">{t('costs.projectBudget')}</label>
          <input id="budget" class="input mono" inputmode="decimal" placeholder={t('costs.budgetPlaceholder')} bind:value={budget} />
        </div>
      </div>

      <h3 class="label sub-title">{t('costs.pricesTitle')}</h3>
      <p class="help">
        {t('costs.inheritHelp', { harness: pricing ? HARNESS_NAMES[pricing.harness] : '' })}
        {#if auth.isAdmin}<a class="link" href="/admin/prices">{t('costs.editAdminPrices')}</a>{/if}
      </p>
      {#if inheritedRows.length === 0}
        <p class="help faint">{t('costs.noInherited')}</p>
      {:else}
        <table class="table inherited">
          <thead>
            <tr>
              <th>{t('costs.model')}</th>
              <th class="num">{t('costs.input')}</th>
              <th class="num">{t('costs.output')}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {#each inheritedRows as [model, price] (model)}
              <tr class:faint={overridden.has(model)}>
                <td class="mono nowrap">{model}</td>
                <td class="num mono">{money(price.input_per_mtok)}</td>
                <td class="num mono">{money(price.output_per_mtok)}</td>
                <td class="num">
                  {#if overridden.has(model)}<span class="tag">{t('costs.overridden')}</span>{/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}

      <h3 class="label sub-title">{t('costs.overridesTitle')}</h3>
      <p class="help">{t('costs.overridesHelp')}</p>
      <PriceRows bind:rows={priceRows} {suggestions} placeholder={pricing?.model} />

      <div class="row gap actions">
        <button type="submit" class="btn btn-solid" disabled={saving}>
          {saving ? t('common.saving') : t('costs.saveSettings')}
        </button>
        {#if saveError}
          <span class="field-error">{saveError}</span>
        {:else if savedAt}
          <span class="help row gap-s"><Icon name="check" size={12} /> {t('costs.savedRecalculated')}</span>
        {/if}
      </div>
    </form>
  </section>
{/if}

<style>
  .head {
    padding-top: var(--s6);
    margin-bottom: var(--s6);
  }

  .head .help {
    max-width: var(--measure);
  }

  .link {
    text-decoration: underline;
    text-underline-offset: 2px;
    text-decoration-color: var(--ink-4);
  }

  .link:hover {
    text-decoration-color: var(--ink);
  }

  /* ---- números principais ---- */

  .stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    border-bottom: 1px solid var(--rule);
  }

  .stat {
    padding: var(--s5) var(--s5) var(--s5) 0;
    display: flex;
    flex-direction: column;
    gap: var(--s2);
    min-width: 0;
  }

  .stat + .stat {
    padding-left: var(--s5);
    border-left: 1px solid var(--rule);
  }

  .big {
    font-size: var(--t-display);
    font-weight: 500;
    letter-spacing: -0.03em;
    line-height: 1.05;
  }

  /* Estourar o orçamento é grave, mas não é "aguardando analista": peso, não cor. */
  .big.over {
    font-weight: 700;
  }

  .meter-wrap {
    padding: var(--s4) 0;
    border-bottom: 1px solid var(--rule);
  }

  .meter {
    height: 6px;
    background: var(--paper-sunk);
    border: 1px solid var(--rule-2);
    position: relative;
  }

  .fill {
    position: absolute;
    inset: 0 auto 0 0;
    background: var(--ink);
    transition: width var(--slow) var(--ease);
  }

  .meter.full .fill {
    background: repeating-linear-gradient(
      45deg,
      var(--ink) 0,
      var(--ink) 2px,
      var(--paper) 2px,
      var(--paper) 5px
    );
  }

  .meter-note {
    margin-top: var(--s2);
    font-size: var(--t-micro);
    color: var(--ink-2);
  }

  .notice {
    display: flex;
    align-items: flex-start;
    gap: var(--s2);
    padding: var(--s3) 0;
    border-bottom: 1px solid var(--rule);
    max-width: none;
  }

  .notice :global(svg) {
    margin-top: 0.15rem;
  }

  /* ---- seções ---- */

  .block {
    padding-top: var(--s6);
  }

  .section-title {
    display: block;
    color: var(--ink-2);
    margin-bottom: var(--s3);
  }

  .table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--t-small);
  }

  .table th {
    text-align: left;
    font-size: var(--t-label);
    font-weight: 500;
    letter-spacing: 0.085em;
    text-transform: uppercase;
    color: var(--ink-3);
    padding: var(--s2) var(--s3) var(--s2) 0;
    border-bottom: 1px solid var(--rule-ink);
  }

  .table td {
    padding: var(--s2) var(--s3) var(--s2) 0;
    border-bottom: 1px solid var(--rule);
    vertical-align: baseline;
  }

  .table .num {
    text-align: right;
    white-space: nowrap;
  }

  .table th:last-child,
  .table td:last-child {
    padding-right: 0;
  }

  .nowrap {
    white-space: nowrap;
  }

  .scroll {
    overflow-x: auto;
  }

  .tag {
    margin-left: var(--s2);
    font-size: var(--t-label);
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--ink-3);
  }

  .tag.unpriced {
    margin-left: 0;
    padding: 0 0.3rem;
    color: var(--ink);
    border: 1px solid var(--ink);
  }

  .foot {
    margin-top: var(--s3);
    max-width: var(--measure);
  }

  /* ---- gráfico diário ---- */

  .chart {
    position: relative;
    padding-top: var(--s4);
  }

  .y-max {
    position: absolute;
    top: 0;
    left: 0;
    font-size: var(--t-label);
    color: var(--ink-3);
  }

  .bars {
    display: grid;
    grid-template-columns: repeat(30, 1fr);
    height: 8rem;
    border-top: 1px dashed var(--rule);
    border-bottom: 1px solid var(--rule-ink);
  }

  /* Coluna inteira é o alvo de hover, bem maior que a barra. */
  .col {
    position: relative;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    height: 100%;
    padding: 0 1px;
    background: none;
    border: 0;
    cursor: default;
  }

  .col:hover,
  .col.active {
    background: var(--paper-sunk);
  }

  .bar {
    display: block;
    width: 100%;
    max-width: 14px;
    min-height: 0;
    background: var(--ink);
  }

  .col.active .bar {
    background: var(--ink-hover);
  }

  .tip {
    position: absolute;
    bottom: calc(100% + var(--s2));
    left: 50%;
    transform: translateX(-50%);
    z-index: 5;
    padding: var(--s2) var(--s3);
    background: var(--paper);
    border: 1px solid var(--rule-ink);
    font-size: var(--t-micro);
    line-height: 1.45;
    text-align: left;
    white-space: nowrap;
    pointer-events: none;
  }

  .tip.left {
    left: auto;
    right: 0;
    transform: none;
  }

  .tip.right {
    left: 0;
    transform: none;
  }

  .tip strong {
    display: block;
    font-weight: 600;
  }

  .x {
    display: flex;
    justify-content: space-between;
    margin-top: var(--s2);
    font-size: var(--t-label);
    color: var(--ink-3);
  }

  /* ---- configuração ---- */

  .intro {
    max-width: var(--measure);
    margin-bottom: var(--s5);
  }

  .settings {
    display: flex;
    flex-direction: column;
    gap: var(--s4);
    max-width: 44rem;
  }

  .fields {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--s4);
  }

  .sub-title {
    margin-top: var(--s3);
  }

  .settings .help {
    max-width: var(--measure);
  }

  .gap {
    gap: var(--s3);
    flex-wrap: wrap;
  }

  .gap-s {
    gap: var(--s2);
  }

  .actions {
    padding-top: var(--s3);
  }

  @media (max-width: 760px) {
    .stats,
    .fields {
      grid-template-columns: 1fr;
    }

    .stat,
    .stat + .stat {
      padding-left: 0;
      border-left: 0;
    }

    .stat + .stat {
      border-top: 1px solid var(--rule);
    }
  }
</style>
