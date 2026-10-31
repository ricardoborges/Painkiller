<script lang="ts">
  import { t, formatDate } from '$lib/i18n/index.svelte';
  import { api } from '$lib/api';
  import type { AppPreview } from '$lib/types';
  import Icon from './Icon.svelte';
  import PhoneFrame, { DEVICE_W, DEVICE_H } from './PhoneFrame.svelte';

  /**
   * O app do projeto rodando num smartphone simulado, ao lado das tarefas.
   *
   * Mostra o último build web incorporado (o backend o promove quando uma
   * tarefa conclui). `version` muda a cada tarefa concluída: aí a prévia é
   * relida e, se o build mudou, o iframe recarrega sozinho.
   *
   * O app é código do agente: o iframe é sandbox sem allow-same-origin (o
   * servidor também manda CSP sandbox), então ele não alcança o token.
   */
  let {
    projectId,
    version = 0,
    collapsed = $bindable(false)
  }: { projectId: string; version?: number; collapsed?: boolean } = $props();

  let preview = $state<AppPreview | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  // Recarregar à mão remonta o iframe, mesmo com o mesmo build.
  let nonce = $state(0);
  let fresh = $state(false);
  let freshTimer: ReturnType<typeof setTimeout> | undefined;

  // O aparelho cabe no que se vê abaixo dele: medido ao montar e a cada
  // redimensionamento (não na rolagem, para não encolher e crescer à toa).
  // Reserva espaço para o rodapé com a tarefa e a data.
  const FOOTER_RESERVE = 104;
  const MIN_HEIGHT = 420;
  let stage = $state<HTMLDivElement | null>(null);
  let stageW = $state(0);
  let fitH = $state(0);
  const scale = $derived(
    stageW && fitH ? Math.min(1, stageW / DEVICE_W, fitH / DEVICE_H) : 1
  );

  function measure() {
    if (!stage) return;
    // A coluna fica presa no topo (sticky): o que conta é onde o aparelho
    // fica quando presa, não onde está ao montar — abaixo da barra da sessão
    // e de faixas de aviso, o que encolhia o aparelho para a metade.
    const col = (stage.closest('aside') as HTMLElement | null) ?? stage;
    const pinned = parseFloat(getComputedStyle(col).top);
    const offset = stage.getBoundingClientRect().top - col.getBoundingClientRect().top;
    const top = Number.isFinite(pinned)
      ? pinned + offset
      : Math.max(0, stage.getBoundingClientRect().top);
    fitH = Math.max(MIN_HEIGHT, window.innerHeight - top - FOOTER_RESERVE);
  }

  $effect(() => {
    if (!stage) return;
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  });

  async function load() {
    const before = preview?.built_at ?? null;
    error = null;
    try {
      const next = await api.getAppPreview(projectId);
      preview = next;
      // Um build novo depois do primeiro: avisa por alguns segundos.
      if (before && next.built_at && next.built_at !== before) {
        fresh = true;
        clearTimeout(freshTimer);
        freshTimer = setTimeout(() => (fresh = false), 5000);
      }
    } catch (e) {
      error = e instanceof Error ? e.message : t('preview.loadFailed');
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    // Lidos aqui para virarem dependências: projeto trocado ou tarefa concluída.
    void projectId;
    void version;
    load();
  });

  $effect(() => () => clearTimeout(freshTimer));
</script>

{#if collapsed}
  <button
    type="button"
    class="reveal btn btn-line btn-sm"
    onclick={() => (collapsed = false)}
    title={t('preview.show')}
  >
    <Icon name="phone" size={12} />
    <span>{t('preview.show')}</span>
  </button>
{:else}
  <section class="preview" aria-label={t('preview.title')}>
    <header class="head">
      <span class="label title">
        {t('preview.title')}
        {#if fresh}<span class="fresh mono" role="status">· {t('preview.fresh')}</span>{/if}
      </span>
      <div class="tools">
        {#if preview?.available}
          <button
            type="button"
            class="btn-icon"
            onclick={() => nonce++}
            aria-label={t('preview.reload')}
            title={t('preview.reload')}
          >
            <Icon name="refresh" size={13} />
          </button>
        {/if}
        <button
          type="button"
          class="btn-icon"
          onclick={() => (collapsed = true)}
          aria-label={t('preview.hide')}
          title={t('preview.hide')}
        >
          <Icon name="close" size={13} />
        </button>
      </div>
    </header>

    <div class="stage" bind:this={stage} bind:clientWidth={stageW}>
      <PhoneFrame {scale} highlight={fresh}>
        {#if loading}
          <div class="skel fill" aria-busy="true"></div>
        {:else if preview?.available && preview.url}
          {#key `${preview.url}#${nonce}`}
            <iframe
              src={preview.url}
              title={t('preview.frameLabel')}
              sandbox="allow-scripts allow-forms allow-modals allow-popups"
              referrerpolicy="no-referrer"
            ></iframe>
          {/key}
        {:else}
          <div class="empty">
            {#if error}
              <p class="empty-title">{t('preview.loadFailed')}</p>
              <p class="empty-detail">{error}</p>
              <button type="button" class="btn btn-line btn-sm" onclick={load}>{t('common.retry')}</button>
            {:else if preview && !preview.supported}
              <p class="empty-title">{t('preview.unsupportedTitle')}</p>
              <p class="empty-detail">{t('preview.unsupportedDetail')}</p>
            {:else}
              <p class="empty-title">{t('preview.emptyTitle')}</p>
              <p class="empty-detail">{t('preview.emptyDetail')}</p>
            {/if}
          </div>
        {/if}
      </PhoneFrame>
    </div>

    {#if preview?.available}
      <footer class="meta">
        {#if preview.task_title}
          <span class="mono truncate" title={preview.task_title}>
            {t('preview.updatedBy', { title: preview.task_title })}
          </span>
        {/if}
        {#if preview.built_at}
          <span class="mono faint">{formatDate(preview.built_at, { dateStyle: 'short', timeStyle: 'short' })}</span>
        {/if}
        <span class="note faint">{t('preview.webNote')}</span>
      </footer>
    {/if}
  </section>
{/if}

<style>
  .preview {
    display: flex;
    flex-direction: column;
    gap: var(--s3);
  }

  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s2);
    padding-bottom: var(--s2);
    border-bottom: 1px solid var(--rule-ink);
  }

  .title {
    color: var(--ink);
  }

  /* Build novo: só peso, nunca o acento (reservado ao exit 42). */
  .fresh {
    font-weight: 600;
    color: var(--ink);
  }

  .tools {
    display: flex;
    gap: var(--s1);
  }

  .stage {
    display: flex;
    justify-content: center;
    align-items: flex-start;
    overflow: hidden;
  }

  .fill {
    display: block;
    width: 100%;
    height: 100%;
  }

  .empty {
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: var(--s3);
    height: 100%;
    padding: var(--s6);
    box-sizing: border-box;
    background: var(--paper-sunk);
    color: var(--ink-2);
  }

  .empty-title {
    margin: 0;
    color: var(--ink);
    font-weight: 600;
    font-size: var(--t-title);
  }

  .empty-detail {
    margin: 0;
    font-size: var(--t-small);
    line-height: 1.5;
  }

  .empty .btn {
    align-self: flex-start;
  }

  .meta {
    display: flex;
    flex-direction: column;
    gap: var(--s1);
    font-size: var(--t-micro);
    color: var(--ink-2);
    min-width: 0;
  }

  .note {
    line-height: 1.4;
  }

  .reveal {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
  }
</style>
