<script lang="ts">
  import { i18n, LOCALES, t } from '$lib/i18n/index.svelte';

  // Dois idiomas: o botão alterna para o próximo e mostra o código do atual.
  const index = $derived(LOCALES.findIndex((l) => l.code === i18n.current));
  const next = $derived(LOCALES[(index + 1) % LOCALES.length]);
  const current = $derived(LOCALES[index] ?? LOCALES[0]);
</script>

<button
  type="button"
  class="btn-icon locale mono"
  onclick={() => i18n.set(next.code)}
  aria-label={t('locale.switchTo', { language: next.label })}
  title={t('locale.switchTo', { language: next.label })}
>
  {current.short}
</button>

<style>
  .locale {
    font-size: 0.6875rem;
    font-weight: 500;
    letter-spacing: 0.04em;
  }
</style>
