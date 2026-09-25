import { api } from '$lib/api';
import type { IterationSession } from '$lib/types';

/**
 * Gerencia o ciclo de sessões iterativas do projeto.
 * Vive fora da árvore de componentes para persistir entre rotas.
 */
export class ProjectSessionStore {
  readonly projectId: string;

  sessions = $state<IterationSession[]>([]);
  activeSessionId = $state<string | null>(null);
  loading = $state(false);
  /** A lista já veio do servidor ao menos uma vez (vazia ainda é resposta). */
  loaded = $state(false);
  creating = $state(false);
  error = $state<string | null>(null);

  readonly activeSession = $derived(
    this.sessions.find((s) => s.id === this.activeSessionId) ??
      this.sessions[this.sessions.length - 1] ??
      null
  );

  constructor(projectId: string) {
    this.projectId = projectId;
    this.#restoreActiveId();
  }

  get storageKey() {
    return `pk_active_session_${this.projectId}`;
  }

  #restoreActiveId() {
    if (typeof localStorage === 'undefined') return;
    try {
      this.activeSessionId = localStorage.getItem(this.storageKey);
    } catch {
      /* ignore storage errors */
    }
  }

  #persistActiveId(id: string | null) {
    if (typeof localStorage === 'undefined') return;
    try {
      if (id) localStorage.setItem(this.storageKey, id);
      else localStorage.removeItem(this.storageKey);
    } catch {
      /* ignore */
    }
  }

  selectSession(id: string) {
    this.activeSessionId = id;
    this.#persistActiveId(id);
  }

  async loadSessions(preferredId?: string): Promise<IterationSession[]> {
    this.loading = true;
    this.error = null;
    try {
      const list = await api.listSessions(this.projectId);
      this.sessions = list;

      if (preferredId && list.some((s) => s.id === preferredId)) {
        this.selectSession(preferredId);
      } else if (this.activeSessionId && list.some((s) => s.id === this.activeSessionId)) {
        // mantém a selecionada
      } else if (list.length > 0) {
        // Seleciona a mais recente por padrão
        const latest = list[list.length - 1];
        this.selectSession(latest.id);
      }

      return list;
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'Falha ao carregar sessões do projeto.';
      return [];
    } finally {
      this.loading = false;
      this.loaded = true;
    }
  }

  /** Alguma sessão já foi encerrada: o projeto tem histórico para um painel. */
  get hasCompleted(): boolean {
    return this.sessions.some((s) => s.status === 'COMPLETED');
  }

  async createNextSession(title?: string): Promise<IterationSession | null> {
    this.creating = true;
    this.error = null;
    try {
      const created = await api.createSession(this.projectId, title);
      await this.loadSessions(created.id);
      return created;
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'Falha ao criar nova sessão.';
      return null;
    } finally {
      this.creating = false;
    }
  }

  /** Encerra a sessão: o backend apaga as branches das tarefas já incorporadas. */
  async finalizeSession(id: string): Promise<boolean> {
    this.error = null;
    try {
      const updated = await api.updateSession(this.projectId, id, { status: 'COMPLETED' });
      this.sessions = this.sessions.map((s) => (s.id === id ? updated : s));
      return true;
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'Falha ao encerrar a sessão.';
      return false;
    }
  }
}

const stores = new Map<string, ProjectSessionStore>();

export function getProjectSessionStore(projectId: string): ProjectSessionStore {
  let store = stores.get(projectId);
  if (!store) {
    store = new ProjectSessionStore(projectId);
    stores.set(projectId, store);
  }
  return store;
}
