<script lang="ts">
  import { STATUS_META, type TaskStatus } from '$lib/types';

  let { status, size = 'md' }: { status: TaskStatus; size?: 'md' | 'sm' } = $props();

  const meta = $derived(STATUS_META[status]);
</script>

<!--
  O status é comunicado por peso, marcador e hachura — não por cor.
  A única exceção é AWAITING_ANALYST, o estado que exige você.
-->
<span
  class="tag"
  class:accent={meta.accent}
  class:done={meta.done}
  class:hatch={meta.hatch}
  class:sm={size === 'sm'}
  class:running={status === 'RUNNING'}
>
  <span class="mark" aria-hidden="true"></span>
  {meta.label}
</span>

<style>
  .tag {
    display: inline-flex;
    align-items: center;
    gap: 0.4375rem;
    padding: 0.1875rem 0.4375rem 0.1875rem 0.375rem;
    font-size: var(--t-label);
    font-weight: 500;
    letter-spacing: 0.075em;
    text-transform: uppercase;
    color: var(--ink-2);
    border: 1px solid var(--rule);
    white-space: nowrap;
  }

  .sm {
    padding: 0.125rem 0.375rem 0.125rem 0.3125rem;
  }

  .mark {
    width: 6px;
    height: 6px;
    border: 1px solid currentColor;
  }

  /* Aguardando analista — o único uso de cor da interface */
  .accent {
    color: var(--accent);
    border-color: var(--accent);
    background: var(--accent-sunk);
  }

  .accent .mark {
    background: currentColor;
  }

  .running {
    color: var(--ink);
    border-color: var(--rule-2);
  }

  .running .mark {
    background: currentColor;
    animation: blink 1.3s var(--ease) infinite;
  }

  .done {
    color: var(--ink-3);
  }

  .done .mark {
    background: var(--ink-4);
    border-color: var(--ink-4);
  }

  /* Falha: hachura diagonal em vez de vermelho, para não competir
     com o vermelhão reservado ao exit 42. */
  .hatch {
    color: var(--ink);
    border-color: var(--rule-2);
    background-image: repeating-linear-gradient(
      45deg,
      var(--rule) 0,
      var(--rule) 1px,
      transparent 1px,
      transparent 5px
    );
  }
</style>
