import type { ModelPrice } from '$lib/types';

/** Linha editável de preço: texto até salvar, para aceitar vírgula decimal. */
export type PriceRow = { model: string; input: string; output: string };

/** Aceita vírgula decimal, que é o que um analista brasileiro digita (e ponto, em inglês). */
export function parseAmount(text: string): number | null {
  const clean = text.trim().replace(/\s/g, '').replace(',', '.');
  if (!clean) return null;
  const n = Number(clean);
  return Number.isFinite(n) ? n : NaN;
}

export function toRows(prices: Record<string, ModelPrice> | undefined): PriceRow[] {
  return Object.entries(prices ?? {}).map(([model, p]) => ({
    model,
    input: String(p.input_per_mtok),
    output: String(p.output_per_mtok)
  }));
}

/** Converte as linhas; `invalid` traz o modelo da primeira linha com preço inválido. */
export function fromRows(
  rows: PriceRow[]
): { prices: Record<string, ModelPrice>; invalid: string | null } {
  const prices: Record<string, ModelPrice> = {};
  for (const row of rows) {
    const model = row.model.trim();
    if (!model) continue;
    const i = parseAmount(row.input) ?? 0;
    const o = parseAmount(row.output) ?? 0;
    if (Number.isNaN(i) || Number.isNaN(o) || i < 0 || o < 0) return { prices, invalid: model };
    prices[model] = { input_per_mtok: i, output_per_mtok: o };
  }
  return { prices, invalid: null };
}
