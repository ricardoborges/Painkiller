<script lang="ts">
  import { t } from '$lib/i18n/index.svelte';
  /**
   * O que o agente de uma tarefa está fazendo agora, via SSE.
   *
   * O dispatch segura a requisição HTTP até o contêiner sair; este painel é o
   * que permite distinguir um agente trabalhando de um travado. O sinal que
   * importa é "última atividade há N s": deltas de texto e de raciocínio
   * contam como atividade mesmo sem virar linha no log.
   */
  // O botão de parar fica na coluna de ações do card, não aqui: dois botões
  // iguais no mesmo card confundiam.
  import { openTaskStream } from '$lib/api';
  import type { AgentEvent } from '$lib/types';
  import Elapsed from './Elapsed.svelte';
  import AgentScene, { sceneForTool, type SceneMode } from './AgentScene.svelte';

  let {
    taskId,
    starting = false,
    onclosed
  }: {
    taskId: string;
    /**
     * Esta aba acabou de disparar a tarefa. O stream pode chegar ao servidor
     * antes do POST de dispatch registrar a execução; nesse caso "inativo"
     * quer dizer "ainda não começou", e o painel reconecta em vez de avisar.
     */
    starting?: boolean;
    /** Chamado quando o servidor encerra o stream de uma execução que estava ativa. */
    onclosed?: () => void;
  } = $props();

  type Line = {
    kind: 'tool' | 'text' | 'system' | 'noise';
    text: string;
    detail?: string | null;
    /** Chamadas seguidas da mesma ferramenta sem alvo viram uma linha só. */
    count?: number;
  };

  // Acima disto sem nenhum evento, o painel avisa que pode estar travado.
  const SILENCE_WARN_S = 120;
  const MAX_LINES = 300;
  // Enquanto o dispatch desta aba não registra a execução no servidor.
  const RETRY_MS = 1000;
  const RETRY_MAX = 15;

  let active = $state<boolean | null>(null);
  let startedAt = $state<number | null>(null);
  let lastAt = $state<number | null>(null);
  let lines = $state<Line[]>([]);
  let partial = $state('');
  let thinking = $state(false);
  // Última ferramenta chamada: escolhe a cena e a legenda ao lado do log.
  let lastTool = $state<{ mode: SceneMode; detail: string | null } | null>(null);
  let now = $state(Date.now());
  let box = $state<HTMLElement | null>(null);
  let follow = true;

  function push(line: Line) {
    const last = lines[lines.length - 1];
    if (line.kind === 'tool' && !line.detail && last?.kind === 'tool' && !last.detail && last.text === line.text) {
      lines = [...lines.slice(0, -1), { ...last, count: (last.count ?? 1) + 1 }];
      return;
    }
    lines = [...lines, line].slice(-MAX_LINES);
  }

  function onEvent(e: AgentEvent) {
    const ts = Date.parse(e.timestamp);
    lastAt = Number.isNaN(ts) ? Date.now() : ts;
    switch (e.type) {
      case 'ASSISTANT_DELTA':
        partial += e.text;
        thinking = false;
        return;
      case 'THINKING_DELTA':
      case 'THINKING':
        thinking = true;
        return;
      case 'ASSISTANT':
        partial = '';
        thinking = false;
        if (e.text.trim()) push({ kind: 'text', text: e.text.trim() });
        return;
      case 'RESULT':
        partial = '';
        thinking = false;
        if (e.text.trim()) push({ kind: 'text', text: e.text.trim() });
        return;
      case 'TOOL_USE':
        thinking = false;
        if (partial.trim()) push({ kind: 'text', text: partial.trim() });
        partial = '';
        push({ kind: 'tool', text: e.text || t('activity.tool'), detail: e.detail });
        lastTool = { mode: sceneForTool(e.text || ''), detail: e.detail ?? null };
        return;
      case 'SYSTEM':
        if (e.text) push({ kind: 'system', text: e.text });
        return;
      case 'ERROR':
        if (e.text.trim()) push({ kind: 'noise', text: e.text.trim() });
        return;
    }
  }

  $effect(() => {
    const id = taskId;
    lines = [];
    partial = '';
    active = null;
    let wasActive = false;
    let tries = 0;
    let retrying = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let close = () => {};

    function connect() {
      // Cada conexão reconstrói o log do zero: num Retry o stream pode chegar
      // antes da nova execução e repetir a anterior, já encerrada.
      lines = [];
      partial = '';
      thinking = false;
      lastTool = null;
      close = openTaskStream(id, {
        onState: (s) => {
          if (!s.active && starting && tries < RETRY_MAX) {
            tries += 1;
            retrying = true;
            return;
          }
          active = s.active;
          wasActive = s.active;
          startedAt = s.started_at ? Date.parse(s.started_at) : null;
          lastAt = s.last_event_at ? Date.parse(s.last_event_at) : startedAt;
        },
        onEvent: (e) => {
          if (!retrying) onEvent(e);
        },
        onClose: () => {
          if (retrying) {
            retrying = false;
            timer = setTimeout(connect, RETRY_MS);
            return;
          }
          if (wasActive) onclosed?.();
        }
      });
    }

    connect();
    return () => {
      clearTimeout(timer);
      close();
    };
  });

  $effect(() => {
    const tick = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(tick);
  });

  // Acompanha o fim do log só enquanto o leitor já está no fim.
  $effect(() => {
    void lines.length;
    void partial;
    if (box && follow) box.scrollTop = box.scrollHeight;
  });

  function onScroll() {
    if (!box) return;
    follow = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
  }

  const silence = $derived(lastAt ? Math.max(0, Math.floor((now - lastAt) / 1000)) : null);
  const stale = $derived(silence !== null && silence >= SILENCE_WARN_S);

  // Silêncio longo vira cochilo; raciocínio vira balão; texto saindo é escrita.
  const scene = $derived<SceneMode>(
    stale ? 'sleep' : thinking ? 'thinking' : partial ? 'edit' : (lastTool?.mode ?? 'thinking')
  );
  const sceneDetail = $derived(stale || thinking || partial ? null : (lastTool?.detail ?? null));

  function ago(s: number): string {
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    return `${m} min ${String(s % 60).padStart(2, '0')}s`;
  }
