<script lang="ts">
  import { composeAnswer, pickedFrom, OTHER_LABEL, type Choices } from '$lib/choices';
  import Icon from '$lib/components/Icon.svelte';

  let {
    choices,
    active,
    answer,
    onsubmit
  }: {
    choices: Choices;
    /** Só a última pergunta, na vez do analista, aceita resposta. */
    active: boolean;
    /** A resposta já enviada a esta pergunta, para mostrá-la marcada. */
    answer?: string;
    onsubmit: (text: string) => void;
  } = $props();

  let selected = $state<string[]>([]);
  let note = $state('');
  let otherInput = $state<HTMLInputElement | null>(null);

  /* "Outro" existe sempre, venha ou não do agente: é a saída para quem não se
     vê em nenhuma alternativa. Marcado, abre o campo de texto livre. */
  const options = $derived([
    ...choices.options,
    { label: OTHER_LABEL, description: 'Responder com as minhas palavras' }
  ]);
  const otherOn = $derived(selected.includes(OTHER_LABEL));
  const shown = $derived(active ? new Set(selected) : pickedFrom(answer, choices));
  const ready = $derived(
    selected.length > 0 && (!otherOn || note.trim().length > 0)
  );

  function toggle(label: string) {
    if (!active) return;
    if (choices.multiple) {
      selected = selected.includes(label)
        ? selected.filter((l) => l !== label)
        : [...selected, label];
    } else {
      selected = selected[0] === label ? [] : [label];
    }
    if (label === OTHER_LABEL && selected.includes(OTHER_LABEL)) {
      queueMicrotask(() => otherInput?.focus());
    }
  }

  function submit() {
    if (!active || !ready) return;
    /* Mantém a ordem em que o agente listou, não a ordem dos cliques. */
    const ordered = choices.options.map((o) => o.label).filter((l) => selected.includes(l));
    onsubmit(composeAnswer(ordered, otherOn ? note : ''));
    selected = [];
    note = '';
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }
</script>

<div class="choices" class:is-active={active}>
  <p class="label hint">
    {choices.multiple ? 'Marque uma ou mais' : 'Escolha uma'}
  </p>

  <ul role={choices.multiple ? 'group' : 'radiogroup'}>
    {#each options as o (o.label)}
      <li>
        <button
          type="button"
          class="opt"
          class:is-on={shown.has(o.label)}
          role={choices.multiple ? 'checkbox' : 'radio'}
          aria-checked={shown.has(o.label)}
          disabled={!active}
          onclick={() => toggle(o.label)}
        >
          <span class="mark" class:square={choices.multiple} aria-hidden="true"></span>
          <span class="text">
            <span class="opt-label">{o.label}</span>
            {#if o.description}<span class="opt-desc">{o.description}</span>{/if}
          </span>
        </button>
      </li>
    {/each}
  </ul>

  {#if active}
    <div class="foot">
      {#if otherOn}
        <input
          class="input"
          type="text"
          bind:this={otherInput}
          bind:value={note}
          placeholder="Escreva a sua resposta"
          aria-label="Resposta livre (Outro)"
          onkeydown={onKeydown}
        />
      {:else}
        <span class="spacer" aria-hidden="true"></span>
      {/if}
      <button type="button" class="btn btn-solid btn-sm" onclick={submit} disabled={!ready}>
        Responder <Icon name="send" size={12} />
      </button>
    </div>
  {/if}
</div>

<style>
  .choices {
    margin-top: var(--s4);
  }

  .hint {
    margin-bottom: var(--s2);
    color: var(--ink-3);
  }

  ul {
    border-top: 1px solid var(--rule);
  }

  .opt {
    width: 100%;
    display: flex;
    align-items: flex-start;
    gap: var(--s3);
    padding: var(--s3) var(--s2);
    text-align: left;
    background: transparent;
    border: 0;
    border-bottom: 1px solid var(--rule);
    color: var(--ink-2);
    font: inherit;
    font-size: var(--t-body);
    line-height: 1.5;
    transition:
      background var(--fast) var(--ease),
      color var(--fast) var(--ease);
  }

  .is-active .opt {
    cursor: pointer;
  }

  .is-active .opt:hover {
    background: var(--paper-sunk);
    color: var(--ink);
  }

  .opt:disabled {
    cursor: default;
  }

  /* Pergunta já respondida: as opções não escolhidas recuam. */
  .choices:not(.is-active) .opt:not(.is-on) {
    color: var(--ink-3);
  }

  .opt.is-on {
    color: var(--ink);
  }

  .opt.is-on .opt-label {
    font-weight: 600;
  }

  /* Marcador por forma e preenchimento, nunca por cor. */
  .mark {
    flex-shrink: 0;
    width: 12px;
    height: 12px;
    margin-top: 0.3em;
    border: 1px solid var(--ink-2);
    border-radius: 50%;
  }

  .mark.square {
    border-radius: 0;
  }

  .is-on .mark {
    border-color: var(--ink);
    background: var(--ink);
    box-shadow: inset 0 0 0 2px var(--paper);
  }

  .text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .opt-label {
    color: inherit;
  }

  .opt-desc {
    font-size: var(--t-small);
    color: var(--ink-3);
  }

  .foot {
    display: flex;
    gap: var(--s2);
    margin-top: var(--s3);
  }

  .foot .input,
  .spacer {
    flex: 1;
    min-width: 0;
  }
</style>
