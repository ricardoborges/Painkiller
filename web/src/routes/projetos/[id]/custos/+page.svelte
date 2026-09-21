<script lang="ts">
  import { api } from '$lib/api';
  import type {
    UsageEntry,
    UsageSettings,
    UsageSource,
    UsageSummary
  } from '$lib/types';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';

  let { data } = $props();
  const projectId = $derived(data.project.id);

  const SOURCE_LABEL: Record<UsageSource, string> = {
    ANALYSIS: 'Análise inicial',
    TASK: 'Tarefas (Aider)',
    LLM: 'Chamadas diretas'
  };

  let summary = $state<UsageSummary | null>(null);
  let records = $state<UsageEntry[]>([]);
  let loading = $state(true);
  let error = $state('');

  // Formulário de configuração: cópia editável, só vira UsageSettings no salvar.
  type PriceRow = { model: string; input: string; output: string };
  let budget = $state('');
  let currency = $state('BRL');
  let rate = $state('');
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
      const [s, r, settings] = await Promise.all([
        api.getProjectUsage(projectId),
        api.listProjectUsageRecords(projectId, 30),
        api.getUsageSettings()
      ]);
      summary = s;
      records = r;
      fillForm(settings, s.budget.budget_usd);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  function fillForm(s: UsageSettings, budgetUsd: number | null) {
    budget = budgetUsd == null ? '' : String(budgetUsd);
    currency = s.local_currency || 'BRL';
    rate = s.exchange_rate == null ? '' : String(s.exchange_rate);
    priceRows = Object.entries(s.prices).map(([model, p]) => ({
      model,
      input: String(p.input_per_mtok),
      output: String(p.output_per_mtok)
    }));
  }

  /** Aceita vírgula decimal, que é o que um analista brasileiro digita. */
  function num(text: string): number | null {
    const clean = text.trim().replace(/\s/g, '').replace(',', '.');
    if (!clean) return null;
    const n = Number(clean);
    return Number.isFinite(n) ? n : NaN;
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    saveError = '';
    const budgetN = num(budget);
    const rateN = num(rate);
    if (Number.isNaN(budgetN) || (budgetN ?? 0) < 0) {
      saveError = 'Orçamento precisa ser um número positivo.';
      return;
    }
    if (Number.isNaN(rateN) || (rateN != null && rateN <= 0)) {
      saveError = 'Câmbio precisa ser maior que zero.';
      return;
    }
    const prices: UsageSettings['prices'] = {};
    for (const row of priceRows) {
      const model = row.model.trim();
      if (!model) continue;
      const i = num(row.input) ?? 0;
      const o = num(row.output) ?? 0;
      if (Number.isNaN(i) || Number.isNaN(o) || i < 0 || o < 0) {
        saveError = `Preço inválido para ${model}.`;
        return;
      }
      prices[model] = { input_per_mtok: i, output_per_mtok: o };
    }

    saving = true;
    try {
      const [saved, savedBudget] = await Promise.all([
        api.saveUsageSettings({
          exchange_rate: rateN,
          local_currency: currency.trim().toUpperCase() || 'BRL',
          prices
        }),
        api.saveProjectBudget(projectId, budgetN)
      ]);
      fillForm(saved, savedBudget.budget_usd);
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

  function addPrice(model = '', input = '', output = '') {
    priceRows = [...priceRows, { model, input, output }];
  }

  function removePrice(i: number) {
    priceRows = priceRows.filter((_, idx) => idx !== i);
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
    const r = summary?.currency.exchange_rate;
    if (!r) return null;
    return money(usd * r, summary!.currency.local);
  }

  const compact = new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 });
  const full = new Intl.NumberFormat('pt-BR');
  const tokens = (n: number) => compact.format(n);

  function day(iso: string): string {
    const [, m, d] = iso.split('-');
    return `${d}/${m}`;
  }

  function when(iso: string): string {
    const date = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
    return date.toLocaleString('pt-BR', {
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
  const unpricedModels = $derived(
    summary?.by_model.filter(
      (m) => m.price_source !== 'settings' && !priceRows.some((r) => r.model.trim() === m.key)
    ) ?? []
  );
</script>

<div class="spread head">
  <p class="help">
    Tokens que os agentes consumiram neste projeto, quanto isso custou e quanto do orçamento dele
    ainda resta. Cada turno da análise inicial e cada execução de tarefa entram aqui assim que
    terminam.
  </p>
  <button
    type="button"
    class="btn btn-line btn-sm"
    onclick={load}
    disabled={loading}
  >
    {loading ? 'Atualizando…' : 'Atualizar'}
  </button>
</div>

{#if loading && !summary}
  <Skeleton variant="table" rows={3} />
{:else if error}
  <Placeholder kind="error" title="Não foi possível carregar os custos" detail={error}>
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={load}>Tentar de novo</button>
    {/snippet}
  </Placeholder>
{:else if summary}
  <!-- ---- números principais ---- -->
  <section class="stats" aria-label="Resumo">
    <div class="stat">
      <span class="label">Crédito disponível</span>
      {#if summary.budget.remaining_usd == null}
        <p class="big mono faint">—</p>
        <p class="help">
          Nenhum orçamento para este projeto. <a class="link" href="#configuracao">Definir orçamento</a>
        </p>
      {:else}
        <p class="big mono" class:over>{money(summary.budget.remaining_usd)}</p>
        <p class="help mono">
          {#if local(summary.budget.remaining_usd)}{local(summary.budget.remaining_usd)} ·
          {/if}de {money(summary.budget.budget_usd ?? 0)}
        </p>
      {/if}
    </div>

    <div class="stat">
      <span class="label">Gasto no projeto</span>
      <p class="big mono">{money(summary.totals.cost_usd)}</p>
      <p class="help mono">
        {local(summary.totals.cost_usd) ?? 'defina o câmbio para ver em moeda local'}
      </p>
    </div>

    <div class="stat">
      <span class="label">Tokens</span>
      <p class="big mono" title="{full.format(summary.totals.total_tokens)} tokens">
        {tokens(summary.totals.total_tokens)}
      </p>
      <p class="help mono">
        {tokens(summary.totals.input_tokens)} entrada · {tokens(summary.totals.output_tokens)} saída
        · {full.format(summary.totals.calls)} registros
      </p>
    </div>
  </section>

  {#if ratio != null}
    <div class="meter-wrap">
      <div
        class="meter"
        class:full={over}
        role="meter"
        aria-label="Orçamento consumido"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(Math.min(ratio, 1) * 100)}
      >
        <span class="fill" style="width: {Math.min(ratio, 1) * 100}%"></span>
      </div>
      <p class="meter-note mono">
        {#if over}
          <strong>Orçamento estourado</strong> em {money(-(summary.budget.remaining_usd ?? 0))}
        {:else}
          {(ratio * 100).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}% do orçamento consumido
        {/if}
      </p>
    </div>
  {/if}

  {#if summary.totals.unpriced_calls > 0}
    <p class="notice help">
      <Icon name="alert" size={12} />
      <span>
        {summary.totals.unpriced_calls}
        {summary.totals.unpriced_calls === 1 ? 'registro está' : 'registros estão'} fora do gasto
        total porque o modelo não tem preço conhecido. Cadastre o preço em
        <a class="link" href="#configuracao">Configuração</a> e o valor é recalculado.
      </span>
    </p>
  {/if}

  <!-- ---- gasto diário ---- -->
  <section class="block">
    <div class="spread">
      <h2 class="label section-title">Gasto por dia — últimos 30 dias</h2>
      <span class="help mono">{money(dailyTotal)} no período</span>
    </div>
    {#if dailyMax === 0}
      <p class="help">Nenhum gasto com preço conhecido no período.</p>
    {:else}
      <div class="chart" role="img" aria-label="Gasto diário em dólares nos últimos 30 dias">
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
              aria-label="{day(d.date)}: {money(d.cost_usd)}, {full.format(d.tokens)} tokens"
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
          <span>hoje</span>
        </div>
      </div>
    {/if}
  </section>

  <!-- ---- quebras ---- -->
  <section class="block">
    <h2 class="label section-title">Por etapa</h2>
    <table class="table">
      <thead><tr><th>Etapa</th><th class="num">Tokens</th><th class="num">Custo</th></tr></thead>
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
    <h2 class="label section-title">Por modelo</h2>
    {#if summary.by_model.length === 0}
      <p class="help">Nenhum consumo registrado ainda.</p>
    {:else}
      <div class="scroll">
      <table class="table">
        <thead>
          <tr>
            <th>Modelo</th>
            <th class="num">Entrada</th>
            <th class="num">Saída</th>
            <th class="num">Preço / 1M</th>
            <th class="num">Custo</th>
          </tr>
        </thead>
        <tbody>
          {#each summary.by_model as m (m.key)}
            <tr>
              <td class="mono nowrap">{m.key || 'desconhecido'}</td>
              <td class="num mono">{tokens(m.input_tokens)}</td>
              <td class="num mono">{tokens(m.output_tokens)}</td>
              <td class="num mono">
                {#if m.price}
                  {money(m.price.input_per_mtok)} / {money(m.price.output_per_mtok)}
                  <span class="tag">{m.price_source === 'settings' ? 'seu' : 'catálogo'}</span>
                {:else}
                  <span class="tag unpriced">sem preço</span>
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
      <p class="help foot">
        Preço cadastrado por você vence; sem ele vale o custo que o Aider ou o agente reportou,
        e por último o catálogo do LiteLLM. * inclui registros sem preço, fora do custo.
      </p>
    {/if}
  </section>

  <!-- ---- registros recentes ---- -->
  <section class="block">
    <h2 class="label section-title">Registros recentes</h2>
    {#if records.length === 0}
      <p class="help">
        Nada registrado ainda. O consumo aparece aqui depois do primeiro turno da análise inicial
        ou da primeira tarefa despachada.
      </p>
    {:else}
      <div class="scroll">
        <table class="table">
          <thead>
            <tr>
              <th>Quando</th>
              <th>Etapa</th>
              <th>Tarefa</th>
              <th>Modelo</th>
              <th class="num">Entrada</th>
              <th class="num">Saída</th>
              <th class="num">Custo</th>
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
    <h2 class="label section-title">Configuração</h2>
    <p class="help intro">
      Google Gemini, OpenAI, Anthropic e NVIDIA não informam saldo por API. O crédito disponível
      é o orçamento que você define para este projeto menos o que ele já gastou.
    </p>

    <form class="settings" onsubmit={save}>
      <div class="fields">
        <div class="field">
          <label for="budget">Orçamento do projeto (USD)</label>
          <input id="budget" class="input mono" inputmode="decimal" placeholder="ex.: 50" bind:value={budget} />
        </div>
      </div>

      <h3 class="label sub-title">Compartilhado por todos os projetos</h3>
      <p class="help">
        Câmbio e preço de modelo não mudam de um projeto para outro: alterar aqui recalcula o
        custo de todos.
      </p>
      <div class="fields">
        <div class="field">
          <label for="currency">Moeda local</label>
          <input id="currency" class="input mono" maxlength="5" bind:value={currency} />
        </div>
        <div class="field">
          <label for="rate">Câmbio (1 USD =)</label>
          <input id="rate" class="input mono" inputmode="decimal" placeholder="ex.: 5,40" bind:value={rate} />
        </div>
      </div>

      <h3 class="label sub-title">Preços por modelo (USD por 1 milhão de tokens)</h3>
      {#if priceRows.length > 0}
        <div class="prices">
          <span class="label">Modelo</span>
          <span class="label">Entrada</span>
          <span class="label">Saída</span>
          <span></span>
          {#each priceRows as row, i (i)}
            <input class="input mono" aria-label="Modelo" placeholder="gemini-3.8-flash" bind:value={row.model} />
            <input class="input mono" aria-label="Preço de entrada" inputmode="decimal" bind:value={row.input} />
            <input class="input mono" aria-label="Preço de saída" inputmode="decimal" bind:value={row.output} />
            <button type="button" class="btn-icon" aria-label="Remover preço" onclick={() => removePrice(i)}>
              <Icon name="trash" />
            </button>
          {/each}
        </div>
      {/if}

      <div class="row gap">
        <button type="button" class="btn btn-line btn-sm" onclick={() => addPrice()}>
          <Icon name="plus" size={12} /> Adicionar modelo
        </button>
        {#each unpricedModels as m (m.key)}
          <button
            type="button"
            class="btn btn-quiet btn-sm mono"
            onclick={() =>
              addPrice(
                m.key,
                m.price ? String(m.price.input_per_mtok) : '',
                m.price ? String(m.price.output_per_mtok) : ''
              )}
          >
            + {m.key || 'desconhecido'}
          </button>
        {/each}
      </div>

      <div class="row gap actions">
        <button type="submit" class="btn btn-solid" disabled={saving}>
          {saving ? 'Salvando…' : 'Salvar configuração'}
        </button>
        {#if saveError}
          <span class="field-error">{saveError}</span>
        {:else if savedAt}
          <span class="help row gap-s"><Icon name="check" size={12} /> Salvo e recalculado</span>
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
    background: #2c2c32;
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

  .prices {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr auto;
    gap: var(--s2) var(--s3);
    align-items: center;
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

    .prices {
      grid-template-columns: 1.6fr 1fr 1fr auto;
      gap: var(--s2);
    }
  }
</style>
