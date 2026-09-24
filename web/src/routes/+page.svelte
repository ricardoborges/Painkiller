<script lang="ts">
  import { goto } from '$app/navigation';

  $effect(() => {
    goto('/projects', { replaceState: true });
  });
</script>
