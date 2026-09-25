<script lang="ts">
  /**
   * O que o agente de uma tarefa está fazendo agora, via SSE.
   *
   * O dispatch segura a requisição HTTP até o contêiner sair; este painel é o
   * que permite distinguir um agente trabalhando de um travado. O sinal que
   * importa é "última atividade há N s": deltas de texto e de raciocínio
   * contam como atividade mesmo sem virar linha no log.
   */
  import { openTaskStream, api } from '$lib/api';
  import type { AgentEvent } from '$lib/types';
  import Elapsed from './Elapsed.svelte';
  import Icon from './Icon.svelte';

  let stopping = $state(false);

  async function handleStop() {
    if (stopping) return;
    stopping = true;
    try {
      await api.stopTask(taskId);
    } catch (err) {
      console.error('Falha ao interromper tarefa:', err);
      stopping = false;
    }
  }

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

  type Line = { kind: 'tool' | 'text' | 'system' | 'noise'; text: string; detail?: string | null };

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
  let now = $state(Date.now());
  let box = $state<HTMLElement | null>(null);
  let follow = true;

  function push(line: Line) {
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
        push({ kind: 'tool', text: e.text || 'ferramenta', detail: e.detail });
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
        onEvent,
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
    const t = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(t);
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

  function ago(s: number): string {
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    return `${m} min ${String(s % 60).padStart(2, '0')}s`;
  }
</script>

<div class="activity" class:stale>
  <div class="head">
    <span class="pulse" class:still={active === false || stale} aria-hidden="true"></span>
    {#if active === null}
      <span>Conectando ao agente…</span>
    {:else if active === false}
      <span>
        Nenhuma execução desta tarefa está sendo acompanhada pelo servidor — ele pode ter
        sido reiniciado no meio dela. O status no banco ficou como executando.
      </span>
    {:else}
      <span>{thinking ? 'Agente raciocinando' : 'Agente trabalhando'}</span>
      {#if startedAt}
        <span class="sep">·</span>
        <Elapsed from={startedAt} />
      {/if}
      {#if silence !== null}
        <span class="sep">·</span>
        <span class="mono last" class:warn={stale}>
          {stale ? `sem sinal há ${ago(silence)} — pode estar travado` : `última atividade há ${ago(silence)}`}
        </span>
      {/if}
    {/if}

    {#if active}
      <button
        type="button"
        class="stop-btn label mono"
        disabled={stopping}
        onclick={handleStop}
        title="Interromper execução da tarefa"
      >
        <Icon name="square" size={9} />
        <span>{stopping ? 'Interrompendo…' : 'Interromper'}</span>
      </button>
    {/if}
  </div>

  {#if lines.length || partial}
    <ol class="log" bind:this={box} onscroll={onScroll}>
      {#each lines as line, i (i)}
        <li class={line.kind}>
          {#if line.kind === 'tool'}
            <span class="mark" aria-hidden="true">›</span>
            <span class="tool">{line.text}</span>
            {#if line.detail}<span class="detail">{line.detail}</span>{/if}
          {:else}
            <span class="body">{line.text}</span>
          {/if}
        </li>
      {/each}
      {#if partial}
        <li class="text partial"><span class="body">{partial}</span></li>
      {/if}
    </ol>
  {/if}
</div>

<style>
  .activity {
    margin-top: var(--s4);
    max-width: 44rem;
    background: var(--paper-sunk);
    border-left: 2px solid var(--ink);
    font-size: var(--t-small);
    color: var(--ink-2);
  }

  /* Silêncio longo: peso e hachura, nunca o acento — ele é só do exit 42. */
  .activity.stale {
    background-image: repeating-linear-gradient(
      -45deg,
      transparent 0 6px,
      var(--rule) 6px 7px
    );
  }

  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--s2);
    padding: var(--s3) var(--s4);
  }

  .sep {
    color: var(--ink-4);
  }

  .last {
    font-variant-numeric: tabular-nums;
    color: var(--ink-3);
  }

  .stop-btn {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.2rem 0.5rem;
    font-size: var(--t-micro);
    color: var(--accent);
    background: transparent;
    border: 1px solid var(--accent);
    cursor: pointer;
    transition: background var(--fast) var(--ease), color var(--fast) var(--ease);
  }

  .stop-btn:hover:not(:disabled) {
    background: var(--accent);
    color: var(--on-accent);
  }

  .stop-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .last.warn {
    color: var(--ink);
    font-weight: 600;
  }

  .pulse {
    width: 6px;
    height: 6px;
    flex: none;
    background: var(--ink);
    animation: blink 1.3s var(--ease) infinite;
  }

  .pulse.still {
    animation: none;
    background: var(--ink-3);
  }

  @keyframes blink {
    50% {
      opacity: 0.2;
    }
  }

  .log {
    list-style: none;
    margin: 0;
    padding: var(--s2) var(--s4) var(--s3);
    max-height: 16rem;
    overflow-y: auto;
    border-top: 1px solid var(--rule);
    font-family: var(--font-mono);
    font-size: var(--t-micro);
    line-height: 1.55;
  }

  .log li {
    display: flex;
    gap: var(--s2);
    min-width: 0;
    padding: 1px 0;
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
    color: var(--ink);
    font-family: var(--font-sans);
    font-size: var(--t-small);
  }

  .partial .body {
    color: var(--ink-2);
  }

  .tool .tool,
  li.tool .tool {
    color: var(--ink);
    font-weight: 600;
    flex: none;
  }

  .mark {
    color: var(--ink-3);
    flex: none;
  }

  .detail {
    color: var(--ink-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  .system .body {
    color: var(--ink-3);
  }

  .noise .body {
    color: var(--ink-4);
  }

  @media (prefers-reduced-motion: reduce) {
    .pulse {
      animation: none;
    }
  }
</style>
