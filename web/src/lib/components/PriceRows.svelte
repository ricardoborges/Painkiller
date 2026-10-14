<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import type { ModelPrice } from '$lib/types';
  import type { PriceRow } from '$lib/prices';
  import Icon from '$lib/components/Icon.svelte';

  /** Tabela editável de preços por modelo (USD por 1M de tokens). */
  let {
    rows = $bindable(),
    suggestions = [],
    placeholder = 'gemini-3.8-flash'
  }: {
    rows: PriceRow[];
    /** Atalhos para modelos ainda sem linha; o preço vem preenchido quando conhecido. */
    suggestions?: { model: string; price?: ModelPrice | null }[];
    placeholder?: string;
  } = $props();

  const pending = $derived(
    suggestions.filter(
      (s, i, all) =>
        all.findIndex((o) => o.model === s.model) === i &&
        !rows.some((r) => r.model.trim() === s.model)
    )
  );

  function add(model = '', price?: ModelPrice | null) {
    rows = [
      ...rows,
      {
        model,
        input: price ? String(price.input_per_mtok) : '',
        output: price ? String(price.output_per_mtok) : ''
      }
    ];
  }

  function remove(i: number) {
    rows = rows.filter((_, idx) => idx !== i);
  }
</script>

{#if rows.length > 0}
  <div class="prices">
    <span class="label">{t('costs.model')}</span>
    <span class="label">{t('costs.input')}</span>
    <span class="label">{t('costs.output')}</span>
    <span></span>
    {#each rows as row, i (i)}
      <input class="input mono" aria-label={t('costs.model')} {placeholder} bind:value={row.model} />
      <input class="input mono" aria-label={t('costs.inputPrice')} inputmode="decimal" bind:value={row.input} />
      <input class="input mono" aria-label={t('costs.outputPrice')} inputmode="decimal" bind:value={row.output} />
      <button type="button" class="btn-icon" aria-label={t('costs.removePrice')} onclick={() => remove(i)}>
        <Icon name="trash" />
      </button>
    {/each}
  </div>
{/if}

<div class="row gap">
  <button type="button" class="btn btn-line btn-sm" onclick={() => add()}>
    <Icon name="plus" size={12} /> {t('costs.addModel')}
  </button>
  {#each pending as s (s.model)}
    <button type="button" class="btn btn-quiet btn-sm mono" onclick={() => add(s.model, s.price)}>
      + {s.model || t('costs.unknown')}
    </button>
  {/each}
</div>

<style>
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

  @media (max-width: 760px) {
    .prices {
      grid-template-columns: 1.6fr 1fr 1fr auto;
      gap: var(--s2);
    }
  }
</style>
