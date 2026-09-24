import { api } from '$lib/api';
import type { SetupState } from '$lib/types';

/**
 * Estado do wizard de setup inicial. Só o admin o carrega: o layout usa
 * `completed` para mandá-lo a /setup no primeiro acesso, e o wizard e a
 * página de configurações leem e substituem o mesmo objeto.
 */
class SetupStore {
  state = $state<SetupState | null>(null);
  error = $state<string | null>(null);
  #loading: Promise<void> | null = null;

  get completed() {
    return this.state?.completed ?? true;
  }

  /** Carrega uma vez; chamadas seguintes reaproveitam o resultado. */
  ensure(): Promise<void> {
    this.#loading ??= this.reload();
    return this.#loading;
  }

  async reload() {
    try {
      this.state = await api.setupState();
      this.error = null;
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'Não foi possível carregar a configuração.';
    }
  }

  set(state: SetupState) {
    this.state = state;
  }

  reset() {
    this.state = null;
    this.error = null;
    this.#loading = null;
  }
}

export const setup = new SetupStore();
