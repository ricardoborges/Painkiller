<script lang="ts">
  import { goto } from '$app/navigation';
  import Icon from '$lib/components/Icon.svelte';
  import ProjectForm from '$lib/components/ProjectForm.svelte';
</script>

<svelte:head><title>Novo projeto — Painkiller</title></svelte:head>

<header class="head">
  <a href="/projects" class="back label">
    <Icon name="arrow-left" size={11} /> Projetos
  </a>
  <h1 class="display">Novo projeto</h1>
  <p class="lede sub">
    Contexto, propósito e documentos que alimentam o agente de análise.
  </p>
</header>

<hr class="rule rule-ink" />

<div class="content">
  <ProjectForm onsaved={(p) => goto(`/projects/${p.id}`)} oncancel={() => goto('/projects')} />
</div>

<style>
  .head {
    padding-top: var(--s7);
  }

  .back {
    display: inline-flex;
    align-items: center;
    gap: var(--s2);
    margin-bottom: var(--s4);
    color: var(--ink-3);
    transition: color var(--fast) var(--ease);
  }

  .back:hover {
    color: var(--ink);
  }

  .sub {
    margin-top: var(--s3);
  }

  .rule {
    margin-top: var(--s5);
  }

  .content {
    padding-top: var(--s6);
  }
</style>
