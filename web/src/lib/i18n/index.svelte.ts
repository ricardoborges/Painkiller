/**
 * Idioma da interface. O catálogo pt-BR é a fonte: define as chaves e o
 * tipo que todo outro catálogo precisa cumprir (svelte-check acusa a chave
 * que faltar). A escolha fica no navegador; sem escolha, vale o idioma do
 * navegador quando é um dos suportados, senão pt-BR.
 *
 * `t()` lê `i18n.current`, que é estado reativo, então qualquer template ou
 * `$derived` que o chame é refeito quando o idioma muda.
 */
import { ptBR } from './pt-BR';
import { enUS } from './en-US';

export type Locale = 'pt-BR' | 'en-US';
export type MessageKey = keyof typeof ptBR;
export type Messages = Record<MessageKey, string>;
export type Params = Record<string, string | number>;

export const DEFAULT_LOCALE: Locale = 'pt-BR';

export const LOCALES: { code: Locale; label: string; short: string }[] = [
  { code: 'pt-BR', label: 'Português (Brasil)', short: 'PT' },
  { code: 'en-US', label: 'English (US)', short: 'EN' }
];

const catalogs: Record<Locale, Messages> = { 'pt-BR': ptBR, 'en-US': enUS };

const STORAGE_KEY = 'pk_locale';

export function isLocale(value: unknown): value is Locale {
  return value === 'pt-BR' || value === 'en-US';
}

/** Casa um idioma qualquer ("en", "en-GB", "pt-PT") com um dos suportados. */
export function matchLocale(value: string | null | undefined): Locale | null {
  if (!value) return null;
  if (isLocale(value)) return value;
  const lang = value.toLowerCase().split('-')[0];
  if (lang === 'pt') return 'pt-BR';
  if (lang === 'en') return 'en-US';
  return null;
}

function detect(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (isLocale(saved)) return saved;
  } catch {
    /* storage bloqueado */
  }
  if (typeof navigator !== 'undefined') {
    for (const lang of navigator.languages ?? [navigator.language]) {
      const match = matchLocale(lang);
      if (match) return match;
    }
  }
  return DEFAULT_LOCALE;
}

class LocaleStore {
  current = $state<Locale>(typeof window === 'undefined' ? DEFAULT_LOCALE : detect());

  constructor() {
    if (typeof document !== 'undefined') document.documentElement.lang = this.current;
  }

  set(locale: Locale) {
    this.current = locale;
    if (typeof document !== 'undefined') document.documentElement.lang = locale;
    try {
      localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      /* ignore */
    }
  }
}

export const i18n = new LocaleStore();

function interpolate(template: string, params?: Params): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole
  );
}

/** Texto da chave no idioma atual, com `{nome}` trocado pelos parâmetros. */
export function t(key: MessageKey, params?: Params): string {
  const template = catalogs[i18n.current][key] ?? ptBR[key] ?? key;
  return interpolate(template, params);
}

/** Chaves com forma singular (`_one`) e plural (`_other`), pelo radical. */
type PluralBase = MessageKey extends infer K
  ? K extends `${infer B}_other`
    ? B
    : never
  : never;

/**
 * Plural: `<base>_one` só para 1, `<base>_other` para o resto (inclusive 0),
 * com a contagem exposta como `{count}`. Não usa Intl.PluralRules de
 * propósito: em pt-BR ele trata 0 como singular ("0 projeto").
 */
export function tp(base: PluralBase, count: number, params?: Params): string {
  const key = (count === 1 ? `${base}_one` : `${base}_other`) as MessageKey;
  return t(key, { count: formatNumber(count), ...params });
}

export function formatNumber(n: number, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(i18n.current, options).format(n);
}

export function formatDate(
  value: Date | string | number,
  options?: Intl.DateTimeFormatOptions
): string {
  const date = value instanceof Date ? value : new Date(value);
  return date.toLocaleString(i18n.current, options);
}
