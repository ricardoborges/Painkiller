<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import { baseName } from '$lib/api';
  import Icon from '$lib/components/Icon.svelte';
  import ProjectDialog from '$lib/components/ProjectDialog.svelte';

  let { data } = $props();

  let dialogOpen = $state(false);

  const sections = $derived([
    { label: 'Descrição geral', text: data.project.description },
    { label: 'Propósito de negócio', text: data.project.purpose },
    { label: 'Solução desejada', text: data.project.solution_description }
  ]);
</script>

<!-- Grade assimétrica 2fr/1fr: a prosa carrega o peso, a coluna
     estreita guarda metadados e ações. -->
<div class="grid">
  <div class="prose">
    {#each sections as s, i (s.label)}
      <section class="block rise" style="--i: {i}">
        <h2 class="label">{s.label}</h2>
        {#if s.text}
          <p>{s.text}</p>
        {:else}
          <p class="faint">Não informado.</p>
        {/if}
      </section>
    {/each}
  </div>

  <aside>
    <div class="panel">
      <h2 class="label">Anexos de contexto</h2>
      {#if data.project.attachments.length}
        <ul class="files divide">
          {#each data.project.attachments as path (path)}
            <li class="file">
              <Icon name="clip" size={12} />
              <span class="truncate" title={baseName(path)}>{baseName(path)}</span>
            </li>
          {/each}
        </ul>
        <p class="help">
          Extraídos como texto e concatenados ao prompt inicial da análise.
        </p>
      {:else}
        <p class="faint none">
          Nenhum documento anexado. O agente vai trabalhar só com os três campos ao lado.
        </p>
      {/if}
    </div>

    <div class="panel">
      <h2 class="label">Repositório</h2>
      <p class="mono path">{data.project.repo_path}</p>
      <p class="help">Montado em <span class="mono">/workspace</span> dentro do contêiner.</p>
    </div>

    <div class="acts">
      <a class="btn btn-solid" href="/projetos/{data.project.id}/analise-inicial">
        <Icon name="play" size={11} /> Iniciar análise
      </a>
      <button type="button" class="btn btn-line" onclick={() => (dialogOpen = true)}>
        <Icon name="pencil" size={11} /> Editar
      </button>
    </div>
  </aside>
</div>

<ProjectDialog bind:open={dialogOpen} project={data.project} onsaved={() => invalidateAll()} />

<style>
  .grid {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: var(--s9);
    padding-top: var(--s6);
    align-items: start;
  }

  .prose {
    max-width: var(--measure);
  }

  .block + .block {
    margin-top: var(--s6);
    border-top: 1px solid var(--rule);
    padding-top: var(--s5);
  }

  .block p {
    margin-top: var(--s3);
    white-space: pre-wrap;
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

  .files {
    margin-top: var(--s2);
  }

  .file {
    display: flex;
    align-items: center;
    gap: var(--s2);
    padding: var(--s2) 0;
    font-size: var(--t-small);
    color: var(--ink-2);
    min-width: 0;
  }

  .none {
    margin-top: var(--s3);
    font-size: var(--t-small);
  }

  .help {
    margin-top: var(--s3);
  }

  .path {
    margin-top: var(--s3);
    font-size: var(--t-micro);
    color: var(--ink-2);
    word-break: break-all;
  }

  .acts {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s2);
  }

  @media (max-width: 900px) {
    .grid {
      grid-template-columns: 1fr;
      gap: var(--s7);
    }

    aside {
      position: static;
    }
  }
</style>
