<script lang="ts">
  /**
   * Cronômetro desde a montagem. O dispatch e a resposta de esclarecimento
   * seguram a requisição HTTP durante toda a execução do contêiner, então o
   * tempo decorrido é o único sinal honesto de progresso que temos.
   */
  let { from = Date.now() }: { from?: number } = $props();

  let now = $state(Date.now());

  $effect(() => {
    const id = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(id);
  });

  const text = $derived.by(() => {
    const total = Math.max(0, Math.floor((now - from) / 1000));
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  });
</script>

<span class="mono">{text}</span>

<style>
  span {
    font-variant-numeric: tabular-nums;
  }
</style>