</script>

<div class="activity" class:stale class:with-scene={active !== false}>
  {#if active !== false}
    <!-- Loading complementar: a cena imita o que o agente faz agora. -->
    <figure class="scene-box">
      <AgentScene mode={scene} />
      <figcaption>
        <span class="caption">{t(`activity.scene.${scene}`)}</span>
        {#if sceneDetail}<span class="mono caption-detail" title={sceneDetail}>{sceneDetail}</span>{/if}
      </figcaption>
    </figure>
  {/if}

  <!-- O log do contêiner como um terminal: o único bloco invertido do card. -->
  <div class="term">
    <div class="term-bar">
      <span class="pulse" class:still={active === false || stale} aria-hidden="true"></span>
      {#if active === null}
        <span>{t('activity.connecting')}</span>
      {:else if active === false}
        <span>{t('activity.orphaned')}</span>
      {:else}
        <span class="state">{thinking ? t('activity.thinking') : t('activity.working')}</span>
        {#if startedAt}
          <span class="sep">·</span>
          <Elapsed from={startedAt} />
        {/if}
        {#if silence !== null}
          <span class="last" class:warn={stale}>
            {stale ? t('activity.stale', { ago: ago(silence) }) : t('activity.lastActivity', { ago: ago(silence) })}
          </span>
        {/if}
      {/if}
    </div>

    <ol class="log" bind:this={box} onscroll={onScroll}>
      {#each lines as line, i (i)}
        <li class={line.kind}>
          {#if line.kind === 'tool'}
            <span class="mark" aria-hidden="true">$</span>
            <span class="tool">{line.text}</span>
            {#if line.detail}<span class="detail" title={line.detail}>{line.detail}</span>{/if}
            {#if line.count && line.count > 1}<span class="count">×{line.count}</span>{/if}
          {:else if line.kind === 'system' || line.kind === 'noise'}
            <span class="mark" aria-hidden="true">#</span>
            <span class="body">{line.text}</span>
          {:else}
            <span class="body">{line.text}</span>
          {/if}
        </li>
      {/each}
      {#if partial}
        <li class="text partial"><span class="body">{partial}<span class="cursor" aria-hidden="true"></span></span></li>
      {:else if active}
        <li class="prompt"><span class="mark" aria-hidden="true">$</span><span class="cursor" aria-hidden="true"></span></li>
      {/if}
    </ol>
  </div>
</div>

<style>
  .activity {
    margin-top: var(--s4);
    max-width: var(--task-col, 44rem);
    background: var(--paper);
    border: 1px solid var(--rule);
    font-size: var(--t-small);
    color: var(--ink-2);
  }

  .activity.with-scene {
    display: grid;
    grid-template-columns: 13rem minmax(0, 1fr);
    align-items: stretch;
  }

  .scene-box {
    margin: 0;
    padding: var(--s3) var(--s4);
    border-right: 1px solid var(--rule);
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: var(--s2);
  }

  figcaption {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
  }

  .caption {
    color: var(--ink);
    font-size: var(--t-micro);
    font-weight: 600;
  }

  .caption-detail {
    color: var(--ink-3);
    font-size: var(--t-micro);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  @media (max-width: 640px) {
    .activity.with-scene {
      grid-template-columns: 1fr;
    }

    .scene-box {
      border-right: 0;
      border-bottom: 1px solid var(--rule);
      flex-direction: row;
      align-items: center;
    }

    .scene-box :global(svg) {
      width: 9rem;
      flex: none;
    }
  }

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
    flex-wrap: wrap;
    align-items: center;
    gap: var(--s2);
    padding: var(--s2) var(--s4);
    border-bottom: 1px solid var(--term-rule);
    color: var(--term-dim);
    font-variant-numeric: tabular-nums;
  }

  .state {
    color: var(--term-fg);
  }

  .sep {
    color: var(--term-faint);
  }

  .last {
    margin-left: auto;
  }

  /* Silêncio longo: peso e hachura, nunca o acento — ele é só do exit 42. */
  .last.warn {
    color: var(--term-fg);
    font-weight: 600;
  }

  .activity.stale .term-bar {
    background-image: repeating-linear-gradient(
      -45deg,
      transparent 0 6px,
      var(--term-rule) 6px 7px
    );
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
    height: 18rem;
    overflow-y: auto;
    line-height: 1.6;
    scrollbar-width: thin;
    scrollbar-color: var(--term-faint) transparent;
  }

  .log li {
    display: flex;
    gap: var(--s2);
    min-width: 0;
  }

  /* A fala do agente abre um parágrafo; os comandos ficam colados. */
  .log li.text {
    margin-block: var(--s2);
  }

  .body {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .text .body {
    color: var(--term-fg);
  }

  .partial .body {
    display: block;
  }

  li.tool .tool {
    color: var(--term-fg);
    font-weight: 600;
    flex: none;
    /* Coluna fixa: os alvos (comando, arquivo) ficam alinhados entre si. */
    min-width: 6ch;
  }

  .count {
    color: var(--term-dim);
    flex: none;
  }

  .mark {
    color: var(--term-faint);
    flex: none;
  }

  .detail {
    color: var(--term-dim);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  .system .body {
    color: var(--term-dim);
  }

  .noise .body {
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
