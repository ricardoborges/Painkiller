<script lang="ts">
  /**
   * Primitivas SVG desenhadas à mão. Traço único de 1.5, terminais retos —
   * coerente com os filetes de 1px do layout. Nenhum emoji na interface.
   */
  type Name =
    | 'plus'
    | 'arrow-right'
    | 'arrow-left'
    | 'pencil'
    | 'trash'
    | 'clip'
    | 'check'
    | 'alert'
    | 'play'
    | 'close'
    | 'send'
    | 'upload'
    | 'external'
    | 'file-text'
    | 'copy'
    | 'info'
    | 'sidebar'
    | 'download';

  let { name, size = 14 }: { name: Name; size?: number } = $props();
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 16 16"
  fill="none"
  stroke="currentColor"
  stroke-width="1.5"
  stroke-linecap="square"
  stroke-linejoin="miter"
  aria-hidden="true"
>
  {#if name === 'plus'}
    <path d="M8 2.5v11M2.5 8h11" />
  {:else if name === 'arrow-right'}
    <path d="M2.5 8h11M9 3.5 13.5 8 9 12.5" />
  {:else if name === 'arrow-left'}
    <path d="M13.5 8h-11M7 3.5 2.5 8 7 12.5" />
  {:else if name === 'pencil'}
    <path d="M10.5 2.5 13.5 5.5 5.5 13.5H2.5v-3z" />
  {:else if name === 'trash'}
    <path d="M2.5 4h11M6 4V2.5h4V4M4 4v9.5h8V4M6.5 6.5v4.5M9.5 6.5v4.5" />
  {:else if name === 'clip'}
    <path d="M12.5 7.5 7.75 12.25a3 3 0 0 1-4.24-4.24l5.3-5.3a2 2 0 0 1 2.83 2.83l-5.3 5.3a1 1 0 0 1-1.42-1.42L9.5 5" />
  {:else if name === 'check'}
    <path d="M3 8.5 6.5 12 13 4" />
  {:else if name === 'alert'}
    <path d="M8 2.5 15 14H1zM8 6.5v3.5M8 11.75v.5" />
  {:else if name === 'play'}
    <path d="M4 2.5 13 8l-9 5.5z" />
  {:else if name === 'close'}
    <path d="m3.5 3.5 9 9M12.5 3.5l-9 9" />
  {:else if name === 'send'}
    <path d="M2 8h11M9 4l4 4-4 4" />
  {:else if name === 'upload'}
    <path d="M8 11V2.5M4.5 6 8 2.5 11.5 6M2.5 13.5h11" />
  {:else if name === 'external'}
    <path d="M7 3.5H3.5v9h9V9M9.5 3.5h3v3M7.5 8.5l5-5" />
  {:else if name === 'file-text'}
    <path d="M3 1.5h6.5l4 4V14.5H3z" />
    <path d="M9.5 1.5v4h4M5.5 8.5h5M5.5 11.5h5" />
  {:else if name === 'copy'}
    <rect x="5.5" y="5.5" width="8" height="8" />
    <path d="M3.5 10.5h-1.5V2.5h8v1.5" />
  {:else if name === 'info'}
    <circle cx="8" cy="8" r="6" />
    <path d="M8 7.5v4M8 5.25v.5" />
  {:else if name === 'sidebar'}
    <rect x="2" y="2.5" width="12" height="11" />
    <path d="M6 2.5v11" />
  {:else if name === 'download'}
    <path d="M8 2.5V11M4.5 7.5 8 11l3.5-3.5M2.5 13.5h11" />
  {/if}
</svg>
