<script lang="ts">
  import { goto } from '$app/navigation';
  import { marked } from 'marked';
  import { analysisFor } from '$lib/stores/analysis.svelte';
  import type { ProjectDoc } from '$lib/types';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';
  import Elapsed from '$lib/components/Elapsed.svelte';
  import DocViewer from '$lib/components/DocViewer.svelte';
  import Choices from '$lib/components/Choices.svelte';
  import { parseMessage, hidePartialBlock } from '$lib/choices';

  let { data } = $props();

  /* A sessão vive num módulo, não neste componente: trocar de aba e voltar
     não fecha o stream nem remonta a conversa. Ver stores/analysis.svelte.ts. */
  const a = $derived(analysisFor(data.project.id));

  let composer = $state<HTMLTextAreaElement | null>(null);
  let scroller = $state<HTMLElement | null>(null);
  let host = $state<HTMLElement | null>(null);
  let menuOpen = $state(false);

  /** O leitor está colado no fim? Só então o auto-scroll pode agir. */
  let pinned = $state(true);

  let selectedDoc = $state<ProjectDoc | null>(null);
  let viewerOpen = $state(false);

  /* A área útil não dá para escrever em CSS: o cabeçalho do projeto tem altura
     variável (título + abas). Medimos uma vez e a cada resize. */
  let avail = $state(0);

  $effect(() => {
    if (!host) return;
    const recompute = () => {
      const top = host!.getBoundingClientRect().top + window.scrollY;
      avail = Math.max(420, window.innerHeight - top - 16);
    };
    recompute();
    window.addEventListener('resize', recompute);
    return () => window.removeEventListener('resize', recompute);
  });

  $effect(() => {
    a.ensureBooted();
  });

  /* Menu sem biblioteca: fecha no clique fora e no Esc, como se espera. */
  $effect(() => {
    if (!menuOpen) return;
    const away = (e: MouseEvent) => {
      if (!(e.target as HTMLElement)?.closest('.menu')) menuOpen = false;
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') menuOpen = false;
    };
    window.addEventListener('click', away, true);
    window.addEventListener('keydown', esc);
    return () => {
      window.removeEventListener('click', away, true);
      window.removeEventListener('keydown', esc);
    };
  });

  function onScroll() {
    if (!scroller) return;
    const gap = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
    pinned = gap < 48;
  }

  function toBottom() {
    scroller?.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
    pinned = true;
  }

  /* Segue a conversa sozinho, mas só enquanto o analista já estava no fim —
     puxar a tela de quem voltou para reler é pior que não rolar nada. */
  $effect(() => {
    void a.turns.length;
    void a.streaming;
    void a.reasoning;
    void a.starting;
    if (!scroller || !pinned) return;
    queueMicrotask(() => scroller?.scrollTo({ top: scroller.scrollHeight }));
  });

  $effect(() => {
    if (a.myTurn) queueMicrotask(() => composer?.focus());
  });

  function renderMarkdown(content: string): string {
    if (!content) return '';
    try {
      return marked.parse(content, { gfm: true, breaks: true }) as string;
    } catch {
      return `<p>${content}</p>`;
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      a.send();
    }
  }

  async function importBacklog() {
    const tasks = await a.commit();
    if (tasks) await goto(`/projetos/${data.project.id}/backlog?novas=${tasks.length}`);
  }

  function confirmRestart() {
    menuOpen = false;
    if (a.finished || confirm('Descartar a sessão atual e iniciar uma nova análise do zero?')) {
      a.restart();
    }
  }

  function openDoc(d: ProjectDoc) {
    selectedDoc = d;
    viewerOpen = true;
  }

  /** Um rótulo só para o estado da sessão — é o que a toolbar precisa dizer. */
  const phase = $derived.by(() => {
    if (a.startError) return { key: 'error', text: 'O agente não subiu' };
    if (a.starting) return { key: 'boot', text: 'Subindo o contêiner' };
    if (a.session?.status === 'FAILED') return { key: 'error', text: 'Sessão falhou' };
    if (a.finished) return { key: 'done', text: 'Sessão encerrada' };
    if (a.myTurn) return { key: 'you', text: 'Sua vez' };
    return { key: 'agent', text: 'Agente trabalhando' };
  });
</script>

