/**
 * O celular simulado do ambiente de teste: um só diálogo, montado no layout
 * raiz, aberto de qualquer lugar (painel, backlog, aviso de deploy pronto).
 *
 * Modal e não aba nova: o token vive no sessionStorage, que uma aba aberta com
 * `noopener` não herda — ela caía no login.
 */
class TestDevice {
  open = $state(false);
  url = $state<string | null>(null);

  show(url: string | null | undefined): void {
    if (!url) return;
    this.url = url;
    this.open = true;
  }
}

export const testDevice = new TestDevice();
