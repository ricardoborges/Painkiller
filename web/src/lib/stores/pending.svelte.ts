import { api } from '$lib/api';
import type { Project, Task } from '$lib/types';

export interface PendingEntry {
  task: Task;
  project: Project;
}

/**
 * Tarefas paradas em AWAITING_ANALYST — o agente rodou `painkiller ask`,
 * commitou o WIP e saiu com 42. É a fila de trabalho do analista.
 *
 * A API não expõe um endpoint global de pendências, então isto varre os
 * projetos e busca as tarefas de cada um (N+1). Aguenta bem a escala atual;
 * se o número de projetos crescer, vale um `GET /api/clarifications/pending`
 * no backend.
 */
class PendingStore {
  entries = $state<PendingEntry[]>([]);
  loading = $state(false);
  loaded = $state(false);
  error = $state<string | null>(null);

  get count() {
    return this.entries.length;
  }

  async refresh() {
    if (this.loading) return;
    this.loading = true;
    this.error = null;
    try {
      const projects = await api.listProjects();
      const found: PendingEntry[] = [];
      const lists = await Promise.all(
        projects.map((p) => api.listTasks(p.id).catch(() => [] as Task[]))
      );
      lists.forEach((tasks, i) => {
        for (const task of tasks) {
          if (task.status === 'AWAITING_ANALYST') found.push({ task, project: projects[i] });
        }
      });
      found.sort((a, b) => b.task.updated_at.localeCompare(a.task.updated_at));
      this.entries = found;
      this.loaded = true;
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'Falha ao carregar pendências.';
    } finally {
      this.loading = false;
    }
  }

  /** Carrega uma vez; chamadas seguintes são no-op até um refresh explícito. */
  async ensure() {
    if (this.loaded || this.loading) return;
    await this.refresh();
  }

  reset() {
    this.entries = [];
    this.loaded = false;
    this.error = null;
  }
}

export const pending = new PendingStore();
