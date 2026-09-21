<script lang="ts">
  import { onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { ApiError, api, openAnalysisStream } from '$lib/api';
  import type { AgentEvent, AnalysisSession, ProjectDoc } from '$lib/types';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';
  import Elapsed from '$lib/components/Elapsed.svelte';
  import DocViewer from '$lib/components/DocViewer.svelte';

  let { data } = $props();

  interface Turn {
    who: 'agent' | 'analyst' | 'tool';
    text: string;
  }

  /** Permite que um F5 reencontre a sessão em vez de subir outro contêiner. */
  const storageKey = $derived(`pk_analysis_${data.project.id}`);

  let session = $state<AnalysisSession | null>(null);
  let turns = $state<Turn[]>([]);
  /** Linhas não-JSON do contêiner (avisos do node, falhas de plugin). */
  let diagnostics = $state<string[]>([]);

  let starting = $state(true);
  let startError = $state<string | null>(null);
  let sendError = $state<string | null>(null);
  let draft = $state('');
  let closing = $state(false);
  let committing = $state(false);
  let streamClosed = $state(false);

  /** Texto do turno em andamento, montado a partir dos deltas. */
  let streaming = $state('');
  /** Raciocínio do modelo enquanto ele ainda não escreveu nada visível. */
  let reasoning = $state('');

  let composer = $state<HTMLTextAreaElement | null>(null);
  let waitingSince = $state(Date.now());
  let disposeStream: (() => void) | null = null;

  /** Documentos do superpowers descobertos no repositório. */
  let docs = $state<ProjectDoc[]>([]);
  let loadingDocs = $state(false);
  let selectedDoc = $state<ProjectDoc | null>(null);
  let isDocViewerOpen = $state(false);

  async function refreshDocs() {
    loadingDocs = true;
    try {
      docs = await api.listProjectDocs(data.project.id);
    } catch {
      /* falha silenciosa em background */
    } finally {
      loadingDocs = false;
    }
  }

  function openDoc(d: ProjectDoc) {
    selectedDoc = d;
    isDocViewerOpen = true;
  }

  /** O agente devolveu o turno: é a única hora em que o analista pode digitar. */
  const myTurn = $derived(session?.status === 'WAITING_ANALYST' && !streamClosed);
  const finished = $derived(session?.status === 'FINISHED' || streamClosed);

  function remember(id: string | null) {
    try {
      if (id) {
        sessionStorage.setItem(storageKey, id);
        localStorage.setItem(storageKey, id);
      } else {
        sessionStorage.removeItem(storageKey);
        localStorage.removeItem(storageKey);
      }
    } catch {
      /* modo privado / storage bloqueado */
    }
  }

  function recall(): string | null {
    try {
      return sessionStorage.getItem(storageKey) || localStorage.getItem(storageKey);
    } catch {
      return null;
    }
  }

  async function boot(forceNew: boolean = false) {
    starting = true;
    startError = null;
    turns = [];
    diagnostics = [];
    streaming = '';
    reasoning = '';
    streamClosed = false;
    waitingSince = Date.now();
    refreshDocs();

    if (!forceNew) {
      try {
        const current = await api.getCurrentAnalysis(data.project.id);
        if (current?.session) {
          session = current.session;
          remember(session.session_id);
          attach(session.session_id);
          starting = false;
          return;
        }
      } catch {
        /* se rota não responder, usa fallback local */
      }

      const previous = recall();
      if (previous) {
        try {
          // O stream reemite o histórico, então reatar é suficiente.
          session = await api.getAnalysis(previous);
          attach(previous);
          starting = false;
          return;
        } catch {
          // Sessão não encontrada: limpa e recomeça.
          remember(null);
        }
      }
    }

    try {
      session = await api.startAnalysis(data.project.id, forceNew);
      remember(session.session_id);
      attach(session.session_id);
    } catch (e) {
      startError = e instanceof Error ? e.message : 'Falha ao subir o agente de análise.';
    } finally {
      starting = false;
    }
  }

  function attach(sessionId: string) {
    disposeStream?.();
    disposeStream = openAnalysisStream(sessionId, onEvent, () => {
      streamClosed = true;
    });
  }

  function onEvent(event: AgentEvent) {
    switch (event.type) {
      case 'ASSISTANT_DELTA':
        streaming += event.text;
        // Assim que o texto de verdade começa, o raciocínio perde a vez.
        reasoning = '';
        break;
      case 'THINKING_DELTA':
        if (!streaming) reasoning += event.text;
        break;
      case 'USER':
        turns = [...turns, { who: 'analyst', text: event.text }];
        break;
      case 'ASSISTANT':
        // Canônico: substitui o que foi montado por delta, então um pedaço
        // perdido no caminho não deixa o texto truncado na tela.
        turns = [...turns, { who: 'agent', text: event.text }];
        streaming = '';
        reasoning = '';
        break;
      case 'TOOL_USE':
        streaming = '';
        reasoning = '';
        // O agente lendo e escrevendo arquivos é o sinal de progresso honesto
        // enquanto ele não fala — superpowers grava spec e plano em disco.
        turns = [...turns, { who: 'tool', text: event.text }];
        refreshDocs();
        break;
      case 'RESULT':
        streaming = '';
        reasoning = '';
        if (session) session = { ...session, status: 'WAITING_ANALYST' };
        queueMicrotask(() => composer?.focus());
        refreshDocs();
        break;
      case 'EXIT':
        if (session) {
          session = { ...session, status: event.text === '0' ? 'FINISHED' : 'FAILED' };
        }
        break;
      case 'ERROR':
        diagnostics = [...diagnostics, event.text];
        break;
    }
  }

  async function send() {
    const text = draft.trim();
    if (!text || !session || !myTurn) return;

    turns = [...turns, { who: 'analyst', text }];
    draft = '';
    streaming = '';
    reasoning = '';
    sendError = null;
    waitingSince = Date.now();
    session = { ...session, status: 'WAITING_AGENT' };

    try {
      await api.answerAnalysis(session.session_id, text);
    } catch (e) {
      sendError =
        e instanceof ApiError && e.status === 404
          ? 'A sessão não existe mais no servidor. As sessões vivem em memória, então um restart do uvicorn as apaga. Recomece a análise.'
          : e instanceof Error
            ? e.message
            : 'Falha ao enviar a resposta.';
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  async function closeSession() {
    if (!session) return;
    closing = true;
    sendError = null;
    try {
      await api.finishAnalysis(session.session_id);
    } catch (e) {
      sendError = e instanceof Error ? e.message : 'Falha ao encerrar a sessão.';
    } finally {
      closing = false;
    }
  }

  async function commit() {
    if (!session) return;
    committing = true;
    sendError = null;
    try {
      const tasks = await api.commitAnalysisBacklog(session.session_id);
      remember(null);
      await goto(`/projetos/${data.project.id}/backlog?novas=${tasks.length}`);
    } catch (e) {
      sendError = e instanceof Error ? e.message : 'Falha ao importar o backlog.';
    } finally {
      committing = false;
    }
  }

  async function restart() {
    if (session) {
      try {
        await api.stopAnalysis(session.session_id);
      } catch {
        /* contêiner já pode ter morrido */
      }
    }
    remember(null);
    session = null;
    boot(true);
  }

  $effect(() => {
    boot();
  });

  onDestroy(() => disposeStream?.());
</script>

<div class="grid">
  <section class="transcript-col">
    {#if starting}
      <div class="turn">
        <span class="label who">Agente</span>
        <div class="content">
          <p class="working">
            <span class="pulse" aria-hidden="true"></span>
            Subindo o contêiner e carregando as skills.
            <span class="clock"><Elapsed from={waitingSince} /></span>
          </p>
          <Skeleton variant="lines" rows={4} />
        </div>
      </div>
    {:else if startError}
      <Placeholder kind="error" title="O agente não subiu" detail={startError}>
        {#snippet action()}
          <button type="button" class="btn btn-solid" onclick={restart}>Tentar de novo</button>
          <a class="btn btn-line" href="/projetos">Voltar</a>
        {/snippet}
      </Placeholder>
    {:else}
      <ol class="transcript">
        {#each turns as turn, i (i)}
          {#if turn.who === 'tool'}
            <li class="tool-line mono">
              <Icon name="clip" size={11} /> {turn.text}
            </li>
          {:else}
            <li
              class="turn rise"
              style="--i: {Math.min(i, 6)}"
              class:is-analyst={turn.who === 'analyst'}
            >
              <span class="label who">{turn.who === 'agent' ? 'Agente' : 'Você'}</span>
              <div class="content"><p>{turn.text}</p></div>
            </li>
          {/if}
        {/each}

        {#if !myTurn && !finished}
          <li class="turn">
            <span class="label who">Agente</span>
            <div class="content">
              {#if streaming}
                <p class="live">{streaming}<span class="caret" aria-hidden="true"></span></p>
              {:else if reasoning}
                <p class="working">
                  <span class="pulse" aria-hidden="true"></span>
                  Raciocinando.
                  <span class="clock"><Elapsed from={waitingSince} /></span>
                </p>
                <!-- O raciocínio é registro de máquina, não fala: fica
                     rebaixado, e some assim que o texto de verdade começa. -->
                <p class="reasoning">{reasoning}</p>
              {:else}
                <p class="working">
                  <span class="pulse" aria-hidden="true"></span>
                  Trabalhando.
                  <span class="clock"><Elapsed from={waitingSince} /></span>
                </p>
                <Skeleton variant="lines" rows={2} />
              {/if}
            </div>
          </li>
        {/if}
      </ol>

      {#if sendError}
        <p class="error-line" role="alert">
          <Icon name="alert" size={12} />
          {sendError}
        </p>
      {/if}

      {#if diagnostics.length}
        <details class="diag">
          <summary class="label">Saída bruta do contêiner ({diagnostics.length})</summary>
          <pre class="mono">{diagnostics.join('\n')}</pre>
        </details>
      {/if}

      <div class="composer">
        <textarea
          bind:this={composer}
          bind:value={draft}
          class="textarea"
          rows="2"
          placeholder={finished
            ? 'Sessão encerrada.'
            : myTurn
              ? 'Responda ao agente…'
              : 'Aguarde — o agente está com o turno.'}
          onkeydown={onKeydown}
          disabled={!myTurn}
        ></textarea>
        <div class="composer-foot">
          <span class="help">
            <span class="mono">Enter</span> envia, <span class="mono">Shift+Enter</span> quebra linha
          </span>
          <button type="button" class="btn btn-solid" onclick={send} disabled={!myTurn || !draft.trim()}>
            Enviar <Icon name="send" size={12} />
          </button>
        </div>
      </div>
    {/if}
  </section>

  <aside>
    <div class="panel">
      <div class="panel-head">
        <h2 class="label">Sessão</h2>
        {#if myTurn}
          <span class="label turn-badge">Sua vez</span>
        {/if}
      </div>

      <dl class="meta">
        <div>
          <dt class="label">Agente</dt>
          <dd class="mono">Claude Code + superpowers</dd>
        </div>
        <div>
          <dt class="label">Contêiner</dt>
          <dd class="mono truncate">{session?.container_name ?? '—'}</dd>
        </div>
        <div>
          <dt class="label">Workspace</dt>
          <dd class="mono truncate">{data.project.repo_path}</dd>
        </div>
      </dl>

      <p class="help">
        A conversa roda dentro do contêiner. A especificação é gravada em
        <span class="mono">docs/superpowers/specs/</span> e o backlog em
        <span class="mono">.painkiller/backlog.json</span>, ambos no próprio repositório.
      </p>

      <button
        type="button"
        class="btn btn-line full"
        onclick={closeSession}
        disabled={closing || finished || !session}
      >
        {closing ? 'Encerrando…' : 'Encerrar sessão'}
      </button>

      <button
        type="button"
        class="btn btn-solid full"
        onclick={commit}
        disabled={committing || !session}
      >
        {committing ? 'Importando…' : 'Importar backlog'}
        {#if !committing}<Icon name="arrow-right" size={12} />{/if}
      </button>

      {#if finished}
        <button type="button" class="btn btn-line full" onclick={restart}>Nova sessão</button>
      {:else}
        <button
          type="button"
          class="btn btn-line full"
          onclick={() => {
            if (confirm('Deseja descartar a sessão atual e iniciar uma nova análise do zero?')) {
              restart();
            }
          }}
          disabled={starting}
        >
          Recomeçar do zero
        </button>
      {/if}
    </div>

    <!-- Painel de Documentos Superpowers -->
    <div class="panel docs-panel">
      <div class="panel-head">
        <div class="head-title">
          <h2 class="label">Docs Superpowers</h2>
          {#if docs.length}
            <span class="mono doc-count">{docs.length}</span>
          {/if}
        </div>
        <button
          type="button"
          class="refresh-btn"
          onclick={refreshDocs}
          title="Recarregar documentos"
          disabled={loadingDocs}
        >
          <Icon name="upload" size={12} />
        </button>
      </div>

      {#if loadingDocs && !docs.length}
        <div class="docs-status faint mono">
          <span class="pulse" aria-hidden="true"></span> Buscando documentos…
        </div>
      {:else if !docs.length}
        <div class="docs-empty">
          <p class="help">
            Nenhum documento gerado ainda. Conforme a elicitação avança, o agente gravará especificações e planos em <span class="mono">docs/superpowers/</span>.
          </p>
        </div>
      {:else}
        <ul class="docs-list">
          {#each docs as d (d.path)}
            <li>
              <button type="button" class="doc-item" onclick={() => openDoc(d)}>
                <div class="doc-item-header">
                  <span class="tag-cat mono {d.category}">{d.category}</span>
                  <span class="doc-title mono truncate" title={d.filename}>{d.filename}</span>
                </div>
                <div class="doc-item-foot mono faint">
                  <span>{(d.size_bytes / 1024).toFixed(1)} KB</span>
                  <span class="view-hint label">Visualizar ↗</span>
                </div>
              </button>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  </aside>
</div>

<DocViewer
  bind:open={isDocViewerOpen}
  doc={selectedDoc}
  projectId={data.project.id}
  repoUrl={data.project.repo_url}
  defaultBranch={data.project.default_branch}
/>

<style>
  .grid {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: var(--s9);
    padding-top: var(--s6);
    align-items: start;
  }

  /* Transcrição de entrevista: rótulo de fala à esquerda, texto na medida
     de leitura. Sem balões. */
  .transcript {
    border-top: 1px solid var(--rule);
  }

  .turn {
    display: grid;
    grid-template-columns: 5.5rem 1fr;
    gap: var(--s4);
    padding: var(--s5) 0;
    border-bottom: 1px solid var(--rule);
  }

  .who {
    padding-top: 0.2rem;
  }

  .is-analyst .who {
    color: var(--ink);
  }

  .content {
    min-width: 0;
    max-width: var(--measure);
  }

  .content p {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  /* A fala do analista fica recuada sobre papel rebaixado — parece
     resposta preenchida num formulário impresso. */
  .is-analyst .content {
    background: var(--paper-sunk);
    padding: var(--s3) var(--s4);
    border-left: 2px solid var(--ink);
  }

  /* Turno em andamento: mesma tipografia da fala pronta, para o texto não
     "pular" quando o evento canônico substituir o buffer. */
  .live {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  /* Cursor de digitação — a única indicação de que ainda está vindo. */
  .caret {
    display: inline-block;
    width: 0.5em;
    height: 1em;
    margin-left: 1px;
    vertical-align: text-bottom;
    background: var(--ink);
    animation: blink 1.1s var(--ease) infinite;
  }

  .reasoning {
    margin-top: var(--s2);
    padding-left: var(--s3);
    border-left: 1px solid var(--rule);
    color: var(--ink-3);
    font-size: var(--t-micro);
    line-height: 1.6;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 9rem;
    overflow-y: auto;
  }

  /* Ferramenta acionada: registro de máquina, não fala. Fica rebaixado para
     não competir com a conversa. */
  .tool-line {
    display: flex;
    align-items: center;
    gap: var(--s2);
    padding: var(--s2) 0;
    border-bottom: 1px solid var(--rule);
    color: var(--ink-3);
    font-size: var(--t-micro);
  }

  .working {
    display: flex;
    align-items: center;
    gap: var(--s2);
    color: var(--ink-2);
    font-size: var(--t-small);
    margin-bottom: var(--s3);
  }

  .clock {
    margin-left: auto;
    color: var(--ink-3);
  }

  .pulse {
    width: 6px;
    height: 6px;
    background: var(--ink);
    animation: blink 1.3s var(--ease) infinite;
  }

  .error-line {
    display: flex;
    align-items: flex-start;
    gap: var(--s2);
    margin-top: var(--s4);
    color: var(--accent);
    font-size: var(--t-small);
    max-width: var(--measure);
  }

  .diag {
    margin-top: var(--s4);
    border-top: 1px solid var(--rule);
    padding-top: var(--s3);
    max-width: var(--measure);
  }

  .diag summary {
    cursor: pointer;
    color: var(--ink-3);
  }

  .diag pre {
    margin-top: var(--s3);
    padding: var(--s3);
    background: var(--paper-sunk);
    font-size: var(--t-micro);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 18rem;
    overflow-y: auto;
  }

  .composer {
    position: sticky;
    bottom: 0;
    margin-top: var(--s5);
    padding-bottom: var(--s5);
    background: linear-gradient(to bottom, transparent, var(--paper) 18%);
  }

  .composer-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s4);
    margin-top: var(--s3);
  }

  aside {
    position: sticky;
    top: 4.5rem;
  }

  .panel {
    border-top: 1px solid var(--rule-ink);
    padding-top: var(--s3);
  }

  .panel-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s3);
  }

  /* Único uso de cor na tela, e pelo mesmo motivo de sempre: o agente parou
     e depende do analista. Ver STATUS_META.AWAITING_ANALYST. */
  .turn-badge {
    color: var(--accent);
  }

  .meta {
    margin: var(--s4) 0;
  }

  .meta div + div {
    margin-top: var(--s3);
  }

  .meta dd {
    font-size: var(--t-micro);
    color: var(--ink-2);
  }

  .full {
    width: 100%;
  }

  .full + .full {
    margin-top: var(--s3);
  }

  .help {
    margin-top: var(--s3);
    margin-bottom: var(--s4);
  }

  .docs-panel {
    margin-top: var(--s6);
  }

  .head-title {
    display: flex;
    align-items: center;
    gap: var(--s2);
  }

  .doc-count {
    font-size: var(--t-micro);
    padding: 0.05rem 0.35rem;
    border: 1px solid var(--rule-2);
    border-radius: 2px;
    color: var(--ink-2);
  }

  .refresh-btn {
    background: transparent;
    border: none;
    cursor: pointer;
    color: var(--ink-3);
    padding: var(--s1);
    display: inline-flex;
    align-items: center;
    transition: color var(--fast) var(--ease);
  }

  .refresh-btn:hover {
    color: var(--ink);
  }

  .docs-status {
    display: flex;
    align-items: center;
    gap: var(--s2);
    margin-top: var(--s3);
    font-size: var(--t-micro);
  }

  .docs-empty {
    margin-top: var(--s2);
  }

  .docs-list {
    list-style: none;
    padding: 0;
    margin: var(--s3) 0 0 0;
    display: flex;
    flex-direction: column;
    gap: var(--s2);
    max-height: 22rem;
    overflow-y: auto;
  }

  .doc-item {
    width: 100%;
    text-align: left;
    padding: var(--s2) var(--s3);
    background: var(--paper-2);
    border: 1px solid var(--rule-ink);
    cursor: pointer;
    transition: all var(--fast) var(--ease);
  }

  .doc-item:hover {
    border-color: var(--ink);
    background: var(--paper-sunk);
  }

  .doc-item-header {
    display: flex;
    align-items: center;
    gap: var(--s2);
    min-width: 0;
  }

  .tag-cat {
    font-size: var(--t-micro);
    padding: 0.1rem 0.3rem;
    border: 1px solid var(--rule-2);
    text-transform: uppercase;
    flex-shrink: 0;
  }

  .tag-cat.spec {
    border-color: var(--ink);
    color: var(--ink);
    font-weight: 600;
  }

  .tag-cat.plan {
    border-color: var(--ink-2);
    color: var(--ink);
  }

  .tag-cat.backlog {
    border-color: var(--rule-2);
    color: var(--ink-3);
  }

  .doc-title {
    font-size: var(--t-micro);
    color: var(--ink);
  }

  .doc-item-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: var(--s1);
    font-size: var(--t-micro);
  }

  .view-hint {
    color: var(--ink-2);
    font-size: var(--t-micro);
  }

  @media (max-width: 900px) {
    .grid {
      grid-template-columns: 1fr;
      gap: var(--s7);
    }

    aside {
      position: static;
      order: -1;
    }

    .turn {
      grid-template-columns: 1fr;
      gap: var(--s2);
    }
  }
</style>