<div class="workbench" bind:this={host} style="height: {avail ? `${avail}px` : '70vh'}">
  <!-- Toolbar: estado à esquerda, ações à direita, hierarquia explícita.
       A ação que conclui a etapa é a única sólida. -->
  <div class="toolbar">
    <div class="state" class:is-you={phase.key === 'you'} class:is-error={phase.key === 'error'}>
      {#if phase.key === 'boot' || phase.key === 'agent'}
        <span class="pulse" aria-hidden="true"></span>
      {:else if phase.key === 'you'}
        <span class="dot" aria-hidden="true"></span>
      {/if}
      <span class="label">{phase.text}</span>
      {#if phase.key === 'boot' || phase.key === 'agent'}
        <span class="clock mono"><Elapsed from={a.waitingSince} /></span>
      {/if}
    </div>

    <div class="acts">
      <button
        type="button"
        class="btn btn-line btn-sm"
        onclick={() => a.closeSession()}
        disabled={a.closing || a.finished || !a.session}
      >
        {a.closing ? 'Encerrando…' : 'Encerrar'}
      </button>

      <button
        type="button"
        class="btn btn-solid btn-sm"
        onclick={importBacklog}
        disabled={a.committing || !a.session}
      >
        {a.committing ? 'Importando…' : 'Importar backlog'}
        {#if !a.committing}<Icon name="arrow-right" size={12} />{/if}
      </button>

      <div class="menu">
        <button
          type="button"
          class="btn btn-quiet btn-sm more"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onclick={() => (menuOpen = !menuOpen)}
        >
          <span aria-hidden="true">···</span>
          <span class="sr">Mais ações</span>
        </button>
        {#if menuOpen}
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div class="sheet" role="menu">
            <button type="button" role="menuitem" onclick={confirmRestart} disabled={a.starting}>
              {a.finished ? 'Nova sessão' : 'Recomeçar do zero'}
            </button>
            <a role="menuitem" href="/projetos/{data.project.id}/artefatos" onclick={() => (menuOpen = false)}>
              Ver artefatos
            </a>
          </div>
        {/if}
      </div>
    </div>
  </div>

  <div class="panes">
    <section class="chat">
      {#if a.startError}
        <div class="scroller">
          <Placeholder kind="error" title="O agente não subiu" detail={a.startError}>
            {#snippet action()}
              <button type="button" class="btn btn-solid" onclick={() => a.boot(true)}>
                Tentar de novo
              </button>
              <a class="btn btn-line" href="/projetos">Voltar</a>
            {/snippet}
          </Placeholder>
        </div>
      {:else}
        <div class="scroller" bind:this={scroller} onscroll={onScroll}>
          <ol class="transcript">
            {#if a.starting}
              <li class="turn">
                <span class="label who">Agente</span>
                <div class="content">
                  <p class="working">
                    <span class="pulse" aria-hidden="true"></span>
                    Subindo o contêiner e carregando as skills.
                  </p>
                  <Skeleton variant="lines" rows={4} />
                </div>
              </li>
            {/if}

            {#each a.turns as turn, i (i)}
              {@const parsed = turn.who === 'agent' ? parseMessage(turn.text) : null}
              <li class="turn" class:is-analyst={turn.who === 'analyst'}>
                <span class="label who">{turn.who === 'agent' ? 'Agente' : 'Você'}</span>
                <div class="content">
                  <div class="markdown-body">
                    {@html renderMarkdown(parsed ? parsed.body : turn.text)}
                  </div>
                  {#if parsed?.choices}
                    <Choices
                      choices={parsed.choices}
                      active={a.myTurn && i === a.turns.length - 1}
                      answer={a.turns[i + 1]?.who === 'analyst' ? a.turns[i + 1].text : undefined}
                      onsubmit={(text) => a.send(text)}
                    />
                  {/if}
                </div>
              </li>
            {/each}

            {#if !a.myTurn && !a.finished && !a.starting}
              <li class="turn">
                <span class="label who">Agente</span>
                <div class="content">
                  {#if a.streaming}
                    <div class="markdown-body live-streaming">
                      {@html renderMarkdown(hidePartialBlock(a.streaming))}<span class="caret" aria-hidden="true"></span>
                    </div>
                  {:else if a.reasoning}
                    <p class="working">
                      <span class="pulse" aria-hidden="true"></span> Raciocinando.
                    </p>
                    <!-- O raciocínio é registro de máquina, não fala: fica
                         rebaixado, e some assim que o texto de verdade começa. -->
                    <p class="reasoning">{a.reasoning}</p>
                  {:else}
                    <p class="working">
                      <span class="pulse" aria-hidden="true"></span> Trabalhando.
                    </p>
                    <Skeleton variant="lines" rows={2} />
                  {/if}
                </div>
              </li>
            {/if}
          </ol>

          {#if a.diagnostics.length}
            <details class="diag">
              <summary class="label">Saída bruta do contêiner ({a.diagnostics.length})</summary>
              <pre class="mono">{a.diagnostics.join('\n')}</pre>
            </details>
          {/if}
        </div>

        {#if !pinned}
          <button type="button" class="jump label" onclick={toBottom}>
            Ir para o fim ↓
          </button>
        {/if}

        {#if a.sendError}
          <p class="error-line" role="alert">
            <Icon name="alert" size={12} />
            {a.sendError}
          </p>
        {/if}

        <div class="composer">
          <textarea
            bind:this={composer}
            bind:value={a.draft}
            class="textarea"
            rows="2"
            placeholder={a.finished
              ? 'Sessão encerrada.'
              : a.myTurn
                ? 'Responda ao agente…'
                : 'Aguarde — o agente está com o turno.'}
            onkeydown={onKeydown}
            disabled={!a.myTurn}
          ></textarea>
          <div class="composer-foot">
            <span class="help">
              <span class="mono">Enter</span> envia, <span class="mono">Shift+Enter</span> quebra linha
            </span>
            <button
              type="button"
              class="btn btn-solid btn-sm"
              onclick={() => a.send()}
              disabled={!a.myTurn || !a.draft.trim()}
            >
              Enviar <Icon name="send" size={12} />
            </button>
          </div>
        </div>
      {/if}
    </section>

    <aside class="rail">
      <div class="panel">
        <h2 class="label">Sessão</h2>
        <dl class="meta">
          <div>
            <dt class="label">Contêiner</dt>
            <dd class="mono truncate">{a.session?.container_name ?? '—'}</dd>
          </div>
          <div>
            <dt class="label">Workspace</dt>
            <dd class="mono truncate" title={data.project.repo_path}>{data.project.repo_path}</dd>
          </div>
        </dl>
      </div>

      <div class="panel grow">
        <div class="panel-head">
          <h2 class="label">Artefatos</h2>
          <a class="label more-link" href="/projetos/{data.project.id}/artefatos">Ver todos ↗</a>
        </div>

        {#if a.loadingDocs && !a.docs.length}
          <p class="docs-status faint mono">
            <span class="pulse" aria-hidden="true"></span> Buscando…
          </p>
        {:else if !a.docs.length}
          <p class="help">
            Nada gravado ainda. Conforme a elicitação avança, o agente escreve a
            especificação e o plano em <span class="mono">docs/superpowers/</span>.
          </p>
        {:else}
          <ul class="docs">
            {#each a.docs.slice(0, 6) as d (d.path)}
              <li>
                <button type="button" class="doc" onclick={() => openDoc(d)}>
                  <span class="cat mono {d.category}">{d.category}</span>
                  <span class="mono truncate" title={d.filename}>{d.filename}</span>
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      </div>
    </aside>
  </div>
</div>

<DocViewer
  bind:open={viewerOpen}
  doc={selectedDoc}
  projectId={data.project.id}
  repoUrl={data.project.repo_url}
  defaultBranch={data.project.default_branch}
/>

<style>
  /* O `main` do layout raiz reserva um rodapé de var(--s9) para páginas que
     rolam. Esta não rola: cancelamos, senão sobra uma barra de rolagem morta. */
  .workbench {
    display: flex;
    flex-direction: column;
    min-height: 0;
    margin-bottom: calc(-1 * var(--s9));
    padding-top: var(--s4);
  }

  /* ---------- Toolbar ---------- */

  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s4);
    flex-wrap: wrap;
    padding-bottom: var(--s3);
    border-bottom: 1px solid var(--rule-ink);
  }

  .state {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    color: var(--ink-2);
    min-width: 0;
  }

  /* Único uso de cor na tela, e pelo mesmo motivo de sempre: o agente parou
     e depende do analista. Ver STATUS_META.AWAITING_ANALYST. */
  .state.is-you,
  .state.is-error {
    color: var(--accent);
  }

  .dot {
    width: 7px;
    height: 7px;
    background: var(--accent);
  }

  .clock {
    color: var(--ink-3);
    font-size: var(--t-micro);
  }

  .acts {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
  }

  .menu {
    position: relative;
  }

  .more {
    letter-spacing: 0.1em;
  }

  .sheet {
    position: absolute;
    right: 0;
    top: calc(100% + var(--s2));
    z-index: 30;
    min-width: 13rem;
    background: var(--paper);
    border: 1px solid var(--rule-ink);
    display: flex;
    flex-direction: column;
  }

  .sheet > :global(*) {
    padding: var(--s2) var(--s3);
    text-align: left;
    font-size: var(--t-small);
    color: var(--ink);
    background: transparent;
    border: 0;
    cursor: pointer;
  }

  .sheet > :global(* + *) {
    border-top: 1px solid var(--rule);
  }

  .sheet > :global(*:hover) {
    background: var(--paper-sunk);
  }

  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }

  /* ---------- Painéis ---------- */

  .panes {
    display: grid;
    grid-template-columns: 1fr 17rem;
    gap: var(--s6);
    flex: 1;
    min-height: 0;
  }

  .chat {
    display: flex;
    flex-direction: column;
    min-height: 0;
    position: relative;
  }

  /* A rolagem é daqui, não do documento: o composer fica ancorado e a página
     inteira para de correr enquanto o agente escreve. */
  .scroller {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding-right: var(--s4);
  }

  .jump {
    position: absolute;
    left: 50%;
    transform: translateX(-50%);
    bottom: 7.5rem;
    z-index: 5;
    padding: var(--s2) var(--s3);
    background: var(--paper);
    border: 1px solid var(--rule-ink);
    color: var(--ink);
    cursor: pointer;
  }

  .rail {
    display: flex;
    flex-direction: column;
    gap: var(--s5);
    min-height: 0;
    border-left: 1px solid var(--rule);
    padding-left: var(--s5);
  }

  .panel {
    border-top: 1px solid var(--rule-ink);
    padding-top: var(--s3);
    min-height: 0;
  }

  .panel.grow {
    display: flex;
    flex-direction: column;
    flex: 1;
  }

  .panel-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--s3);
  }

  .more-link {
    color: var(--ink-3);
    transition: color var(--fast) var(--ease);
  }

  .more-link:hover {
    color: var(--ink);
  }

  .meta {
    margin-top: var(--s3);
  }

  .meta div + div {
    margin-top: var(--s3);
  }

  .meta dd {
    font-size: var(--t-micro);
    color: var(--ink-2);
  }

  .docs {
    margin-top: var(--s3);
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: var(--s2);
  }

  .doc {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--s2);
    min-width: 0;
    padding: var(--s2);
    text-align: left;
    background: transparent;
    border: 1px solid var(--rule);
    cursor: pointer;
    font-size: var(--t-micro);
    color: var(--ink);
    transition: border-color var(--fast) var(--ease);
  }

  .doc:hover {
    border-color: var(--ink);
  }

  .cat {
    flex-shrink: 0;
    font-size: var(--t-micro);
    padding: 0.05rem 0.3rem;
    border: 1px solid var(--rule-2);
    text-transform: uppercase;
    color: var(--ink-3);
  }

  .cat.spec {
    border-color: var(--ink);
    color: var(--ink);
    font-weight: 600;
  }

  .cat.plan {
    border-color: var(--ink-2);
    color: var(--ink);
  }

  .docs-status {
    display: flex;
    align-items: center;
    gap: var(--s2);
    margin-top: var(--s3);
    font-size: var(--t-micro);
  }

  /* ---------- Transcrição ---------- */

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

  /* A fala do analista fica recuada sobre papel rebaixado — parece
     resposta preenchida num formulário impresso. */
  .is-analyst .content {
    background: var(--paper-sunk);
    padding: var(--s3) var(--s4);
    border-left: 2px solid var(--ink);
  }

  .markdown-body {
    line-height: 1.6;
    color: var(--ink);
    font-size: var(--t-body);
    word-break: break-word;
  }

  .markdown-body :global(h1),
  .markdown-body :global(h2),
  .markdown-body :global(h3),
  .markdown-body :global(h4) {
    color: var(--ink);
    font-weight: 600;
    margin-top: var(--s4);
    margin-bottom: var(--s2);
    letter-spacing: -0.01em;
  }

  .markdown-body :global(h1:first-child),
  .markdown-body :global(h2:first-child),
  .markdown-body :global(h3:first-child),
  .markdown-body :global(h4:first-child) {
    margin-top: 0;
  }

  .markdown-body :global(h1) {
    font-size: var(--t-h3);
  }

  .markdown-body :global(h2) {
    font-size: var(--t-body);
    font-weight: 700;
  }

  .markdown-body :global(h3) {
    font-size: var(--t-body);
    font-weight: 600;
  }

  .markdown-body :global(h4) {
    font-size: var(--t-small);
    font-weight: 600;
  }

  .markdown-body :global(p) {
    margin-top: 0;
    margin-bottom: var(--s3);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .markdown-body :global(p:last-child) {
    margin-bottom: 0;
  }

  .markdown-body :global(ul),
  .markdown-body :global(ol) {
    margin-top: 0;
    margin-bottom: var(--s3);
    padding-left: 1.4rem;
  }

  .markdown-body :global(li) {
    margin-bottom: var(--s1);
  }

  .markdown-body :global(li:last-child) {
    margin-bottom: 0;
  }

  .markdown-body :global(strong),
  .markdown-body :global(b) {
    font-weight: 600;
    color: var(--ink);
  }

  .markdown-body :global(code) {
    font-family: var(--font-mono, monospace);
    font-size: 0.9em;
    background: var(--paper-sunk);
    padding: 0.15em 0.35em;
    border: 1px solid var(--rule);
  }

  .markdown-body :global(pre) {
    background: var(--paper-sunk);
    border: 1px solid var(--rule-ink);
    padding: var(--s3) var(--s4);
    margin: var(--s3) 0;
    overflow-x: auto;
    font-family: var(--font-mono, monospace);
    font-size: var(--t-micro);
    line-height: 1.5;
  }

  .markdown-body :global(pre code) {
    background: transparent;
    padding: 0;
    border: none;
    font-size: 1em;
  }

  .markdown-body :global(blockquote) {
    margin: var(--s3) 0;
    padding-left: var(--s4);
    border-left: 3px solid var(--rule-ink);
    color: var(--ink-2);
  }

  .markdown-body :global(hr) {
    border: none;
    border-top: 1px solid var(--rule);
    margin: var(--s4) 0;
  }

  .markdown-body :global(table) {
    width: 100%;
    border-collapse: collapse;
    margin: var(--s3) 0;
    font-size: var(--t-small);
  }

  .markdown-body :global(th),
  .markdown-body :global(td) {
    padding: var(--s2) var(--s3);
    border: 1px solid var(--rule);
    text-align: left;
  }

  .markdown-body :global(th) {
    background: var(--paper-sunk);
    font-weight: 600;
  }

  .live-streaming {
    position: relative;
  }

  .live-streaming :global(p:last-child) {
    display: inline;
  }

  /* Cursor de digitação — a única indicação de que ainda está vindo. */
  .caret {
    display: inline-block;
    width: 0.5em;
    height: 1em;
    margin-left: 2px;
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

  .working {
    display: flex;
    align-items: center;
    gap: var(--s2);
    color: var(--ink-2);
    font-size: var(--t-small);
    margin-bottom: var(--s3);
  }

  .pulse {
    width: 6px;
    height: 6px;
    background: var(--ink);
    animation: blink 1.3s var(--ease) infinite;
    flex-shrink: 0;
  }

  .error-line {
    display: flex;
    align-items: flex-start;
    gap: var(--s2);
    margin-top: var(--s3);
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

  /* ---------- Composer ---------- */

  .composer {
    flex-shrink: 0;
    padding-top: var(--s4);
    margin-top: var(--s2);
    border-top: 1px solid var(--rule-ink);
  }

  .composer-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s4);
    margin-top: var(--s3);
  }

  @media (max-width: 900px) {
    /* Sem altura fixa no celular: a tela é curta demais para dois painéis. */
    .workbench {
      height: auto !important;
      margin-bottom: 0;
    }

    .panes {
      grid-template-columns: 1fr;
      gap: var(--s6);
    }

    .rail {
      border-left: 0;
      padding-left: 0;
      order: -1;
    }

    .scroller {
      overflow: visible;
      padding-right: 0;
    }

    .turn {
      grid-template-columns: 1fr;
      gap: var(--s2);
    }

    .jump {
      display: none;
    }
  }
</style>
