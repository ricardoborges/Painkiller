import { api } from '$lib/api';
import type { DeploymentRecord, DeploymentStatus, EnvironmentType } from '$lib/types';
import { toast } from '$lib/stores/toast.svelte';

/**
 * Acompanha os deploys no Coolify até terminarem.
 *
 * `POST /deploy` só dispara: o Coolify clona, constrói e publica por minutos
 * depois disso. Este módulo consulta `GET /deployments/{id}` (que atualiza o
 * status e os logs a partir do Coolify) até um estado final e então avisa com
 * um toast. Vive fora da rota de propósito: sair do backlog e voltar não perde
 * o acompanhamento, e o aviso chega em qualquer página.
 */

const POLL_MS = 3000;
/** Um build que passa disso provavelmente travou; paramos de perguntar. */
const GIVE_UP_MS = 30 * 60 * 1000;
/** Erros de rede seguidos antes de desistir. */
const MAX_ERRORS = 5;

const FINAL: DeploymentStatus[] = ['HEALTHY', 'FAILED', 'STOPPED'];

export function isDeployActive(r: DeploymentRecord | null | undefined): boolean {
  return !!r && (r.status === 'PENDING' || r.status === 'BUILDING');
}

export const DEPLOY_STAGE: Record<DeploymentStatus, string> = {
  PENDING: 'Na fila do Coolify',
  BUILDING: 'Construindo e publicando',
  HEALTHY: 'No ar',
  FAILED: 'Falhou',
  STOPPED: 'Interrompido'
};

const ENV_LABEL: Record<EnvironmentType, string> = {
  test: 'Ambiente de teste',
  production: 'Produção'
};

/** O SQLite devolve datas sem fuso; o backend grava em UTC. */
function parseUtc(iso: string): number {
  const hasZone = /(Z|[+-]\d\d:?\d\d)$/.test(iso);
  return Date.parse(hasZone ? iso : iso + 'Z');
}

/** Última linha não vazia do log — o que o Coolify está fazendo agora. */
export function lastLogLine(logs: string | null | undefined): string {
  if (!logs) return '';
  const lines = logs.split('\n');
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim();
    if (line) return line.length > 160 ? line.slice(0, 160) + '…' : line;
  }
  return '';
}

export function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}

class DeployTracker {
  records = $state<Record<string, DeploymentRecord>>({});
  /** Relógio compartilhado para o tempo decorrido; só anda com deploy ativo. */
  now = $state(Date.now());
  /** Sobe a cada deploy encerrado, para as páginas recarregarem o que dependem. */
  settled = $state(0);

  private polling = new Set<string>();
  private startedAt = new Map<string, number>();
  private finishedAt = new Map<string, number>();
  private clock: ReturnType<typeof setInterval> | null = null;

  /** Deploy mais recente acompanhado de um projeto (e ambiente, se dado). */
  latest(projectId: string, env?: EnvironmentType): DeploymentRecord | null {
    let best: DeploymentRecord | null = null;
    for (const r of Object.values(this.records)) {
      if (r.project_id !== projectId || (env && r.environment !== env)) continue;
      if (!best || this.started(r) > this.started(best)) best = r;
    }
    return best;
  }

  active(projectId: string, env?: EnvironmentType): DeploymentRecord | null {
    const r = this.latest(projectId, env);
    return isDeployActive(r) ? r : null;
  }

  /** Deploy de teste em andamento com a branch desta tarefa. */
  activeForTask(taskId: string): DeploymentRecord | null {
    for (const r of Object.values(this.records)) {
      if (r.task_id === taskId && isDeployActive(r)) return r;
    }
    return null;
  }

  elapsed(r: DeploymentRecord): string {
    const end = isDeployActive(r) ? this.now : (this.finishedAt.get(r.id) ?? parseUtc(r.updated_at));
    return formatElapsed(end - this.started(r));
  }

  /** Passa a acompanhar um deploy recém-disparado (ou já encerrado, e só avisa). */
  track(record: DeploymentRecord) {
    this.startedAt.set(record.id, this.startedAt.get(record.id) ?? Date.now());
    this.records[record.id] = record;
    if (!isDeployActive(record)) {
      this.finish(record);
      return;
    }
    this.poll(record.id);
  }

  /**
   * Retoma um deploy que já estava em andamento quando a página abriu (depois
   * de um F5, por exemplo). Não avisa se ele já tinha terminado.
   */
  async resume(deploymentId: string) {
    if (this.polling.has(deploymentId) || this.records[deploymentId]) return;
    try {
      const record = await api.getDeployment(deploymentId);
      if (!isDeployActive(record)) return;
      this.records[record.id] = record;
      this.poll(record.id);
    } catch {
      // Sem acesso ao registro: nada a acompanhar.
    }
  }

  reset() {
    this.records = {};
    this.polling.clear();
    this.startedAt.clear();
    this.finishedAt.clear();
    this.stopClock();
  }

  private started(r: DeploymentRecord): number {
    return this.startedAt.get(r.id) ?? parseUtc(r.created_at);
  }

  private async poll(id: string) {
    if (this.polling.has(id)) return;
    this.polling.add(id);
    this.startClock();
    let errors = 0;
    try {
      while (this.polling.has(id)) {
        await new Promise((r) => setTimeout(r, POLL_MS));
        if (!this.polling.has(id)) return;
        const current = this.records[id];
        if (!current) return;
        if (this.now - this.started(current) > GIVE_UP_MS) {
          toast.show({
            tone: 'failed',
            title: `${ENV_LABEL[current.environment]}: sem resposta do Coolify`,
            detail: 'O deploy passou de 30 minutos sem terminar. Confira no Coolify.',
            duration: 12000
          });
          return;
        }
        try {
          const fresh = await api.getDeployment(id);
          errors = 0;
          this.records[id] = fresh;
          if (!isDeployActive(fresh)) {
            this.finish(fresh);
            return;
          }
        } catch {
          if (++errors >= MAX_ERRORS) {
            toast.show({
              tone: 'failed',
              title: 'Perdi o contato com o deploy',
              detail: 'Não consegui consultar o andamento. Recarregue a página para tentar de novo.',
              duration: 12000
            });
            return;
          }
        }
      }
    } finally {
      this.polling.delete(id);
      if (!this.polling.size) this.stopClock();
    }
  }

  private finish(r: DeploymentRecord) {
    this.finishedAt.set(r.id, Date.now());
    this.settled++;
    const env = ENV_LABEL[r.environment];
    const took = this.elapsed(r);
    if (r.status === 'HEALTHY') {
      toast.show({
        tone: 'done',
        title: r.environment === 'test' ? `${env} pronto` : 'Deploy em produção concluído',
        detail: `Branch ${r.branch} · ${took}`,
        href: r.url ?? undefined,
        hrefLabel: r.url ? 'Abrir aplicação' : undefined,
        duration: 9000
      });
    } else {
      toast.show({
        tone: 'failed',
        title: r.status === 'STOPPED' ? `${env}: deploy interrompido` : `${env}: deploy falhou`,
        detail: lastLogLine(r.logs) || `Branch ${r.branch}`,
        duration: 12000
      });
    }
  }

  private startClock() {
    if (this.clock) return;
    this.now = Date.now();
    this.clock = setInterval(() => (this.now = Date.now()), 1000);
  }

  private stopClock() {
    if (this.clock) clearInterval(this.clock);
    this.clock = null;
  }
}

export const deploys = new DeployTracker();
