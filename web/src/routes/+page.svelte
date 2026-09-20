<script lang="ts">
  import { goto } from '$app/navigation';

  $effect(() => {
    goto('/projetos', { replaceState: true });
  });
</script>
