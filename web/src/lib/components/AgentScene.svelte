<script lang="ts" module>
  let seq = 0;

  export type SceneMode = 'thinking' | 'bash' | 'edit' | 'read' | 'skill' | 'sleep';

  /** O que o nome da ferramenta sugere que o agente está fazendo. */
  export function sceneForTool(name: string): SceneMode {
    const n = name.toLowerCase();
    if (/skill/.test(n)) return 'skill';
    if (/bash|shell|command|exec|run|terminal/.test(n)) return 'bash';
    if (/edit|write|create|patch|replace|apply|multiedit|str_replace/.test(n)) return 'edit';
    if (/read|view|grep|glob|search|find|list|ls|fetch|open/.test(n)) return 'read';
    return 'edit';
  }
</script>

<script lang="ts">
  /**
   * Uma cena pequena para a espera: um robô na mesa que imita o que o agente
   * está fazendo de verdade (terminal, código, leitura, skill, pensando) e
   * cochila quando o stream fica em silêncio. Só tinta sobre papel, como o
   * resto da interface; sem animação para quem pede movimento reduzido.
   */
  let { mode }: { mode: SceneMode } = $props();

  // Duas tarefas rodando = duas cenas: o recorte da tela precisa de id próprio.
  const clip = `scene-screen-${++seq}`;
</script>

