<script lang="ts">
  import { api } from '$lib/api';
  import type { Clarification, Task } from '$lib/types';
  import Icon from './Icon.svelte';
  import Elapsed from './Elapsed.svelte';
  import Skeleton from './Skeleton.svelte';

  /**
   * A pergunta que o agente deixou ao sair com 42, e a caixa de resposta.
   *
   * Responder reexecuta a tarefa do início, na mesma branch e sobre o commit
   * de WIP que o `painkiller ask` deixou — e a requisição fica aberta o
   * tempo todo.
   */
  let {
    task,
    onresolved
  }: {
    task: Task;
    onresolved: (updated: Task) => void;
  } = $props();

  let clarification = $state<Clarification | null>(null);
  let loading = $state(true);
  let answer = $state('');
  let sending = $state(false);
  let startedAt = $state(0);
  let error = $state<string | null>(null);

  $effect(() => {
    const id = task.id;
    loading = true;
    error = null;
    api
      .getClarification(id)
      .then((res) => {
        clarification = 'status' in res && res.status === 'none' ? null : (res as Clarification);
      })
      .catch((e) => {
        error = e instanceof Error ? e.message : 'Falha ao ler a pendência.';
      })
      .finally(() => {
        loading = false;
      });
  });

  async function submit() {
    const text = answer.trim();
    if (!text || sending) return;
    sending = true;
    startedAt = Date.now();
    error = null;
    try {
      const updated = await api.answerClarification(task.id, text);
      answer = '';
      onresolved(updated);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Falha ao responder.';
    } finally {
      sending = false;
    }
  }
</script>

<div class="panel">
  {#if loading}
    <Skeleton variant="lines" rows={2} />
  {:else if !clarification}
    <p class="faint small">
      A tarefa está marcada como aguardando, mas não há pendência registrada.
    </p>
  {:else}
    <div class="q">
      <span class="label">Pergunta do agente</span>
      <p class="question">{clarification.question}</p>
      {#if clarification.context_summary}
        <p class="ctx mono">{clarification.context_summary}</p>
      {/if}
    </div>

    {#if sending}
      <div class="running">
        <span class="pulse" aria-hidden="true"></span>
        <span>
          Resposta entregue. O contêiner foi retomado na branch
          <span class="mono">{task.assigned_branch ?? `feature/${task.id}`}</span> — a requisição
          fica aberta até o agente terminar.
        </span>
        <Elapsed from={startedAt} />
      </div>
    {:else}
      <div class="answer">
        <textarea
          bind:value={answer}
          class="textarea"
          rows="3"
          placeholder="Responda de forma que o agente consiga decidir sozinho…"
        ></textarea>
        <div class="foot">
          <span class="help">Responder reexecuta a tarefa e pode levar minutos.</span>
          <button type="button" class="btn btn-accent" onclick={submit} disabled={!answer.trim()}>
            Responder e retomar <Icon name="arrow-right" size={12} />
          </button>
        </div>
      </div>
    {/if}
  {/if}

  {#if error}
    <p class="error-line" role="alert"><Icon name="alert" size={12} /> {error}</p>
  {/if}
</div>

<style>
  /* Único bloco da interface com borda de acento: é o que depende de você. */
  .panel {
    border: 1px solid var(--accent);
    background: var(--accent-sunk);
    padding: var(--s4);
  }

  .q :global(.label) {
    color: var(--accent-ink);
  }

  .question {
    margin-top: var(--s2);
    max-width: var(--measure);
  }

  .ctx {
    margin-top: var(--s2);
    font-size: var(--t-micro);
    color: var(--ink-2);
    overflow-wrap: anywhere;
  }

  .answer {
    margin-top: var(--s4);
  }

  .foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s4);
    margin-top: var(--s3);
    flex-wrap: wrap;
  }

  .running {
    display: flex;
    align-items: center;
    gap: var(--s3);
    margin-top: var(--s4);
    padding-top: var(--s3);
    border-top: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
    font-size: var(--t-small);
    color: var(--accent-ink);
  }

  .pulse {
    width: 6px;
    height: 6px;
    flex: none;
    background: var(--accent);
    animation: blink 1.3s var(--ease) infinite;
  }

  .small {
    font-size: var(--t-small);
  }

  .error-line {
    display: flex;
    align-items: flex-start;
    gap: var(--s2);
    margin-top: var(--s3);
    font-size: var(--t-small);
    color: var(--accent-ink);
  }

  .textarea {
    background: var(--paper);
  }
</style>
