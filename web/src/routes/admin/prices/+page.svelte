<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import { api } from '$lib/api';
  import { HARNESS_MODELS, HARNESS_NAMES, type HarnessType, type UsageSettings } from '$lib/types';
  import { fromRows, parseAmount, toRows, type PriceRow } from '$lib/prices';
  import AdminTabs from '$lib/components/AdminTabs.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import PriceRows from '$lib/components/PriceRows.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';

  const HARNESSES = Object.keys(HARNESS_NAMES) as HarnessType[];

  let loaded = $state(false);
  let error = $state('');

  let currency = $state('BRL');
  let rate = $state('');
  let tables = $state<Record<HarnessType, PriceRow[]>>({
    agy_superpowers: [],
    deepseek_superpowers: [],
    maki_superpowers: [],
    unreal_superpowers: []
  });
  /** Lista anterior aos preços por harness: segue valendo para qualquer um. */
  let shared = $state<PriceRow[]>([]);

  let saving = $state(false);
  let saveError = $state('');
  let savedAt = $state<Date | null>(null);

  $effect(() => {
    load();
  });

  async function load() {
    error = '';
    try {
      fill(await api.getUsageSettings());
      loaded = true;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  function fill(s: UsageSettings) {
    currency = s.local_currency || 'BRL';
    rate = s.exchange_rate == null ? '' : String(s.exchange_rate);
    for (const h of HARNESSES) tables[h] = toRows(s.harness_prices?.[h]);
    shared = toRows(s.prices);
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    saveError = '';
    const rateN = parseAmount(rate);
    if (Number.isNaN(rateN) || (rateN != null && rateN <= 0)) {
      saveError = t('costs.rateInvalid');
      return;
    }
    const harness_prices: UsageSettings['harness_prices'] = {};
    for (const h of HARNESSES) {
      const { prices, invalid } = fromRows(tables[h]);
      if (invalid) {
        saveError = t('costs.priceInvalid', { model: `${HARNESS_NAMES[h]} · ${invalid}` });
        return;
      }
      harness_prices[h] = prices;
    }
    const { prices, invalid } = fromRows(shared);
    if (invalid) {
      saveError = t('costs.priceInvalid', { model: invalid });
      return;
    }

    saving = true;
    try {
      fill(
        await api.saveUsageSettings({
          exchange_rate: rateN,
          local_currency: currency.trim().toUpperCase() || 'BRL',
          prices,
          harness_prices
        })
      );
      savedAt = new Date();
    } catch (err) {
      saveError = err instanceof Error ? err.message : String(err);
    } finally {
      saving = false;
    }
  }
</script>

<svelte:head><title>{t('adminTabs.prices')} — {t('admin.title')} — Painkiller</title></svelte:head>

<header class="head spread">
  <div>
    <h1 class="display">{t('admin.title')}</h1>
    <p class="lede sub">{t('adminPrices.lede')}</p>
  </div>
</header>

<AdminTabs />

<hr class="rule rule-ink" />

{#if error}
  <Placeholder kind="error" title={t('costs.loadFailed')} detail={error}>
    {#snippet action()}
      <button type="button" class="btn btn-solid" onclick={load}>{t('common.retry')}</button>
    {/snippet}
  </Placeholder>
{:else if !loaded}
  <Skeleton rows={6} />
{:else}
  <form class="form" onsubmit={save}>
    <section>
      <h2 class="title">{t('adminPrices.currency')}</h2>
      <p class="help">{t('adminPrices.currencyHelp')}</p>
      <div class="fields">
        <div class="field">
          <label for="currency">{t('costs.localCurrency')}</label>
          <input id="currency" class="input mono" maxlength="5" bind:value={currency} />
        </div>
        <div class="field">
          <label for="rate">{t('costs.rate')}</label>
          <input id="rate" class="input mono" inputmode="decimal" placeholder={t('costs.ratePlaceholder')} bind:value={rate} />
        </div>
      </div>
    </section>

    <p class="help">{t('adminPrices.inheritHelp')}</p>

    {#each HARNESSES as h (h)}
      <section>
        <h2 class="title">{HARNESS_NAMES[h]}</h2>
        <PriceRows
          bind:rows={tables[h]}
          placeholder={HARNESS_MODELS[h][0]}
          suggestions={HARNESS_MODELS[h].map((model) => ({ model }))}
        />
      </section>
    {/each}

    {#if shared.length > 0}
      <section>
        <h2 class="title">{t('adminPrices.anyHarness')}</h2>
        <p class="help">{t('adminPrices.anyHarnessHelp')}</p>
        <PriceRows bind:rows={shared} />
      </section>
    {/if}

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
{/if}

<style>
  .head {
    padding: var(--s7) 0 0;
  }

  .sub {
    margin-top: var(--s2);
  }

  .form {
    display: flex;
    flex-direction: column;
    gap: var(--s7);
    max-width: 44rem;
    padding: var(--s6) 0 var(--s9);
  }

  section {
    display: flex;
    flex-direction: column;
    gap: var(--s4);
  }

  .form > .help {
    max-width: var(--measure);
  }

  .fields {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: var(--s4);
  }

  .gap {
    gap: var(--s3);
    flex-wrap: wrap;
  }

  .gap-s {
    gap: var(--s2);
  }

  @media (max-width: 760px) {
    .fields {
      grid-template-columns: 1fr;
    }
  }
</style>
