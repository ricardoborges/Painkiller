/**
 * Tema da interface. O padrão é claro; o escuro só entra quando o usuário
 * escolhe, e a escolha fica no navegador (localStorage). O script inline em
 * app.html aplica o valor salvo antes da pintura, para não piscar branco.
 */
export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'pk_theme';

function read(): Theme {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'dark' ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

function apply(theme: Theme) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (theme === 'dark') root.dataset.theme = 'dark';
  else delete root.dataset.theme;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', theme === 'dark' ? '#121214' : '#ffffff');
}

class ThemeStore {
  current = $state<Theme>(typeof localStorage === 'undefined' ? 'light' : read());

  toggle() {
    this.set(this.current === 'dark' ? 'light' : 'dark');
  }

  set(theme: Theme) {
    this.current = theme;
    apply(theme);
    try {
      if (theme === 'dark') localStorage.setItem(STORAGE_KEY, 'dark');
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }
}

export const theme = new ThemeStore();
