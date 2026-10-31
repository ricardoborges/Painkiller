<script lang="ts">
  /**
   * QR code de um APK pronto: o celular escaneia e baixa direto, sem cabo.
   * O celular não tem a sessão do Painkiller, então o código leva um link
   * assinado e temporário (uma hora), pedido ao abrir o modal.
   */
  import qrcode from 'qrcode-generator';
  import { t, formatDate } from '$lib/i18n/index.svelte';
  import { api } from '$lib/api';
  import type { ApkBuild, ApkLink } from '$lib/types';
  import Modal from './Modal.svelte';
  import Icon from './Icon.svelte';

  let { open = $bindable(false), build }: { open?: boolean; build: ApkBuild | null } = $props();

  let link = $state<ApkLink | null>(null);
  let error = $state<string | null>(null);
  let copied = $state(false);

  $effect(() => {
    if (!open || !build) return;
    const current = build;
    link = null;
    error = null;
    copied = false;
    api
      .getApkLink(current.project_id, current.id)
      .then((value) => {
        if (build?.id === current.id) link = value;
      })
      .catch((e) => {
        error = e instanceof Error ? e.message : t('apk.qrFailed');
      });
  });

  // Correção de erro média: o código continua legível impresso pequeno ou numa tela com reflexo.
  const svg = $derived.by(() => {
    if (!link || link.local) return '';
    const qr = qrcode(0, 'M');
    qr.addData(link.url);
    qr.make();
    return qr.createSvgTag({ cellSize: 6, margin: 4, scalable: true });
  });

  const origin = $derived(link ? new URL(link.url).origin : '');

  async function copy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link.url);
      copied = true;
    } catch {
      /* clipboard indisponível (HTTP): o link segue visível para copiar à mão */
    }
  }
</script>

<Modal bind:open title={t('apk.qrDialogTitle')} width="30rem">
  {#snippet body()}
    <div class="wrap">
      {#if error}
        <p class="note hatch">{error}</p>
      {:else if !link}
        <div class="box skel" aria-busy="true"></div>
      {:else if link.local}
        <p class="note hatch">{t('apk.qrLocal', { url: origin })}</p>
      {:else}
        <div class="qr" role="img" aria-label={t('apk.qrDialogTitle')}>{@html svg}</div>
        <p>{t('apk.qrHelp')}</p>
        <p class="faint small">{t('apk.qrUnknownSources')}</p>
        <div class="url">
          <code class="mono">{link.url}</code>
          <button type="button" class="btn btn-line btn-sm" onclick={copy}>
            <Icon name={copied ? 'check' : 'copy'} size={11} /> {copied ? t('apk.qrCopied') : t('common.copy')}
          </button>
        </div>
        <p class="faint small">
          {t('apk.qrExpires', { time: formatDate(link.expires_at, { timeStyle: 'short' }) })}
        </p>
      {/if}
    </div>
  {/snippet}
</Modal>

<style>
  .wrap {
    padding: var(--s5);
    display: flex;
    flex-direction: column;
    gap: var(--s3);
  }

  /* Tinta sobre papel, sempre: um QR invertido no tema escuro muitas câmeras não leem. */
  .qr,
  .box {
    align-self: center;
    width: min(18rem, 100%);
    aspect-ratio: 1;
  }

  .qr {
    background: #fff;
    color: #000;
    border: 1px solid var(--rule);
  }

  .qr :global(svg) {
    display: block;
    width: 100%;
    height: 100%;
  }

  .note {
    padding: var(--s3);
    border: 1px solid var(--rule-ink);
    font-weight: 600;
  }

  .small {
    font-size: var(--t-small, 0.8125rem);
  }

  .url {
    display: flex;
    gap: var(--s2);
    align-items: center;
    border-top: 1px solid var(--rule);
    padding-top: var(--s3);
  }

  .url code {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
    font-size: 0.75rem;
    color: var(--ink-2);
  }

  .url .btn {
    flex: none;
  }
</style>
