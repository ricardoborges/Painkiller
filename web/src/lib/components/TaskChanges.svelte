<script lang="ts">
  /**
   * Arquivos que a branch da tarefa mudou, lidos do repositório no host.
   *
   * No card fica só uma linha; o conteúdo abre num modal com a árvore de
   * pastas e o diff do arquivo escolhido. Enquanto o agente roda, o servidor
   * compara a árvore de trabalho com o ponto em que a branch saiu da principal
   * (entra o que ainda não foi commitado); depois do merge, usa o commit de
   * merge, então o diff segue legível mesmo com a branch apagada. Só busca
   * com o modal aberto, e só repete enquanto a tarefa roda.
   */
  import { api } from '$lib/api';
  import { t, tp, formatNumber } from '$lib/i18n/index.svelte';
  import type { BranchChanges, FileChange } from '$lib/types';
  import Icon from './Icon.svelte';
  import Modal from './Modal.svelte';
  import Skeleton from './Skeleton.svelte';

  let { taskId, title = '', live = false }: { taskId: string; title?: string; live?: boolean } = $props();

  const POLL_S = 5;

  let open = $state(false);
  let data = $state<BranchChanges | null>(null);
  let failed = $state(false);
  let selected = $state<string | null>(null);
  let collapsed = $state<Record<string, boolean>>({});
  let loading = false;

  async function load() {
    if (loading) return;
    loading = true;
    try {
      data = await api.getTaskChanges(taskId);
      failed = false;
      // Primeiro arquivo por padrão; mantém a escolha enquanto ele existir.
      if (!selected || !data.files.some((f) => f.path === selected)) {
        selected = data.files[0]?.path ?? null;
      }
    } catch {
      failed = true;
    } finally {
      loading = false;
    }
  }

  // Reabre quando `live` cai: a última leitura pega o estado final da branch.
  $effect(() => {
    if (!open) return;
    void taskId;
    load();
    if (!live) return;
    const timer = setInterval(load, POLL_S * 1000);
    return () => clearInterval(timer);
  });

  const totals = $derived(
    (data?.files ?? []).reduce(
      (acc, f) => ({ add: acc.add + f.additions, del: acc.del + f.deletions }),
      { add: 0, del: 0 }
    )
  );

  const current = $derived(data?.files.find((f) => f.path === selected) ?? null);

  const STATUS_LABEL: Record<FileChange['status'], () => string> = {
    A: () => t('changes.status.A'),
    M: () => t('changes.status.M'),
    D: () => t('changes.status.D')
  };

  // ── Árvore ─────────────────────────────────────────────────────────────
  type Dir = { name: string; path: string; dirs: Dir[]; files: FileChange[] };

  function buildTree(files: FileChange[]): Dir {
    const root: Dir = { name: '', path: '', dirs: [], files: [] };
    for (const f of files) {
      const parts = f.path.split('/');
      let node = root;
      for (const part of parts.slice(0, -1)) {
        const path = node.path ? `${node.path}/${part}` : part;
        let next = node.dirs.find((d) => d.name === part);
        if (!next) {
          next = { name: part, path, dirs: [], files: [] };
          node.dirs.push(next);
        }
        node = next;
      }
      node.files.push(f);
    }
    // Pastas com uma só subpasta e nenhum arquivo viram uma linha ("src/app").
    function squash(d: Dir): Dir {
      d.dirs = d.dirs.map(squash);
      if (d.path && d.dirs.length === 1 && d.files.length === 0) {
        const only = d.dirs[0];
        return { ...only, name: `${d.name}/${only.name}` };
      }
      return d;
    }
    const tree = squash(root);
    const sort = (d: Dir) => {
      d.dirs.sort((a, b) => a.name.localeCompare(b.name));
      d.files.sort((a, b) => a.path.localeCompare(b.path));
      d.dirs.forEach(sort);
    };
    sort(tree);
    return tree;
  }

  const tree = $derived(buildTree(data?.files ?? []));

  function baseName(path: string): string {
    return path.slice(path.lastIndexOf('/') + 1);
  }

  // ── Diff com números de linha ──────────────────────────────────────────
  type Row = { kind: 'hunk' | 'add' | 'del' | 'ctx' | 'meta'; text: string; old: number | null; new: number | null };

  function rows(patch: string): Row[] {
    const out: Row[] = [];
    let o = 0;
    let n = 0;
    const lines = patch.split('\n');
    if (lines[lines.length - 1] === '') lines.pop();
    for (const line of lines) {
      const h = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (h) {
        o = Number(h[1]);
        n = Number(h[2]);
        out.push({ kind: 'hunk', text: line, old: null, new: null });
      } else if (line.startsWith('+')) {
        out.push({ kind: 'add', text: line.slice(1), old: null, new: n++ });
      } else if (line.startsWith('-')) {
        out.push({ kind: 'del', text: line.slice(1), old: o++, new: null });
      } else if (line.startsWith('\\')) {
        out.push({ kind: 'meta', text: line, old: null, new: null });
      } else {
        out.push({ kind: 'ctx', text: line.slice(1), old: o++, new: n++ });
      }
    }
    return out;
  }

  const MARK: Record<Row['kind'], string> = { add: '+', del: '−', ctx: ' ', hunk: '', meta: '' };
