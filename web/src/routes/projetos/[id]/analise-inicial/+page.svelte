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
  import Modal from '$lib/components/Modal.svelte';
  import { parseMessage, hidePartialBlock } from '$lib/choices';

  let { data } = $props();

  /* A sessão vive num módulo, não neste componente: trocar de aba e voltar
     não fecha o stream nem remonta a conversa. Ver stores/analysis.svelte.ts. */
  const a = $derived(analysisFor(data.project.id));

  let composer = $state<HTMLTextAreaElement | null>(null);
  let scroller = $state<HTMLElement | null>(null);
  let host = $state<HTMLElement | null>(null);
  let menuOpen = $state(false);
  let artifactsOpen = $state(false);
  let sessionModalOpen = $state(false);
  let copiedField = $state<string | null>(null);

  /** O leitor está colado no fim? Só então o auto-scroll pode agir. */
  let pinned = $state(true);

  /* As perguntas do agente chegam como formulário (Choices.svelte), então a
     caixa livre só aparece quando a última fala não trouxe o bloco — sem ela o
     analista ficaria sem como responder. */
  const needsComposer = $derived.by(() => {
    if (!a.myTurn) return false;
    const last = a.turns[a.turns.length - 1];
    return !(last?.who === 'agent' && parseMessage(last.text).choices);
  });

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

  async function copyToClipboard(text: string, field: string) {
    try {
      await navigator.clipboard.writeText(text);
      copiedField = field;
      setTimeout(() => {
        if (copiedField === field) copiedField = null;
      }, 2000);
    } catch {
      // ignore
    }
  }

  /* Menus sem biblioteca: fecham no clique fora e no Esc, como se espera. */
  $effect(() => {
    if (!menuOpen && !artifactsOpen) return;
    const away = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (menuOpen && !target?.closest('.menu')) menuOpen = false;
      if (artifactsOpen && !target?.closest('.artifacts-menu')) artifactsOpen = false;
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        menuOpen = false;
        artifactsOpen = false;
      }
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

  function handleChoiceSubmit(text: string) {
    if (
      text.toLowerCase().includes('seguir para backlog') ||
      text.toLowerCase().includes('importar backlog') ||
      text.toLowerCase().includes('abrir backlog')
    ) {
      importBacklog();
    } else {
      a.send(text);
    }
  }

  function hasBacklogCreated(text: string): boolean {
    const lower = text.toLowerCase();
    return (
      lower.includes('backlog.json') ||
      (lower.includes('backlog') && lower.includes('tarefas planejadas')) ||
      (lower.includes('backlog') && lower.includes('critérios de aceitação'))
    );
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
      <!-- Artefatos Dropdown -->
      <div class="artifacts-menu">
        <button
          type="button"
          class="btn btn-line btn-sm artifacts-btn"
          class:open={artifactsOpen}
          aria-haspopup="menu"
          aria-expanded={artifactsOpen}
          onclick={() => (artifactsOpen = !artifactsOpen)}
          title="Ver documentos e especificações gerados"
        >
          <Icon name="file-text" size={13} />
          <span>Artefatos</span>
          {#if a.docs.length > 0}
            <span class="badge mono">{a.docs.length}</span>
          {/if}
          <span class="chevron" aria-hidden="true">{artifactsOpen ? '▴' : '▾'}</span>
        </button>

        {#if artifactsOpen}
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div class="sheet artifacts-sheet" role="menu">
            <div class="sheet-head">
              <span class="label">Artefatos do Projeto</span>
              <a href="/projetos/{data.project.id}/artefatos" class="label view-all" onclick={() => (artifactsOpen = false)}>
                Ver todos ↗
              </a>
            </div>

            {#if a.loadingDocs && !a.docs.length}
              <p class="sheet-status faint mono">
                <span class="pulse" aria-hidden="true"></span> Buscando…
              </p>
            {:else if !a.docs.length}
              <p class="sheet-empty faint">
                Nenhum artefato gravado ainda.<br />
                O agente gera arquivos em <span class="mono">docs/superpowers/</span> durante a conversa.
              </p>
            {:else}
              <ul class="sheet-list">
                {#each a.docs as d (d.path)}
                  <li>
                    <button
                      type="button"
                      class="sheet-doc-btn"
                      onclick={() => {
                        artifactsOpen = false;
                        openDoc(d);
                      }}
                    >
                      <span class="cat mono {d.category}">{d.category}</span>
                      <span class="sheet-doc-title mono truncate" title={d.filename}>{d.filename}</span>
                      <span class="doc-arrow" aria-hidden="true">→</span>
                    </button>
                  </li>
                {/each}
              </ul>
            {/if}
          </div>
        {/if}
      </div>

      {#if data.project.repo_url}
        <a
          href={data.project.repo_url}
          target="_blank"
          rel="noopener noreferrer"
          class="btn btn-line btn-sm repo-link"
          title="Abrir repositório externo"
        >
          <span>Repositório</span>
          <Icon name="external" size={11} />
        </a>
      {/if}

      <!-- Menu Mais Ações (...) -->
      <div class="menu">
        <button
          type="button"
          class="btn btn-line btn-sm more"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onclick={() => (menuOpen = !menuOpen)}
          title="Mais opções e detalhes"
        >
          <span aria-hidden="true">···</span>
          <span class="sr">Mais ações</span>
        </button>
        {#if menuOpen}
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div class="sheet" role="menu">
            <button
              type="button"
              role="menuitem"
              onclick={() => {
                menuOpen = false;
                sessionModalOpen = true;
              }}
            >
              <Icon name="info" size={12} />
              <span>Detalhes da sessão</span>
            </button>
            <button type="button" role="menuitem" onclick={confirmRestart} disabled={a.starting}>
              <Icon name="play" size={12} />
              <span>{a.finished ? 'Nova sessão' : 'Recomeçar do zero'}</span>
            </button>
            <button
              type="button"
              role="menuitem"
              class="danger-action"
              onclick={() => {
                menuOpen = false;
                a.closeSession();
              }}
              disabled={a.closing || a.finished || !a.session}
            >
              <Icon name="close" size={12} />
              <span>{a.closing ? 'Encerrando…' : 'Encerrar sessão'}</span>
            </button>
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
              {@const showBacklogAction =
                turn.who === 'agent' &&
                (hasBacklogCreated(turn.text) ||
                  (parsed?.choices?.options.some((o) =>
                    o.label.toLowerCase().includes('seguir para backlog') ||
                    o.label.toLowerCase().includes('backlog')
                  ) ?? false))}
              <li class="turn" class:is-analyst={turn.who === 'analyst'}>
                <span class="label who">{turn.who === 'agent' ? 'Agente' : 'Você'}</span>
                <div class="content">
                  <div class="markdown-body">
                    {@html renderMarkdown(parsed ? parsed.body : turn.text)}
                  </div>
                  {#if showBacklogAction}
                    <div class="backlog-handoff">
                      <button
                        type="button"
                        class="btn btn-solid btn-sm follow-backlog-btn"
                        onclick={importBacklog}
                        disabled={a.committing}
                        title="Importar tarefas geradas e seguir para o backlog"
                      >
                        <span>{a.committing ? 'Importando tarefas…' : 'Seguir para backlog'}</span>
                        <Icon name="arrow-right" size={12} />
                      </button>
                    </div>
                  {:else if parsed?.choices}
                    <Choices
                      choices={parsed.choices}
                      active={a.myTurn && i === a.turns.length - 1}
                      answer={a.turns[i + 1]?.who === 'analyst' ? a.turns[i + 1].text : undefined}
                      onsubmit={(text) => handleChoiceSubmit(text)}
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
          <button type="button" class="jump label" class:low={!needsComposer} onclick={toBottom}>
            Ir para o fim ↓
          </button>
        {/if}

        {#if a.sendError}
          <p class="error-line" role="alert">
            <Icon name="alert" size={12} />
            {a.sendError}
          </p>
        {/if}

        {#if needsComposer}
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
      {/if}
    </section>
  </div>
</div>

<DocViewer
  bind:open={viewerOpen}
  doc={selectedDoc}
  projectId={data.project.id}
  repoUrl={data.project.repo_url}
  defaultBranch={data.project.default_branch}
/>

<Modal
  bind:open={sessionModalOpen}
  title="Detalhes da Sessão"
  width="38rem"
>
  {#snippet body()}
    <div class="session-details">
      <div class="detail-row">
        <span class="detail-label label">Contêiner Docker</span>
        <div class="detail-box">
          <code class="mono detail-val">{a.session?.container_name ?? '—'}</code>
          {#if a.session?.container_name}
            <button
              type="button"
              class="btn btn-quiet btn-sm copy-btn"
              onclick={() => a.session?.container_name && copyToClipboard(a.session.container_name, 'container')}
              title="Copiar nome do contêiner"
            >
              <Icon name={copiedField === 'container' ? 'check' : 'copy'} size={12} />
              <span>{copiedField === 'container' ? 'Copiado!' : 'Copiar'}</span>
            </button>
          {/if}
        </div>
      </div>

      <div class="detail-row">
        <span class="detail-label label">Workspace Local</span>
        <div class="detail-box">
          <code class="mono detail-val truncate" title={data.project.repo_path}>{data.project.repo_path}</code>
          {#if data.project.repo_path}
            <button
              type="button"
              class="btn btn-quiet btn-sm copy-btn"
              onclick={() => copyToClipboard(data.project.repo_path, 'workspace')}
              title="Copiar caminho do workspace"
            >
              <Icon name={copiedField === 'workspace' ? 'check' : 'copy'} size={12} />
              <span>{copiedField === 'workspace' ? 'Copiado!' : 'Copiar'}</span>
            </button>
          {/if}
        </div>
      </div>

      <div class="detail-row">
        <span class="detail-label label">Status Operacional</span>
        <div class="detail-box plain">
          <span class="mono detail-val">{a.session?.status ?? (a.starting ? 'SUBINDO' : 'DISPONÍVEL')}</span>
        </div>
      </div>
    </div>
  {/snippet}
  {#snippet footer()}
    <button type="button" class="btn btn-solid btn-sm" onclick={() => (sessionModalOpen = false)}>
      Fechar
    </button>
  {/snippet}
</Modal>

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
    flex-wrap: wrap;
  }

  /* Dropdown de Artefatos no Topo */
  .artifacts-menu {
    position: relative;
  }

  .artifacts-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
  }

  .artifacts-btn.open {
    background: var(--paper-sunk);
    border-color: var(--ink);
  }

  .artifacts-btn .badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0 0.35rem;
    height: 1.15rem;
    font-size: var(--t-micro);
    background: var(--paper-sunk);
    border: 1px solid var(--rule-2);
    color: var(--ink);
  }

  .artifacts-btn .chevron {
    font-size: 0.65rem;
    color: var(--ink-3);
  }

  .artifacts-sheet {
    width: 22rem;
    max-width: calc(100vw - 2rem);
  }

  .sheet-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--s2) var(--s3);
    border-bottom: 1px solid var(--rule-ink);
    background: var(--paper-sunk);
  }

  .view-all {
    color: var(--ink-3);
    font-size: var(--t-micro);
    transition: color var(--fast) var(--ease);
  }

  .view-all:hover {
    color: var(--ink);
  }

  .sheet-status,
  .sheet-empty {
    padding: var(--s3) var(--s4);
    font-size: var(--t-small);
    line-height: 1.5;
    margin: 0;
  }

  .sheet-list {
    max-height: 18rem;
    overflow-y: auto;
  }

  .sheet-doc-btn {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--s2);
    padding: var(--s2) var(--s3);
    border: 0;
    border-bottom: 1px solid var(--rule);
    background: transparent;
    text-align: left;
    cursor: pointer;
    font-size: var(--t-micro);
    color: var(--ink);
    transition: background var(--fast) var(--ease);
  }

  .sheet-doc-btn:hover {
    background: var(--paper-sunk);
  }

  .sheet-doc-title {
    flex: 1;
    min-width: 0;
  }

  .doc-arrow {
    color: var(--ink-4);
    transition: transform var(--fast) var(--ease), color var(--fast) var(--ease);
  }

  .sheet-doc-btn:hover .doc-arrow {
    color: var(--ink);
    transform: translateX(2px);
  }

  .repo-link {
    display: inline-flex;
    align-items: center;
    gap: var(--s1);
  }

  .backlog-handoff {
    margin-top: var(--s4);
    padding-top: var(--s3);
    border-top: 1px solid var(--rule-2);
    display: flex;
    align-items: center;
    gap: var(--s3);
  }

  .follow-backlog-btn {
    padding: 0.5rem 1rem;
    font-size: var(--t-small);
    font-weight: 500;
    gap: var(--s2);
  }

  .danger-action {
    color: var(--accent) !important;
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
    min-width: 14rem;
    background: var(--paper);
    border: 1px solid var(--rule-ink);
    display: flex;
    flex-direction: column;
    box-shadow: 0 16px 36px -12px rgba(20, 20, 22, 0.2);
  }

  .sheet > :global(*) {
    display: flex;
    align-items: center;
    gap: var(--s2);
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

  /* Modal de Detalhes da Sessão */
  .session-details {
    display: flex;
    flex-direction: column;
    gap: var(--s4);
    padding-block: var(--s3);
  }

  .detail-row {
    display: flex;
    flex-direction: column;
    gap: var(--s1);
  }

  .detail-box {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s3);
    background: var(--paper-sunk);
    border: 1px solid var(--rule);
    padding: var(--s2) var(--s3);
  }

  .detail-box.plain {
    background: transparent;
    border-color: var(--rule);
  }

  .detail-val {
    font-size: var(--t-small);
    color: var(--ink);
    user-select: all;
  }

  .copy-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--s1);
    flex-shrink: 0;
  }

  /* ---------- Painéis ---------- */

  .panes {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
  }

  .chat {
    display: flex;
    flex-direction: column;
    flex: 1;
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
    max-width: 100%;
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

  .jump.low {
    bottom: var(--s4);
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
    /* Sem altura fixa no celular: a rolagem corre naturalmente. */
    .workbench {
      height: auto !important;
      margin-bottom: 0;
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
