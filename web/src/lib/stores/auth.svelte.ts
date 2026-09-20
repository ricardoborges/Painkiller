import { api, getToken, setToken } from '$lib/api';
import type { User } from '$lib/types';

/**
 * A autenticação do backend é um stub de usuário único (ver
 * painkiller/api/routes/auth.py) e nenhuma rota a exige. Este gate é
 * conveniência de navegação, não fronteira de segurança.
 */
class AuthStore {
  user = $state<User | null>(null);
  ready = $state(false);

  get signedIn() {
    return this.user !== null;
  }

  /** Revalida o token guardado na sessão. Chamado uma vez no layout raiz. */
  async restore() {
    if (this.ready) return;
    const token = getToken();
    if (!token) {
      this.ready = true;
      return;
    }
    try {
      this.user = await api.me();
    } catch {
      setToken(null);
      this.user = null;
    } finally {
      this.ready = true;
    }
  }

  async signIn(username: string, password: string) {
    const { token, user } = await api.login(username, password);
    setToken(token);
    this.user = user;
    this.ready = true;
  }

  signOut() {
    setToken(null);
    this.user = null;
  }
}

export const auth = new AuthStore();
