<script module lang="ts">
  // Tela de um Android comum em dp; a moldura soma as bordas.
  export const SCREEN_W = 360;
  export const SCREEN_H = 760;
  /** Um Android grande (classe Pixel Pro / Galaxy Ultra), em dp. */
  export const LARGE_SCREEN_W = 412;
  export const LARGE_SCREEN_H = 915;
  export const BEZEL_X = 10;
  export const BEZEL_Y = 26;
  export const DEVICE_W = SCREEN_W + BEZEL_X * 2;
  export const DEVICE_H = SCREEN_H + BEZEL_Y * 2;
</script>

<script lang="ts">
  /**
   * Um smartphone simulado: a tela tem o tamanho de um Android de verdade
   * (360×760 dp) e o aparelho inteiro é reduzido por `scale` para caber, de
   * modo que o app vê sempre a mesma largura, como num celular.
   */
  import type { Snippet } from 'svelte';

  let {
    scale = 1,
    highlight = false,
    screenW = SCREEN_W,
    screenH = SCREEN_H,
    children
  }: {
    scale?: number;
    highlight?: boolean;
    screenW?: number;
    screenH?: number;
    children: Snippet;
  } = $props();

  const deviceW = $derived(screenW + BEZEL_X * 2);
  const deviceH = $derived(screenH + BEZEL_Y * 2);
</script>

<div class="slot" style="width: {deviceW * scale}px; height: {deviceH * scale}px">
  <div
    class="device"
    class:highlight
    style="width: {deviceW}px; height: {deviceH}px; padding: {BEZEL_Y}px {BEZEL_X}px; transform: scale({scale})"
  >
    <span class="speaker" aria-hidden="true"></span>
    <div class="screen" style="width: {screenW}px; height: {screenH}px">
      {@render children()}
    </div>
  </div>
</div>

<style>
  .slot {
    position: relative;
    flex: none;
  }

  /* O aparelho: bloco de tinta, sem raio, como o resto da interface. */
  .device {
    position: absolute;
    top: 0;
    left: 0;
    box-sizing: border-box;
    transform-origin: top left;
    background: var(--term-bg);
    border: 1px solid var(--rule-ink);
    transition: box-shadow var(--fast) var(--ease);
  }

  .device.highlight {
    box-shadow: 0 0 0 3px var(--rule-ink);
  }

  .speaker {
    position: absolute;
    top: 11px;
    left: 50%;
    width: 48px;
    height: 3px;
    transform: translateX(-50%);
    background: var(--term-rule);
  }

  .screen {
    position: relative;
    overflow: hidden;
    background: #ffffff;
  }

  .screen :global(iframe) {
    display: block;
    width: 100%;
    height: 100%;
    border: 0;
    background: #ffffff;
  }
</style>
