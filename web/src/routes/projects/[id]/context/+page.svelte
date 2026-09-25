<script lang="ts">
  import ProjectContext from '$lib/components/ProjectContext.svelte';

  let { data } = $props();
</script>

<ProjectContext project={data.project} />
