<script lang="ts">
  import { api } from '$lib/api';
  import type { ProjectDoc } from '$lib/types';
  import Icon from '$lib/components/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Placeholder from '$lib/components/Placeholder.svelte';
  import DocViewer from '$lib/components/DocViewer.svelte';
  import { getProjectSessionStore } from '$lib/stores/session.svelte';

  let { data } = $props();

  const sessionStore = $derived(getProjectSessionStore(data.project.id));
  const activeSession = $derived(sessionStore.activeSession);

  let docs = $state<ProjectDoc[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let scope = $state<'session' | 'all'>('session');

  let selected = $state<ProjectDoc | null>(null);
  let viewerOpen = $state(false);

  /* Tudo o que o agente produziu num lugar só. */
  const GROUPS = [
    { key: 'spec', title: 'Especificações', hint: 'O que o brainstorming decidiu construir.' },
    { key: 'plan', title: 'Planos de implementação', hint: 'Como o trabalho foi dividido.' },
    { key: 'backlog', title: 'Backlog decomposto', hint: 'O JSON que vira tarefas ao importar.' },
    { key: 'doc', title: 'Outros documentos', hint: 'Markdown avulso em docs/.' }
  ] as const;

  const grouped = $derived(
    GROUPS.map((g) => ({ ...g, items: docs.filter((d) => d.category === g.key) })).filter(
      (g) => g.items.length > 0
    )
  );

  async function load() {
    loading = true;
    error = null;
    try {
      if (scope === 'session' && activeSession) {
        docs = await api.listSessionArtifacts(data.project.id, activeSession.id);
      } else {
        docs = await api.listProjectDocs(data.project.id);
      }
    } catch (e) {
      error = e instanceof Error ? e.message : 'Falha ao listar os artefatos.';
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    // Re-executa quando o projeto, sessão ativa ou escopo mudam
    const _pId = data.project.id;
    const _sId = activeSession?.id;
    const _sc = scope;
    load();
  });

  function open(d: ProjectDoc) {
    selected = d;
    viewerOpen = true;
  }

  function when(iso: string) {
    const d = new Date(iso);
    return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
  }

  const repoUrl = $derived(data.project.repo_url?.replace(/\/$/, '') ?? null);
</script>

<div class="grid">
  <div class="main">
    <div class="head">
      <div class="spread">
        <div>
          <p class="help">
            Documentos e especificações gerados pelo ciclo iterativo de engenharia.
            Arquivos reais gravados diretamente no repositório.
          </p>
        </div>
        <div class="head-actions">
          {#if activeSession}
            <div class="seg-control" role="group" aria-label="Filtrar artefatos">
              <button
                type="button"
                class="seg-btn"
                class:active={scope === 'session'}
                onclick={() => (scope = 'session')}
              >
                Sessão {activeSession.number}
              </button>
              <button
                type="button"
                class="seg-btn"
                class:active={scope === 'all'}
                onclick={() => (scope = 'all')}
              >
                Todos
              </button>
            </div>
          {/if}
          <button type="button" class="btn btn-line btn-sm" onclick={load} disabled={loading}>
            <Icon name="upload" size={12} /> Recarregar
          </button>
        </div>
      </div>
    </div>

    {#if loading && !docs.length}
      <Skeleton variant="lines" rows={6} />
    {:else if error}
      <Placeholder kind="error" title="Não deu para listar" detail={error}>
        {#snippet action()}
          <button type="button" class="btn btn-solid" onclick={load}>Tentar de novo</button>
        {/snippet}
      </Placeholder>
    {:else if !docs.length}
      <Placeholder
        kind="empty"
        title={scope === 'session' && activeSession ? `Nenhum artefato vinculado à Sessão ${activeSession.number}` : 'Nenhum artefato ainda'}
        detail="Ao executar a análise da sessão, o agente grava a especificação em docs/superpowers/specs/ e o backlog em .painkiller/backlog.json."
      >
        {#snippet action()}
          <div class="empty-actions">
            {#if scope === 'session'}
              <button type="button" class="btn btn-line" onclick={() => (scope = 'all')}>
                Ver todos do projeto
              </button>
            {/if}
            <a class="btn btn-solid" href="/projetos/{data.project.id}/analise">
              <Icon name="play" size={11} /> Ir para a Análise
            </a>
          </div>
        {/snippet}
      </Placeholder>
    {:else}
      {#each grouped as group (group.key)}
        <section class="group">
          <div class="group-head">
            <h2 class="label">{group.title}</h2>
            <span class="mono faint">{group.items.length}</span>
          </div>
          <p class="help">{group.hint}</p>

          <ul class="docs divide">
            {#each group.items as d (d.path)}
              <li class="doc">
                <button type="button" class="open" onclick={() => open(d)}>
                  <div class="name-row">
                    <span class="name mono truncate" title={d.path}>{d.filename}</span>
                    {#if d.is_session_spec}
                      <span class="session-tag mono" title="Especificação desta sessão">Sessão {activeSession?.number}</span>
                    {/if}
                  </div>
                  <span class="path mono faint truncate">{d.path}</span>
                </button>
                <span class="mono faint size">{(d.size_bytes / 1024).toFixed(1)} KB</span>
                <span class="mono faint stamp">{when(d.modified_at)}</span>
                {#if repoUrl}
                  <a
                    class="ext"
                    href="{repoUrl}/src/branch/{data.project.default_branch}/{d.path}"
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Abrir no Gitea"
                    aria-label="Abrir {d.filename} no Gitea"
                  >
                    <Icon name="external" size={12} />
                  </a>
                {/if}
              </li>
            {/each}
          </ul>
        </section>
      {/each}
    {/if}
  </div>

  <aside>
    <div class="panel">
      <h2 class="label">Repositório</h2>
      <a
        class="btn btn-line btn-sm download"
        href="/api/projects/{data.project.id}/archive"
        download
        title="Arquivos versionados da branch {data.project.default_branch}, sem .git"
      >
        <Icon name="download" size={12} /> Baixar .zip
      </a>
      {#if repoUrl}
        <ul class="links">
          <li>
            <a href={repoUrl} target="_blank" rel="noopener noreferrer">
              <Icon name="external" size={11} /> Código no Gitea
            </a>
          </li>
          <li>
            <a
              href="{repoUrl}/src/branch/{data.project.default_branch}/docs"
              target="_blank"
              rel="noopener noreferrer"
            >
              <Icon name="external" size={11} /> Pasta docs/
            </a>
          </li>
          <li>
            <a href="{repoUrl}/branches" target="_blank" rel="noopener noreferrer">
              <Icon name="external" size={11} /> Branches feature/*
            </a>
          </li>
        </ul>
      {:else}
        <p class="help">
          Este projeto não tem repositório remoto registrado; os arquivos existem
          apenas no workspace local.
        </p>
      {/if}
      <p class="path mono">{data.project.repo_path}</p>
    </div>

    <div class="panel">
      <h2 class="label">Onde cada coisa nasce</h2>
      <dl class="legend">
        <div>
          <dt class="mono">docs/superpowers/specs/</dt>
          <dd class="help">Escrito pelo agente de análise ao fechar o brainstorming.</dd>
        </div>
        <div>
          <dt class="mono">.painkiller/backlog.json</dt>
          <dd class="help">Lido por “Importar backlog” e convertido em tarefas.</dd>
        </div>
        <div>
          <dt class="mono">.painkiller/clarification.json</dt>
          <dd class="help">Escrito por um agente de código que parou para perguntar.</dd>
        </div>
      </dl>
    </div>
  </aside>
</div>

<DocViewer
  bind:open={viewerOpen}
  doc={selected}
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

  .head {
    margin-bottom: var(--s6);
  }

  .head-actions {
    display: flex;
    align-items: center;
    gap: var(--s3);
  }

  .seg-control {
    display: inline-flex;
    border: 1px solid var(--rule-ink);
    border-radius: 0;
    overflow: hidden;
  }

  .seg-btn {
    background: transparent;
    border: none;
    border-right: 1px solid var(--rule-ink);
    padding: var(--s1) var(--s3);
    font-size: var(--t-micro);
    font-family: var(--font-mono, monospace);
    color: var(--ink-2);
    cursor: pointer;
    transition: background var(--fast) var(--ease), color var(--fast) var(--ease);
  }

  .seg-btn:last-child {
    border-right: none;
  }

  .seg-btn:hover {
    color: var(--ink);
    background: var(--paper-2);
  }

  .seg-btn.active {
    background: var(--ink);
    color: var(--paper);
    font-weight: 600;
  }

  .empty-actions {
    display: flex;
    align-items: center;
    gap: var(--s3);
    margin-top: var(--s3);
  }

  .name-row {
    display: flex;
    align-items: center;
    gap: var(--s2);
  }

  .session-tag {
    font-size: var(--t-micro);
    padding: 0.1rem 0.35rem;
    border: 1px solid var(--rule-ink);
    color: var(--ink);
    background: var(--paper-2);
    letter-spacing: 0.04em;
    white-space: nowrap;
  }

  .head .help {
    max-width: var(--measure);
  }

  .group + .group {
    margin-top: var(--s7);
  }

  .group-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--s3);
    border-bottom: 1px solid var(--rule-ink);
    padding-bottom: var(--s2);
  }

  .group .help {
    margin-top: var(--s2);
  }

  .docs {
    margin-top: var(--s3);
  }

  /* Uma linha por arquivo, sem card: nome, peso, data, saída para o Gitea. */
  .doc {
    display: grid;
    grid-template-columns: 1fr auto auto auto;
    align-items: center;
    gap: var(--s4);
    padding: var(--s3) 0;
  }

  .open {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
    text-align: left;
    background: transparent;
    border: 0;
    padding: 0;
    cursor: pointer;
  }

  .name {
    font-size: var(--t-small);
    color: var(--ink);
  }

  .open:hover .name {
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .path,
  .size,
  .stamp {
    font-size: var(--t-micro);
  }

  .ext {
    color: var(--ink-3);
    display: inline-flex;
    transition: color var(--fast) var(--ease);
  }

  .ext:hover {
    color: var(--ink);
  }

  aside {
    display: flex;
    flex-direction: column;
    gap: var(--s6);
    position: sticky;
    top: 4.5rem;
  }

  .panel {
    border-top: 1px solid var(--rule-ink);
    padding-top: var(--s3);
  }

  .download {
    margin-top: var(--s3);
  }

  .links {
    margin-top: var(--s3);
    display: flex;
    flex-direction: column;
    gap: var(--s2);
  }

  .links a {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    font-size: var(--t-small);
    color: var(--ink-2);
    transition: color var(--fast) var(--ease);
  }

  .links a:hover {
    color: var(--ink);
  }

  .panel .path {
    margin-top: var(--s4);
    color: var(--ink-3);
    word-break: break-all;
  }

  .legend {
    margin-top: var(--s3);
  }

  .legend div + div {
    margin-top: var(--s4);
  }

  .legend dt {
    font-size: var(--t-micro);
    color: var(--ink);
  }

  .legend dd {
    margin-top: var(--s1);
  }

  @media (max-width: 900px) {
    .grid {
      grid-template-columns: 1fr;
      gap: var(--s7);
    }

    aside {
      position: static;
    }

    .doc {
      grid-template-columns: 1fr auto;
      row-gap: var(--s2);
    }

    .stamp {
      display: none;
    }
  }
</style>
