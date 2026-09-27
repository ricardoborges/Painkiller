<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import Icon from '$lib/components/Icon.svelte';

  const ICON = { done: 'check', failed: 'alert', info: 'info' } as const;
</script>

<div class="toaster" aria-live="polite" aria-atomic="false">
  {#each toast.items as item (item.id)}
    <div
      class="toast"
      class:done={item.tone === 'done'}
      class:failed={item.tone === 'failed'}
      role={item.tone === 'failed' ? 'alert' : 'status'}
      onmouseenter={() => toast.pause(item.id)}
      onmouseleave={() => toast.resume(item.id)}
      onfocusin={() => toast.pause(item.id)}
      onfocusout={() => toast.resume(item.id)}
    >
      <span class="ico" aria-hidden="true"><Icon name={ICON[item.tone]} size={14} /></span>
      <div class="text">
        <strong>{item.title}</strong>
        {#if item.detail}<span class="detail mono">{item.detail}</span>{/if}
        {#if item.href}
          <a href={item.href} target="_blank" rel="noopener noreferrer" class="link mono">
            {item.hrefLabel ?? item.href}
            <Icon name="external" size={10} />
          </a>
        {/if}
      </div>
      <button type="button" class="btn-icon close" aria-label={t('common.closeNotice')} onclick={() => toast.dismiss(item.id)}>
        <Icon name="close" size={12} />
      </button>
      <!-- Contagem regressiva visível: o aviso some quando a linha esvazia -->
      <span class="timer" style="animation-duration: {item.duration}ms" aria-hidden="true"></span>
    </div>
  {/each}
</div>

<style>
  .toaster {
    position: fixed;
    right: var(--s5);
    bottom: var(--s5);
    z-index: 60;
    display: flex;
    flex-direction: column;
    gap: var(--s2);
    width: min(24rem, calc(100vw - 2 * var(--s4)));
    pointer-events: none;
  }

  .toast {
    position: relative;
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: var(--s3);
    align-items: start;
    padding: var(--s3) var(--s4) calc(var(--s3) + 2px);
    background-color: var(--paper);
    border: 1px solid var(--rule-ink);
    box-shadow: 0 8px 24px -12px var(--shadow);
    pointer-events: auto;
    animation: rise 220ms var(--ease) both;
  }

  /* Exceção pedida à regra de cor única: só os avisos de resultado ganham um
     fundo levemente verde (deu certo) ou avermelhado (falhou). Tons pálidos,
     longe do vermelhão de --accent, que segue reservado para o exit 42. */
  .toast {
    --toast-done-bg: #eef8f0;
    --toast-done-rule: #7fb98c;
    --toast-done-ink: #2f7a43;
    --toast-failed-bg: #fbeeee;
    --toast-failed-rule: #d69a9a;
    --toast-failed-ink: #a33a3a;
  }

  :global(:root[data-theme='dark']) .toast {
    --toast-done-bg: #17261b;
    --toast-done-rule: #3f7a50;
    --toast-done-ink: #8fd0a0;
    --toast-failed-bg: #2a1818;
    --toast-failed-rule: #85494b;
    --toast-failed-ink: #e6a3a3;
  }

  .toast.done {
    background-color: var(--toast-done-bg);
    border-color: var(--toast-done-rule);
  }

  .toast.done .ico,
  .toast.done .timer {
    color: var(--toast-done-ink);
  }

  .toast.done .timer,
  .toast.failed .timer {
    background: currentColor;
  }

  .toast.failed {
    background-color: var(--toast-failed-bg);
    border-color: var(--toast-failed-rule);
  }

  .toast.failed .ico,
  .toast.failed .timer {
    color: var(--toast-failed-ink);
  }

  .ico {
    display: inline-flex;
    padding-top: 2px;
    color: var(--ink);
  }

  .text {
    display: flex;
    flex-direction: column;
    gap: var(--s1);
    min-width: 0;
  }

  strong {
    font-size: var(--t-small);
    font-weight: 600;
  }

  .detail {
    font-size: var(--t-micro);
    color: var(--ink-2);
    word-break: break-word;
  }

  .link {
    display: inline-flex;
    align-items: center;
    gap: var(--s1);
    font-size: var(--t-micro);
    color: var(--ink);
    text-decoration: underline;
    word-break: break-all;
  }

  .close {
    color: var(--ink-3);
  }

  .timer {
    position: absolute;
    left: 0;
    bottom: 0;
    height: 2px;
    width: 100%;
    background: var(--ink);
    transform-origin: left;
    animation-name: drain;
    animation-timing-function: linear;
    animation-fill-mode: forwards;
  }

  .toast:hover .timer,
  .toast:focus-within .timer {
    animation-play-state: paused;
  }

  @keyframes drain {
    from {
      transform: scaleX(1);
    }
    to {
      transform: scaleX(0);
    }
  }

  @media (max-width: 640px) {
    .toaster {
      right: var(--s4);
      bottom: var(--s4);
    }
  }
</style>
