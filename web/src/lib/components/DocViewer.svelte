<script lang="ts">
  import { marked } from 'marked';
  import { api } from '$lib/api';
  import type { ProjectDoc, ProjectDocContent } from '$lib/types';
  import Modal from './Modal.svelte';
  import Icon from './Icon.svelte';
  import Skeleton from './Skeleton.svelte';

  let {
    open = $bindable(false),
    doc = null,
    projectId,
    repoUrl = null,
    defaultBranch = 'main'
  }: {
    open?: boolean;
    doc: ProjectDoc | null;
    projectId: string;
    repoUrl?: string | null;
    defaultBranch?: string;
  } = $props();

  let loading = $state(false);
  let error = $state<string | null>(null);
  let docContent = $state<ProjectDocContent | null>(null);
  let viewMode = $state<'rendered' | 'raw'>('rendered');
  let copied = $state(false);

  const renderedHtml = $derived.by(() => {
    if (!docContent?.content) return '';
    try {
      return marked.parse(docContent.content, { gfm: true, breaks: true }) as string;
    } catch {
      return `<pre class="mono">${docContent.content}</pre>`;
    }
  });

  const categoryLabel: Record<string, string> = {
    spec: 'Especificação (Design)',
    plan: 'Plano de Implementação',
    backlog: 'Backlog Decomposto',
    doc: 'Documento'
  };

  const giteaFileUrl = $derived.by(() => {
    if (!repoUrl || !doc) return null;
    return `${repoUrl.replace(/\/$/, '')}/src/branch/${defaultBranch}/${doc.path}`;
  });

  async function loadDoc() {
    if (!doc) return;
    loading = true;
    error = null;
    docContent = null;
    copied = false;
    try {
      docContent = await api.getProjectDocContent(projectId, doc.path);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Falha ao carregar conteúdo do documento.';
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (open && doc) {
      loadDoc();
    }
  });

  async function copyText() {
    if (!docContent?.content) return;
    try {
      await navigator.clipboard.writeText(docContent.content);
      copied = true;
      setTimeout(() => (copied = false), 2000);
    } catch {
      /* clipboard error */
    }
  }
</script>

