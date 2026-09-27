import type { Task } from '$lib/types';

/* Tempo e tokens gastos pelas tarefas. Cada tarefa guarda o acumulado de
   todas as suas execuções; a sessão e o projeto são só a soma delas. */

export interface TaskTotals {
  seconds: number;
  input: number;
  output: number;
}

export function taskTotals(tasks: Task[]): TaskTotals {
  let seconds = 0;
  let input = 0;
  let output = 0;
  for (const t of tasks) {
    seconds += t.elapsed_seconds ?? 0;
    input += t.input_tokens ?? 0;
    output += t.output_tokens ?? 0;
  }
  return { seconds, input, output };
}

/** "2h 05min", "12min 30s", "45s". */
export function formatDuration(seconds: number): string {
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h) return `${h}h ${String(m).padStart(2, '0')}min`;
  return `${m}min ${String(s % 60).padStart(2, '0')}s`;
}

const compact = new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 });

export function formatTokens(n: number): string {
  return compact.format(n);
}
