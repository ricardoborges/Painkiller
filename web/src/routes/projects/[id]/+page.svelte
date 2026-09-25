<script lang="ts">
  import ProjectContext from '$lib/components/ProjectContext.svelte';
  import ProjectDashboard from '$lib/components/ProjectDashboard.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import { getProjectSessionStore } from '$lib/stores/session.svelte';

  let { data } = $props();

  const sessionStore = $derived(getProjectSessionStore(data.project.id));
</script>

<!-- Projeto novo ou só com a primeira sessão em curso: o contexto leva direto à
     análise. Com uma sessão já encerrada há histórico, e a entrada vira o painel. -->
{#if !sessionStore.loaded}
  <div class="wait"><Skeleton rows={4} /></div>
{:else if sessionStore.hasCompleted}
  <ProjectDashboard project={data.project} />
{:else}
  <ProjectContext project={data.project} />
{/if}

<style>
  .wait {
    padding-top: var(--s6);
    max-width: var(--measure);
  }
</style>