<Modal bind:open title={doc?.filename ?? 'Documento'} width="54rem">
  {#snippet body()}
    <div class="doc-viewer">
      <!-- Toolbar com metadados e ações -->
      <div class="toolbar">
        <div class="doc-meta">
          <span class="category-badge mono label {doc?.category}">
            {doc ? (categoryLabel[doc.category] ?? doc.category) : ''}
          </span>
          <span class="mono faint path truncate" title={doc?.path}>{doc?.path}</span>
        </div>

        <div class="actions">
          {#if giteaFileUrl}
            <a
              href={giteaFileUrl}
              target="_blank"
              rel="noopener noreferrer"
              class="btn btn-line btn-sm"
              title="Abrir arquivo no Gitea"
            >
              <Icon name="external" size={11} /> Gitea
            </a>
          {/if}

          <div class="seg-control" role="group" aria-label="Modo de visualização">
            <button
              type="button"
              class="seg-btn"
              class:active={viewMode === 'rendered'}
              onclick={() => (viewMode = 'rendered')}
            >
              Renderizado
            </button>
            <button
              type="button"
              class="seg-btn"
              class:active={viewMode === 'raw'}
              onclick={() => (viewMode = 'raw')}
            >
              Raw
            </button>
          </div>

          <button
            type="button"
            class="btn btn-line btn-sm"
            onclick={copyText}
            disabled={!docContent?.content}
          >
            {#if copied}
              <Icon name="check" size={11} /> Copiado!
            {:else}
              <Icon name="clip" size={11} /> Copiar
            {/if}
          </button>
        </div>
      </div>

      <!-- Área de Conteúdo -->
      <div class="content-scroll">
        {#if loading}
          <div class="loading-box">
            <p class="working">
              <span class="pulse" aria-hidden="true"></span> Carregando documento…
            </p>
            <Skeleton variant="lines" rows={8} />
          </div>
        {:else if error}
          <div class="error-box">
            <Icon name="alert" size={14} />
            <p>{error}</p>
          </div>
        {:else if docContent}
          {#if viewMode === 'rendered'}
            <article class="markdown-body">
              {@html renderedHtml}
            </article>
          {:else}
            <pre class="raw-content mono">{docContent.content}</pre>
          {/if}
        {/if}
      </div>
    </div>
  {/snippet}
</Modal>

<style>
  .doc-viewer {
    display: flex;
    flex-direction: column;
    height: 72vh;
  }

  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s3);
    padding: var(--s3) var(--s5);
    border-bottom: 1px solid var(--rule-ink);
    background: var(--paper-2);
  }

  .doc-meta {
    display: flex;
    align-items: center;
    gap: var(--s3);
    min-width: 0;
  }

  .category-badge {
    display: inline-flex;
    padding: 0.15rem 0.4rem;
    font-size: var(--t-micro);
    border: 1px solid var(--rule-2);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .category-badge.spec {
    border-color: var(--ink);
    color: var(--ink);
    font-weight: 600;
  }

  .category-badge.plan {
    border-color: var(--ink-2);
    color: var(--ink);
  }

  .category-badge.backlog {
    border-color: var(--rule-2);
    color: var(--ink-2);
  }

  .path {
    font-size: var(--t-micro);
    max-width: 22rem;
  }

  .actions {
    display: flex;
    align-items: center;
    gap: var(--s2);
    flex-shrink: 0;
  }

  .seg-control {
    display: inline-flex;
    border: 1px solid var(--rule-ink);
    border-radius: 2px;
    overflow: hidden;
  }

  .seg-btn {
    padding: 0.2rem 0.6rem;
    font-size: var(--t-micro);
    background: transparent;
    border: none;
    cursor: pointer;
    color: var(--ink-3);
    transition: all var(--fast) var(--ease);
  }

  .seg-btn:hover {
    color: var(--ink);
  }

  .seg-btn.active {
    background: var(--ink);
    color: var(--paper);
    font-weight: 500;
  }

  .content-scroll {
    flex: 1;
    overflow-y: auto;
    padding: var(--s6) var(--s6);
    background: var(--paper);
  }

  .loading-box {
    padding: var(--s6) 0;
  }

  .error-box {
    display: flex;
    align-items: center;
    gap: var(--s2);
    color: var(--accent);
    padding: var(--s6);
  }

  .raw-content {
    white-space: pre-wrap;
    word-break: break-word;
    font-size: var(--t-small);
    line-height: 1.6;
    color: var(--ink);
  }

  /* Estilos do Markdown rendered */
  .markdown-body {
    line-height: 1.65;
    color: var(--ink);
    font-size: var(--t-small);
    max-width: 48rem;
  }

  .markdown-body :global(h1) {
    font-size: var(--t-h2);
    margin-top: 0;
    margin-bottom: var(--s4);
    padding-bottom: var(--s2);
    border-bottom: 1px solid var(--rule-ink);
    letter-spacing: -0.02em;
  }

  .markdown-body :global(h2) {
    font-size: var(--t-h3);
    margin-top: var(--s6);
    margin-bottom: var(--s3);
    letter-spacing: -0.01em;
  }

  .markdown-body :global(h3) {
    font-size: var(--t-body);
    margin-top: var(--s5);
    margin-bottom: var(--s2);
    font-weight: 600;
  }

  .markdown-body :global(p) {
    margin-top: 0;
    margin-bottom: var(--s4);
  }

  .markdown-body :global(ul),
  .markdown-body :global(ol) {
    margin-top: 0;
    margin-bottom: var(--s4);
    padding-left: 1.25rem;
  }

  .markdown-body :global(li) {
    margin-bottom: var(--s1);
  }

  .markdown-body :global(pre) {
    background: var(--paper-2);
    padding: var(--s3) var(--s4);
    border: 1px solid var(--rule-ink);
    overflow-x: auto;
    font-family: var(--font-mono, monospace);
    font-size: var(--t-micro);
    margin-bottom: var(--s4);
  }

  .markdown-body :global(code) {
    font-family: var(--font-mono, monospace);
    background: var(--paper-2);
    padding: 0.1em 0.3em;
    font-size: 0.9em;
  }

  .markdown-body :global(pre code) {
    background: transparent;
    padding: 0;
  }

  .markdown-body :global(blockquote) {
    margin: 0 0 var(--s4) 0;
    padding-left: var(--s4);
    border-left: 2px solid var(--rule-2);
    color: var(--ink-2);
  }

  .markdown-body :global(hr) {
    border: none;
    border-top: 1px solid var(--rule-ink);
    margin: var(--s6) 0;
  }
</style>
