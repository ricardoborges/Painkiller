<script lang="ts">
  import { goto, invalidateAll } from '$app/navigation';
  import ProjectForm from '$lib/components/ProjectForm.svelte';

  let { data } = $props();

  const back = $derived(`/projects/${data.project.id}`);

  async function onSaved() {
    await invalidateAll();
    await goto(back);
  }
</script>

<svelte:head><title>Editar {data.project.name} — Painkiller</title></svelte:head>

<h2 class="label heading">Editar projeto</h2>

<ProjectForm project={data.project} onsaved={onSaved} oncancel={() => goto(back)} />

<style>
  .heading {
    margin-bottom: var(--s5);
  }
</style>