</script>

<section class="changes">
  <button type="button" class="head" onclick={() => (open = true)}>
    <Icon name="file-text" size={12} />
    <span class="label">{t('changes.title')}</span>
    {#if data?.available && data.files.length}
      <span class="mono count">
        {formatNumber(data.files.length + data.omitted)}
        <span class="sep">·</span>
        <span class="plus">+{formatNumber(totals.add)}</span> <span class="minus">−{formatNumber(totals.del)}</span>
      </span>
    {/if}
    <span class="open-hint label">{t('changes.view')} <Icon name="arrow-right" size={10} /></span>
  </button>
</section>

<Modal bind:open title={title ? `${t('changes.modalTitle')} · ${title}` : t('changes.modalTitle')} width="84rem">
  {#snippet body()}
    {#if !data && !failed}
      <Skeleton variant="lines" rows={6} />
    {:else if !data}
      <p class="note">{t('changes.failed')}</p>
    {:else}
      <div class="summary">
        <span class="mono">{data.branch} → {data.base_branch}</span>
        {#if data.merged}
          <span class="sep">·</span>
          <span class="bold">{t('changes.merged', { base: data.base_branch })}</span>
        {:else if live && data.live}
          <span class="sep">·</span>
          <span class="mono faint">{t('changes.live', { seconds: POLL_S })}</span>
        {/if}
        {#if data.available && data.files.length}
          <span class="sep">·</span>
          <span class="mono tabular">
            {tp('changes.fileCount', data.files.length + data.omitted)} · <span class="plus">+{formatNumber(totals.add)}</span> <span class="minus">−{formatNumber(totals.del)}</span>
          </span>
        {/if}
        {#if data.web_url}
          <a
            class="gitea"
            href={data.web_url}
            target="_blank"
            rel="noopener noreferrer"
            title={data.merged ? undefined : t('changes.giteaTitle')}
          >
            {t('changes.openInGitea')} <Icon name="external" size={10} />
          </a>
        {/if}
      </div>

      {#if !data.available}
        <p class="note">{t('changes.unavailable')}</p>
      {:else if !data.files.length}
        <p class="note">{t('changes.empty')}</p>
      {:else}
        <div class="viewer">
          <nav class="tree" aria-label={t('changes.title')}>
            {@render dir(tree, 0)}
            {#if data.omitted}
              <p class="note mono">{tp('changes.omitted', data.omitted)}</p>
            {/if}
          </nav>

          <div class="diff">
            {#if current}
              <div class="diff-head">
                <span class="st mono" class:new={current.status === 'A'} class:gone={current.status === 'D'}>
                  {STATUS_LABEL[current.status]()}
                </span>
                <span class="mono path">{current.path}</span>
                <span class="mono num">
                  {#if current.binary}bin{:else}<span class="plus">+{current.additions}</span> <span class="minus">−{current.deletions}</span>{/if}
                </span>
              </div>
              {#if current.binary}
                <p class="note">{t('changes.binary')}</p>
              {:else if current.patch}
                <table class="patch mono">
                  <tbody>
                    {#each rows(current.patch) as r, i (i)}
                      <tr class={r.kind}>
                        {#if r.kind === 'hunk' || r.kind === 'meta'}
                          <td class="ln" colspan="3"></td>
                          <td class="code">{r.text}</td>
                        {:else}
                          <td class="ln">{r.old ?? ''}</td>
                          <td class="ln">{r.new ?? ''}</td>
                          <td class="mk">{MARK[r.kind]}</td>
                          <td class="code">{r.text || ' '}</td>
                        {/if}
                      </tr>
                    {/each}
                  </tbody>
                </table>
                {#if current.truncated}<p class="note">{t('changes.truncated')}</p>{/if}
              {:else if current.truncated}
                <p class="note">{t('changes.tooLarge')}</p>
              {/if}
            {:else}
              <p class="note">{t('changes.pick')}</p>
            {/if}
          </div>
        </div>
      {/if}
    {/if}
  {/snippet}
</Modal>

{#snippet dir(d: Dir, depth: number)}
  <ul class="level" style="--depth: {depth}">
    {#each d.dirs as sub (sub.path)}
      <li>
        <button
          type="button"
          class="node folder"
          aria-expanded={!collapsed[sub.path]}
          onclick={() => (collapsed[sub.path] = !collapsed[sub.path])}
        >
          <span class="chev" class:shut={collapsed[sub.path]} aria-hidden="true"><Icon name="chevron-down" size={10} /></span>
          <span class="mono name">{sub.name}/</span>
        </button>
        {#if !collapsed[sub.path]}
          {@render dir(sub, depth + 1)}
        {/if}
      </li>
    {/each}
    {#each d.files as f (f.path)}
      <li>
        <button
          type="button"
          class="node file"
          class:on={selected === f.path}
          aria-current={selected === f.path ? 'true' : undefined}
          title={`${STATUS_LABEL[f.status]()} · ${f.path}`}
          onclick={() => (selected = f.path)}
        >
          <span class="st mono" class:new={f.status === 'A'} class:gone={f.status === 'D'}>{f.status}</span>
          <span class="mono name" class:gone={f.status === 'D'}>{baseName(f.path)}</span>
          <span class="mono num">{#if f.binary}bin{:else}<span class="plus">+{f.additions}</span> <span class="minus">−{f.deletions}</span>{/if}</span>
        </button>
      </li>
    {/each}
  </ul>
{/snippet}

<style>
  .changes {
    margin-top: var(--s3);
    max-width: var(--task-col, 44rem);
    border-top: 1px solid var(--rule);
    font-size: var(--t-small);
  }

  .head {
    display: flex;
    align-items: center;
    gap: var(--s2);
    width: 100%;
    padding: var(--s2) 0;
    background: none;
    border: 0;
    color: var(--ink);
    cursor: pointer;
    text-align: left;
  }

  .head:hover .open-hint {
    color: var(--ink);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .count {
    font-size: var(--t-micro);
    color: var(--ink-2);
    font-variant-numeric: tabular-nums;
  }

  .open-hint {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    margin-left: auto;
    color: var(--ink-2);
  }

  .sep {
    color: var(--ink-4);
  }

  .note {
    margin: var(--s2) 0;
    font-size: var(--t-micro);
    color: var(--ink-3);
  }

  .summary {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--s2);
    padding-bottom: var(--s3);
    font-size: var(--t-small);
    color: var(--ink-2);
  }

  .gitea {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    margin-left: auto;
    color: var(--ink);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  /* Duas colunas com rolagem própria: a árvore não some ao descer no diff. */
  .viewer {
    display: grid;
    grid-template-columns: minmax(14rem, 18rem) 1fr;
    height: min(64vh, 40rem);
    border: 1px solid var(--rule-2);
  }

  .tree {
    overflow: auto;
    border-right: 1px solid var(--rule-2);
    padding: var(--s2) 0;
    font-size: var(--t-micro);
  }

  .level {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .node {
    display: flex;
    align-items: center;
    gap: var(--s2);
    width: 100%;
    min-width: 0;
    padding: 0.2rem var(--s3) 0.2rem calc(var(--s3) + var(--depth) * 0.9rem);
    background: none;
    border: 0;
    color: var(--ink);
    cursor: pointer;
    text-align: left;
  }

  .node:hover {
    background: var(--paper-sunk);
  }

  .node.on {
    background: var(--paper-sunk);
    box-shadow: inset 2px 0 0 var(--ink);
    font-weight: 600;
  }

  .folder .name {
    color: var(--ink-2);
  }

  .chev {
    display: inline-flex;
    color: var(--ink-3);
    transition: transform var(--fast) var(--ease);
  }

  .chev.shut {
    transform: rotate(-90deg);
  }

  .name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .name.gone {
    text-decoration: line-through;
    color: var(--ink-3);
  }

  .st {
    flex: none;
    min-width: 1ch;
    color: var(--ink-3);
  }

  .st.new {
    color: var(--ink);
    font-weight: 600;
  }

  .st.gone {
    text-decoration: line-through;
  }

  .num {
    flex: none;
    color: var(--ink-3);
    font-variant-numeric: tabular-nums;
  }

  .diff {
    overflow: auto;
    min-width: 0;
  }

  .diff-head {
    position: sticky;
    top: 0;
    z-index: 1;
    display: flex;
    align-items: baseline;
    gap: var(--s3);
    padding: var(--s2) var(--s3);
    background: var(--paper);
    border-bottom: 1px solid var(--rule-2);
    font-size: var(--t-micro);
  }

  .diff-head .path {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
    color: var(--ink);
  }

  .diff .note {
    padding: 0 var(--s3);
  }

  .patch {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--t-micro);
    line-height: 1.5;
  }

  .patch td {
    padding: 0;
    vertical-align: top;
  }

  .ln {
    width: 1%;
    padding: 0 var(--s2) !important;
    text-align: right;
    color: var(--ink-4);
    user-select: none;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
    border-right: 1px solid var(--rule);
  }

  .mk {
    width: 1%;
    padding: 0 var(--s1) 0 var(--s2) !important;
    color: var(--ink-3);
    user-select: none;
  }

  .code {
    white-space: pre;
    padding-right: var(--s3) !important;
  }

  /* Exceção à regra de cor única, como nos toasts de resultado: verde e
     vermelho pálidos para linhas acrescentadas e removidas, longe do
     vermelhão de --accent, que segue reservado para o exit 42. */
  .changes,
  .summary,
  .viewer {
    --diff-add-bg: #e9f7ec;
    --diff-add-gutter: #d3eedb;
    --diff-add-ink: #1f6b35;
    --diff-del-bg: #fcecec;
    --diff-del-gutter: #f6d7d7;
    --diff-del-ink: #9b2f2f;
  }

  :global(:root[data-theme='dark']) .changes,
  :global(:root[data-theme='dark']) .summary,
  :global(:root[data-theme='dark']) .viewer {
    --diff-add-bg: #15261a;
    --diff-add-gutter: #1c3323;
    --diff-add-ink: #8fd0a0;
    --diff-del-bg: #2a1818;
    --diff-del-gutter: #3a2020;
    --diff-del-ink: #e6a3a3;
  }

  .plus {
    color: var(--diff-add-ink);
  }

  .minus {
    color: var(--diff-del-ink);
  }

  .add td {
    background: var(--diff-add-bg);
  }

  .add .ln {
    background: var(--diff-add-gutter);
  }

  .add .mk,
  .add .code {
    color: var(--diff-add-ink);
  }

  .del td {
    background: var(--diff-del-bg);
  }

  .del .ln {
    background: var(--diff-del-gutter);
  }

  .del .mk,
  .del .code {
    color: var(--diff-del-ink);
  }

  .ctx .code {
    color: var(--ink-2);
  }

  .hunk td,
  .meta td {
    color: var(--ink-3);
    background: var(--paper-2);
    padding-block: 0.15rem !important;
  }

  .hunk:not(:first-child) td {
    border-top: 1px solid var(--rule);
  }

  @media (max-width: 760px) {
    .viewer {
      grid-template-columns: 1fr;
      grid-template-rows: 12rem 1fr;
      height: 72vh;
    }

    .tree {
      border-right: 0;
      border-bottom: 1px solid var(--rule-2);
    }
  }
</style>
