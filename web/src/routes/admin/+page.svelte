<script lang="ts">
  import { goto } from '$app/navigation';
  $effect(() => {
    goto('/admin/templates', { replaceState: true });
  });
</script>
