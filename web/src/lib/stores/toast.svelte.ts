/**
 * Avisos passageiros no canto da tela: aparecem, esperam alguns segundos e
 * somem sozinhos. Pausam enquanto o ponteiro está em cima, para dar tempo de
 * clicar no link.
 *
 * Sem cor: um aviso de falha se distingue por peso e hachura, como o resto da
 * interface — o acento continua reservado para o agente parado esperando o
 * analista.
 */

export type ToastTone = 'done' | 'failed' | 'info';

export interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  detail?: string;
  href?: string;
  hrefLabel?: string;
  duration: number;
}

export interface ToastInput {
  tone?: ToastTone;
  title: string;
  detail?: string;
  href?: string;
  hrefLabel?: string;
  /** Milissegundos até sumir. */
  duration?: number;
}

class ToastStore {
  items = $state<Toast[]>([]);
  private seq = 0;
  private timers = new Map<number, { handle: ReturnType<typeof setTimeout>; endsAt: number; left: number }>();

  show(input: ToastInput): number {
    const id = ++this.seq;
    const toast: Toast = { tone: 'info', duration: 7000, ...input, id };
    this.items = [...this.items, toast];
    this.arm(id, toast.duration);
    return id;
  }

  dismiss(id: number) {
    const t = this.timers.get(id);
    if (t) clearTimeout(t.handle);
    this.timers.delete(id);
    this.items = this.items.filter((x) => x.id !== id);
  }

  pause(id: number) {
    const t = this.timers.get(id);
    if (!t) return;
    clearTimeout(t.handle);
    t.left = Math.max(0, t.endsAt - Date.now());
  }

  resume(id: number) {
    const t = this.timers.get(id);
    if (!t) return;
    this.arm(id, t.left);
  }

  private arm(id: number, ms: number) {
    const handle = setTimeout(() => this.dismiss(id), ms);
    this.timers.set(id, { handle, endsAt: Date.now() + ms, left: ms });
  }
}

export const toast = new ToastStore();