<svg class="scene {mode}" viewBox="0 0 240 112" role="img" aria-hidden="true">
  <!-- Mesa -->
  <line class="ink-line" x1="8" y1="100" x2="232" y2="100" />

  <!-- Caneca, com vapor -->
  <g class="mug">
    <rect class="paper" x="210" y="86" width="13" height="14" />
    <path class="ink-line" d="M223 90 h3 v6 h-3" fill="none" />
    <path class="steam s1" d="M214 82 q-3 -4 0 -8 q3 -4 0 -8" />
    <path class="steam s2" d="M219 82 q-3 -4 0 -8 q3 -4 0 -8" />
  </g>

  <!-- Monitor -->
  <rect class="paper" x="118" y="22" width="92" height="62" />
  <rect class="screen" x="123" y="27" width="82" height="52" />
  <rect class="ink" x="160" y="84" width="8" height="10" />
  <line class="ink-line" x1="148" y1="94" x2="180" y2="94" />

  <clipPath id={clip}>
    <rect x="123" y="27" width="82" height="52" />
  </clipPath>

  <g clip-path="url(#{clip})">
    {#if mode === 'bash'}
      <g class="scroll">
        {#each [0, 1, 2, 3, 4, 5, 6, 7] as i (i)}
          <rect class="ink" x="128" y={33 + i * 9} width="4" height="3" />
          <rect class="faint" x="135" y={33 + i * 9} width={[40, 28, 52, 22, 46, 34, 50, 26][i]} height="3" />
        {/each}
      </g>
      <rect class="ink cursor" x="128" y="70" width="5" height="4" />
    {:else if mode === 'edit'}
      {#each [0, 1, 2, 3, 4] as i (i)}
        <rect
          class="ink type"
          style="--d: {i * 0.45}s"
          x={128 + (i % 2) * 6}
          y={33 + i * 9}
          width={[54, 40, 58, 30, 46][i]}
          height="3"
        />
      {/each}
    {:else if mode === 'read'}
      {#each [0, 1, 2, 3, 4] as i (i)}
        <rect class="faint" x="128" y={33 + i * 9} width={[60, 44, 66, 38, 52][i]} height="3" />
      {/each}
      <g class="lens">
        <circle class="lens-glass" cx="140" cy="46" r="9" />
        <line class="ink-line thick" x1="146.5" y1="52.5" x2="153" y2="59" />
      </g>
    {:else if mode === 'skill'}
      <g transform="translate(164 53)">
        <rect class="paper" x="-26" y="-16" width="26" height="32" />
        <rect class="paper" x="0" y="-16" width="26" height="32" />
        {#each [0, 1, 2] as i (i)}
          <rect class="faint" x="-21" y={-9 + i * 7} width="16" height="2" />
        {/each}
        <rect class="paper page" x="0" y="-16" width="26" height="32" />
      </g>
    {:else}
      {#each [0, 1, 2, 3] as i (i)}
        <rect class="faint" x="128" y={33 + i * 9} width={[50, 36, 58, 28][i]} height="3" />
      {/each}
    {/if}
  </g>

  <!-- Teclado -->
  <rect class="ink" x="92" y="96" width="40" height="4" />

  <!-- Robô -->
  <g class="bot">
    <!-- antena -->
    <line class="ink-line" x1="60" y1="28" x2="60" y2="19" />
    <circle class="bulb" cx="60" cy="17" r="3" />
    <!-- cabeça -->
    <rect class="paper" x="42" y="28" width="38" height="28" />
    <g class="eyes">
      {#if mode === 'sleep'}
        <line class="ink-line thick" x1="56" y1="42" x2="62" y2="42" />
        <line class="ink-line thick" x1="68" y1="42" x2="74" y2="42" />
      {:else}
        <rect class="ink" x="57" y="37" width="5" height="7" />
        <rect class="ink" x="69" y="37" width="5" height="7" />
      {/if}
    </g>
    <line class="ink-line" x1="60" y1="50" x2="70" y2="50" />
    <!-- corpo -->
    <rect class="paper" x="46" y="58" width="30" height="34" />
    <rect class="ink" x="54" y="66" width="14" height="3" />
    <rect class="faint" x="54" y="73" width="10" height="3" />
    <!-- braços -->
    <line class="ink-line thick arm a1" x1="76" y1="68" x2="98" y2="93" />
    <line class="ink-line thick arm a2" x1="76" y1="74" x2="112" y2="94" />
    <!-- banco -->
    <rect class="ink" x="44" y="92" width="34" height="3" />
    <line class="ink-line" x1="50" y1="95" x2="50" y2="100" />
    <line class="ink-line" x1="72" y1="95" x2="72" y2="100" />
  </g>

  {#if mode === 'thinking'}
    <g class="bubble">
      <circle class="paper" cx="88" cy="22" r="2.5" />
      <circle class="paper" cx="96" cy="14" r="3.5" />
      <rect class="paper" x="98" y="0" width="34" height="13" />
      <circle class="ink dot d1" cx="107" cy="6.5" r="1.8" />
      <circle class="ink dot d2" cx="115" cy="6.5" r="1.8" />
      <circle class="ink dot d3" cx="123" cy="6.5" r="1.8" />
    </g>
  {:else if mode === 'sleep'}
    <g class="zzz">
      <text class="z z1" x="84" y="28">z</text>
      <text class="z z2" x="92" y="20">z</text>
      <text class="z z3" x="101" y="11">Z</text>
    </g>
  {/if}
</svg>

<style>
  .scene {
    width: 100%;
    height: auto;
    display: block;
    overflow: visible;
  }

  .ink {
    fill: var(--ink);
  }

  .faint {
    fill: var(--ink-4);
  }

  .paper {
    fill: var(--paper);
    stroke: var(--ink);
    stroke-width: 1.4;
  }

  .screen {
    fill: var(--paper-sunk);
    stroke: var(--rule-2);
  }

  .ink-line {
    stroke: var(--ink);
    stroke-width: 1.4;
    stroke-linecap: square;
    fill: none;
  }

  .ink-line.thick {
    stroke-width: 2.4;
  }

  .bulb {
    fill: var(--ink);
    animation: blink 1.4s steps(2, jump-none) infinite;
  }

  .steam {
    fill: none;
    stroke: var(--ink-3);
    stroke-width: 1.2;
    opacity: 0;
    animation: steam 3s ease-in-out infinite;
  }

  .s2 {
    animation-delay: 1.5s;
  }

  /* Olhos piscam de vez em quando. */
  .eyes {
    transform-box: fill-box;
    transform-origin: center;
    animation: wink 4.5s infinite;
  }

  /* Digitação: os braços batem alternados no teclado. */
  .arm {
    transform-box: view-box;
    transform-origin: 76px 70px;
  }

  .edit .a1,
  .bash .a1 {
    animation: tap 0.32s ease-in-out infinite alternate;
  }

  .edit .a2,
  .bash .a2 {
    animation: tap 0.32s ease-in-out infinite alternate-reverse;
  }

  /* Pensando ou lendo: a cabeça balança devagar. */
  .thinking .bot,
  .read .bot,
  .skill .bot {
    transform-box: view-box;
    transform-origin: 60px 100px;
    animation: sway 3.2s ease-in-out infinite;
  }

  .sleep .bot {
    transform-box: view-box;
    transform-origin: 60px 100px;
    animation: breathe 3.6s ease-in-out infinite;
  }

  .sleep .bulb,
  .sleep .eyes {
    animation: none;
  }

  .sleep .bulb {
    fill: var(--ink-4);
  }

  .scroll {
    animation: scroll 2.6s linear infinite;
  }

  .cursor {
    animation: blink 0.9s steps(2, jump-none) infinite;
  }

  .type {
    transform-box: fill-box;
    transform-origin: left center;
    transform: scaleX(0);
    animation: type 2.8s var(--d) ease-out infinite;
  }

  .lens {
    animation: scan 3.4s ease-in-out infinite;
  }

  .lens-glass {
    fill: color-mix(in srgb, var(--paper) 55%, transparent);
    stroke: var(--ink);
    stroke-width: 1.8;
  }

  .page {
    transform-box: fill-box;
    transform-origin: left center;
    animation: flip 1.8s ease-in-out infinite;
  }

  .dot {
    animation: pulse 1.2s ease-in-out infinite;
  }

  .d2 {
    animation-delay: 0.2s;
  }

  .d3 {
    animation-delay: 0.4s;
  }

  .z {
    fill: var(--ink-3);
    font-family: var(--font-mono);
    font-size: 9px;
    font-weight: 600;
    opacity: 0;
    animation: float 3s ease-in-out infinite;
  }

  .z2 {
    animation-delay: 1s;
  }

  .z3 {
    animation-delay: 2s;
  }

  @keyframes blink {
    50% {
      opacity: 0.15;
    }
  }

  @keyframes wink {
    0%,
    92%,
    100% {
      transform: scaleY(1);
    }
    95% {
      transform: scaleY(0.1);
    }
  }

  @keyframes tap {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(-5deg);
    }
  }

  @keyframes sway {
    0%,
    100% {
      transform: rotate(0deg);
    }
    50% {
      transform: rotate(-2.5deg);
    }
  }

  @keyframes breathe {
    0%,
    100% {
      transform: scaleY(1);
    }
    50% {
      transform: scaleY(0.97);
    }
  }

  @keyframes steam {
    0% {
      opacity: 0;
      transform: translateY(4px);
    }
    40% {
      opacity: 0.8;
    }
    100% {
      opacity: 0;
      transform: translateY(-8px);
    }
  }

  @keyframes scroll {
    from {
      transform: translateY(0);
    }
    to {
      transform: translateY(-36px);
    }
  }

  @keyframes type {
    0% {
      transform: scaleX(0);
    }
    35%,
    85% {
      transform: scaleX(1);
    }
    100% {
      transform: scaleX(1);
      opacity: 0;
    }
  }

  @keyframes scan {
    0%,
    100% {
      transform: translate(0, 0);
    }
    30% {
      transform: translate(36px, 0);
    }
    55% {
      transform: translate(36px, 18px);
    }
    80% {
      transform: translate(4px, 18px);
    }
  }

  @keyframes flip {
    0%,
    20% {
      transform: scaleX(1);
    }
    60%,
    100% {
      transform: scaleX(-1);
    }
  }

  @keyframes pulse {
    0%,
    100% {
      opacity: 0.2;
    }
    50% {
      opacity: 1;
    }
  }

  @keyframes float {
    0% {
      opacity: 0;
      transform: translate(0, 4px);
    }
    30% {
      opacity: 1;
    }
    100% {
      opacity: 0;
      transform: translate(6px, -8px);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .scene :global(*) {
      animation: none !important;
    }

    .type {
      transform: none;
    }
  }
</style>
