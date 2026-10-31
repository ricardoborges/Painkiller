<script lang="ts">
  /**
   * Log de um deploy do Coolify no mesmo terminal invertido do agente.
   *
   * O texto chega inteiro a cada poll (`format_deployment_logs`), então a
   * classificação é por linha e barata: erros ganham peso, passos do build
   * ganham a marca `$`, réguas e contexto do Dockerfile esmaecem.
   */
  import { t } from '$lib/i18n/index.svelte';

  let {
    logs,
    active = false,
    failed = false,
    branch = null,
    title = null
  }: {
    logs: string;
    /** Deploy ainda em andamento: pulso aceso e cursor no fim. */
    active?: boolean;
    /** Deploy falhou: hachura na barra, nunca o acento. */
    failed?: boolean;
    branch?: string | null;
    /** Rótulo da barra; o padrão é o dos deploys. */
    title?: string | null;
  } = $props();

  type Kind = 'error' | 'step' | 'rule' | 'context' | 'plain';
  type Line = { kind: Kind; text: string };

  // Linhas acima disto ficam de fora; o fim é o que importa num build.
  const MAX_LINES = 2000;

  function classify(text: string): Kind {
    if (/^\s*[-=]{4,}\s*$/.test(text)) return 'rule';
    if (/\b(error|failed|fatal|exception|denied)\b/i.test(text)) return 'error';
    // Contexto do Dockerfile que o BuildKit imprime: "  21 | >>> RUN ...".
    if (/^\s*\d+\s*\|/.test(text)) return /\|\s*>>>/.test(text) ? 'error' : 'context';
    // Passos do BuildKit ("#7 [3/6] RUN ...") e comandos do Coolify.
    if (/^#\d+\s+\[/.test(text) || /^(step \d+|\$ |>\s)/i.test(text)) return 'step';
    return 'plain';
  }

  const all = $derived(logs.replace(/\r\n?/g, '\n').replace(/\n+$/, '').split('\n'));
  const lines = $derived<Line[]>(all.slice(-MAX_LINES).map((text) => ({ kind: classify(text), text })));
  const skipped = $derived(Math.max(0, all.length - MAX_LINES));

  let box = $state<HTMLElement | null>(null);
  let follow = true;

  // Acompanha o fim do log só enquanto o leitor já está no fim.
  $effect(() => {
    void lines.length;
    if (box && follow) box.scrollTop = box.scrollHeight;
  });

  function onScroll() {
    if (!box) return;
    follow = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
  }
</script>

<div class="term" class:failed>
  <div class="term-bar">
    <span class="pulse" class:still={!active} aria-hidden="true"></span>
    <span class="title">{title ?? t('backlog.deployLogs')}</span>
    {#if branch}
      <span class="sep">·</span>
      <span class="branch">{branch}</span>
    {/if}
    <span class="count">{lines.length + skipped}</span>
  </div>

  <ol class="log" bind:this={box} onscroll={onScroll}>
    {#if skipped}
      <li class="rule"><span class="text">… {skipped}</span></li>
    {/if}
    {#each lines as line, i (i)}
      <li class={line.kind}>
        <span class="mark" aria-hidden="true">{line.kind === 'step' ? '$' : line.kind === 'error' ? '!' : ''}</span>
        <span class="text">{line.text}</span>
      </li>
    {/each}
    {#if active}
      <li class="prompt"><span class="mark" aria-hidden="true">$</span><span class="cursor" aria-hidden="true"></span></li>
    {/if}
  </ol>
</div>

<style>
  .term {
    min-width: 0;
    background: var(--term-bg);
    color: var(--term-fg);
    font-family: var(--font-mono);
    font-size: var(--t-micro);
    display: flex;
    flex-direction: column;
  }

  .term-bar {
    display: flex;
    align-items: center;
    gap: var(--s2);
    padding: var(--s2) var(--s4);
    border-bottom: 1px solid var(--term-rule);
    color: var(--term-dim);
    font-variant-numeric: tabular-nums;
    min-width: 0;
  }

  /* Falha: peso e hachura, nunca o acento — ele é só do exit 42. */
  .term.failed .term-bar {
    background-image: repeating-linear-gradient(-45deg, transparent 0 6px, var(--term-rule) 6px 7px);
  }

  .title {
    color: var(--term-fg);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .sep {
    color: var(--term-faint);
  }

  .branch {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  .count {
    margin-left: auto;
    color: var(--term-faint);
  }

  .pulse {
    width: 6px;
    height: 6px;
    flex: none;
    background: var(--term-fg);
    animation: blink 1.3s var(--ease) infinite;
  }

  .pulse.still {
    animation: none;
    background: var(--term-faint);
  }

  @keyframes blink {
    50% {
      opacity: 0.2;
    }
  }

  .log {
    list-style: none;
    margin: 0;
    padding: var(--s3) var(--s4);
    height: 22rem;
    max-height: 50vh;
    overflow-y: auto;
    overflow-x: hidden;
    line-height: 1.6;
    scrollbar-width: thin;
    scrollbar-color: var(--term-faint) transparent;
  }

  .log li {
    display: flex;
    gap: var(--s2);
    min-width: 0;
    /* Linha em branco do log continua ocupando uma linha. */
    min-height: 1.6em;
    color: var(--term-dim);
  }

  .mark {
    flex: none;
    width: 1ch;
    color: var(--term-faint);
  }

  .text {
    min-width: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .step .text {
    color: var(--term-fg);
  }

  .error .text,
  .error .mark {
    color: var(--term-fg);
    font-weight: 600;
  }

  .rule .text,
  .context .text {
    color: var(--term-faint);
  }

  .cursor {
    display: inline-block;
    width: 0.55em;
    height: 1.1em;
    margin-left: 1px;
    vertical-align: text-bottom;
    background: var(--term-fg);
    animation: caret 1s steps(1) infinite;
  }

  @keyframes caret {
    50% {
      opacity: 0;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .pulse,
    .cursor {
      animation: none;
    }
  }
</style>
