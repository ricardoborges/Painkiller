<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  let { data } = $props();

  onMount(() => {
    goto(`/projetos/${data.project.id}/backlog`, { replaceState: true });
  });
</script>

<div class="redirecting mono faint pad">
  Redirecionando para o Backlog…
</div>

<style>
  .pad {
    padding: var(--s6);
  }
</style>
