<script lang="ts">
  /**
   * O ambiente de teste (Coolify) dentro de um smartphone grande, em vez da
   * janela inteira do navegador. Aberto por `testDevice.show(url)`.
   *
   * Não usa o Modal genérico: cabeçalho, rodapé e margens dele roubavam altura,
   * e o aparelho saía minúsculo numa janela baixa. Aqui o aparelho ocupa toda a
   * altura útil e as ações ficam numa coluna estreita ao lado.
   *
   * Sem `sandbox` no iframe, ao contrário da prévia: o teste roda em outra
   * origem (o subdomínio do Coolify), que já não alcança o token do Painkiller,
   * e precisa de storage e do próprio servidor para funcionar como no aparelho.
   */
  import { t } from '$lib/i18n/index.svelte';
  import { testDevice } from '$lib/stores/testDevice.svelte';
  import Icon from './Icon.svelte';
  import PhoneFrame, { BEZEL_X, BEZEL_Y } from './PhoneFrame.svelte';

  // Viewports reais (pontos CSS) de três aparelhos: do maior ao menor.
  const SIZES = [
    { id: 'max', label: 'testDevice.size.max', model: 'iPhone 16 Pro Max', w: 440, h: 956 },
    { id: 'standard', label: 'testDevice.size.standard', model: 'iPhone 16', w: 393, h: 852 },
    { id: 'compact', label: 'testDevice.size.compact', model: 'iPhone SE', w: 375, h: 667 }
  ] as const;
  type SizeId = (typeof SIZES)[number]['id'];
  const SIZE_KEY = 'pk_test_device_size';

  function storedSize(): SizeId {
    try {
      const v = localStorage.getItem(SIZE_KEY);
      if (SIZES.some((x) => x.id === v)) return v as SizeId;
    } catch {
      /* storage indisponível: fica o padrão */
    }
    return 'standard';
  }

  let sizeId = $state<SizeId>(storedSize());
  const size = $derived(SIZES.find((x) => x.id === sizeId) ?? SIZES[1]);
  const DEVICE_W = $derived(size.w + BEZEL_X * 2);
  const DEVICE_H = $derived(size.h + BEZEL_Y * 2);

  function pick(id: SizeId) {
    sizeId = id;
    try {
      localStorage.setItem(SIZE_KEY, id);
    } catch {
      /* sem persistência */
    }
  }
  // Respiro em volta do aparelho e a coluna de ações.
  const MARGIN_Y = 24;
  const SIDE_W = 112;

  let el = $state<HTMLDialogElement | null>(null);
  let nonce = $state(0);
  let viewportH = $state(0);
  let viewportW = $state(0);
  const scale = $derived(
    viewportH && viewportW
      ? Math.max(0.3, Math.min(1, (viewportH - MARGIN_Y * 2) / DEVICE_H, (viewportW - SIDE_W * 2 - 32) / DEVICE_W))
      : 0.7
  );

  $effect(() => {
    if (!el) return;
    if (testDevice.open && !el.open) el.showModal();
    else if (!testDevice.open && el.open) el.close();
  });
</script>

<svelte:window bind:innerHeight={viewportH} bind:innerWidth={viewportW} />

<dialog
  bind:this={el}
  onclose={() => (testDevice.open = false)}
  onclick={(e) => {
    // Clique fora do aparelho (no fundo) fecha, como num modal comum.
    if (e.target === el) testDevice.open = false;
  }}
  aria-label={t('testDevice.title')}
>
  <div class="room">
    {#if testDevice.url && testDevice.open}
      <PhoneFrame {scale} screenW={size.w} screenH={size.h}>
        {#key nonce}
          <iframe src={testDevice.url} title={t('testDevice.frameLabel')}></iframe>
        {/key}
      </PhoneFrame>
    {/if}

    <div class="side">
      <button
        type="button"
        class="tool"
        onclick={() => (testDevice.open = false)}
        aria-label={t('common.close')}
        title={t('common.close')}
      >
        <Icon name="close" size={16} />
      </button>
      <button
        type="button"
        class="tool"
        onclick={() => nonce++}
        aria-label={t('testDevice.reload')}
        title={t('testDevice.reload')}
      >
        <Icon name="refresh" size={15} />
      </button>
      {#if testDevice.url}
        <a
          class="tool"
          href={testDevice.url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={t('testDevice.direct')}
          title={t('testDevice.direct')}
        >
          <Icon name="external" size={15} />
        </a>
      {/if}

      <div class="sizes" role="radiogroup" aria-label={t('testDevice.sizeLabel')}>
        {#each SIZES as x (x.id)}
          <button
            type="button"
            role="radio"
            aria-checked={sizeId === x.id}
            class="size"
            class:on={sizeId === x.id}
            onclick={() => pick(x.id)}
            title="{x.model} · {x.w}×{x.h}"
          >
            <span class="size-name">{t(x.label)}</span>
            <span class="size-dim mono">{x.w}×{x.h}</span>
          </button>
        {/each}
      </div>
      {#if scale < 1}
        <p class="zoom mono" title={t('testDevice.zoomTitle')}>{Math.round(scale * 100)}%</p>
      {/if}
    </div>
  </div>
</dialog>

<style>
  dialog {
    width: 100vw;
    height: 100dvh;
    max-width: none;
    max-height: none;
    margin: 0;
    padding: 0;
    border: 0;
    background: transparent;
    overflow: hidden;
  }

  dialog[open] {
    display: flex;
    align-items: center;
    justify-content: center;
    animation: rise var(--base) var(--ease);
  }

  dialog::backdrop {
    background: var(--scrim);
  }

  .room {
    position: relative;
    display: flex;
    align-items: flex-start;
    gap: var(--s3);
    /* A coluna de ações não desloca o aparelho do centro. */
    margin-right: calc(-1 * (6rem + var(--s3)));
  }

  .side {
    display: flex;
    flex-direction: column;
    gap: var(--s2);
  }

  .tool {
    display: grid;
    place-items: center;
    width: 2.5rem;
    height: 2.5rem;
    background: var(--paper);
    color: var(--ink);
    border: 1px solid var(--rule-2);
    cursor: pointer;
  }

  .tool:hover {
    border-color: var(--ink);
  }

  .sizes {
    display: flex;
    flex-direction: column;
    width: 6rem;
    margin-top: var(--s3);
    border: 1px solid var(--rule-2);
    background: var(--paper);
  }

  .size {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    padding: var(--s2);
    background: none;
    border: 0;
    border-bottom: 1px solid var(--rule);
    color: var(--ink-3);
    cursor: pointer;
    text-align: left;
  }

  .size:last-child {
    border-bottom: 0;
  }

  .size:hover {
    color: var(--ink);
  }

  /* Selecionado: tinta invertida, nunca o acento. */
  .size.on {
    background: var(--ink);
    color: var(--paper);
  }

  .size-name {
    font-size: var(--t-small);
    font-weight: 600;
  }

  .size-dim {
    font-size: var(--t-micro);
    opacity: 0.8;
  }

  .zoom {
    width: 6rem;
    font-size: var(--t-micro);
    /* Sobre o fundo escurecido, nos dois temas. */
    color: #ffffff;
    opacity: 0.7;
    text-align: center;
  }
</style>
