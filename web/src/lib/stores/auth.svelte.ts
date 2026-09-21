import { api, getToken, setToken } from '$lib/api';
import type { User } from '$lib/types';

/**
 * O backend exige o token em toda rota fora de /api/auth e filtra os projetos
 * pelo dono (ver painkiller/api/security.py). Este gate só evita mostrar telas
 * que responderiam 401.
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

  /** Conclui o login Google: o callback devolve o token no fragmento de /login. */
  async signInWithToken(token: string) {
    setToken(token);
    try {
      this.user = await api.me();
    } catch (e) {
      setToken(null);
      this.user = null;
      throw e;
    } finally {
      this.ready = true;
    }
  }

  signOut() {
    setToken(null);
    this.user = null;
  }
}

export const auth = new AuthStore();
