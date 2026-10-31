import { t } from '$lib/i18n/index.svelte';
import { api, apkDownloadUrl } from '$lib/api';
import type { ApkBuild, ApkVariant } from '$lib/types';
import { toast } from '$lib/stores/toast.svelte';

/**
 * Builds de APK por projeto, compartilhados entre o backlog e o painel.
 *
 * `POST /apk-builds` só dispara: npm e Gradle levam minutos. Enquanto houver
 * um build em BUILDING, o módulo relê a lista a cada poucos segundos e, ao
 * terminar, avisa com um toast que já traz o link de download. Vive fora das
 * rotas pelo mesmo motivo dos deploys: trocar de aba não perde o aviso.
 */

const POLL_MS = 4000;

/** O SQLite devolve datas sem fuso; o backend grava em UTC. */
function parseUtc(iso: string): number {
  const hasZone = /(Z|[+-]\d\d:?\d\d)$/.test(iso);
  return Date.parse(hasZone ? iso : iso + 'Z');
}

export function formatApkSize(bytes: number | null | undefined): string {
  if (!bytes) return '';
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

class ApkBuilds {
  byProject = $state<Record<string, ApkBuild[]>>({});
  /** Relógio do tempo decorrido; só anda com build ativo. */
  now = $state(Date.now());
  starting = $state<Record<string, ApkVariant | null>>({});

  private polling = new Set<string>();
  private loaded = new Set<string>();
  private clock: ReturnType<typeof setInterval> | null = null;

  list(projectId: string): ApkBuild[] {
    return this.byProject[projectId] ?? [];
  }

  active(projectId: string): ApkBuild | null {
    return this.list(projectId).find((b) => b.status === 'BUILDING') ?? null;
  }

  /** Último build de uma variante, qualquer que seja o resultado. */
  latest(projectId: string, variant: ApkVariant): ApkBuild | null {
    return this.list(projectId).find((b) => b.variant === variant) ?? null;
  }

  /** Último APK baixável de uma variante. */
  latestReady(projectId: string, variant: ApkVariant): ApkBuild | null {
    return this.list(projectId).find((b) => b.variant === variant && b.available) ?? null;
  }

  elapsed(build: ApkBuild): string {
    const end = build.finished_at ? parseUtc(build.finished_at) : this.now;
    const s = Math.max(0, Math.floor((end - parseUtc(build.created_at)) / 1000));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }

  /** Carrega uma vez por projeto (e de novo com `force`). */
  async load(projectId: string, force = false): Promise<void> {
    if (this.loaded.has(projectId) && !force) return;
    this.loaded.add(projectId);
    try {
      this.byProject[projectId] = await api.listApkBuilds(projectId);
    } catch {
      this.loaded.delete(projectId);
      return;
    }
    if (this.active(projectId)) void this.poll(projectId);
  }

  async start(projectId: string, variant: ApkVariant): Promise<void> {
    const running = this.active(projectId);
    if (running) return;
    this.starting[projectId] = variant;
    try {
      const build = await api.startApkBuild(projectId, variant);
      this.byProject[projectId] = [build, ...this.list(projectId)];
      void this.poll(projectId);
    } catch (e) {
      toast.show({
        tone: 'failed',
        title: t('apk.startFailed'),
        detail: e instanceof Error ? e.message : undefined,
        duration: 10000
      });
    } finally {
      this.starting[projectId] = null;
    }
  }

  private async poll(projectId: string): Promise<void> {
    if (this.polling.has(projectId)) return;
    this.polling.add(projectId);
    this.startClock();
    try {
      while (true) {
        await new Promise((r) => setTimeout(r, POLL_MS));
        const before = this.active(projectId);
        if (!before) return;
        let fresh: ApkBuild[];
        try {
          fresh = await api.listApkBuilds(projectId);
        } catch {
          continue;
        }
        this.byProject[projectId] = fresh;
        const done = fresh.find((b) => b.id === before.id);
        if (done && done.status !== 'BUILDING') this.announce(done);
        if (!this.active(projectId)) return;
      }
    } finally {
      this.polling.delete(projectId);
      this.stopClockIfIdle();
    }
  }

  private announce(build: ApkBuild): void {
    const kind = build.variant === 'release' ? t('apk.release') : t('apk.debug');
    if (build.status === 'SUCCESS') {
      toast.show({
        tone: 'done',
        title: t('apk.ready', { kind }),
        detail: formatApkSize(build.size_bytes),
        href: build.available ? apkDownloadUrl(build) : undefined,
        hrefLabel: t('apk.download'),
        duration: 15000
      });
    } else {
      toast.show({
        tone: 'failed',
        title: t('apk.failed', { kind }),
        detail: build.error ?? undefined,
        duration: 12000
      });
    }
  }

  private startClock(): void {
    if (this.clock) return;
    this.clock = setInterval(() => (this.now = Date.now()), 1000);
  }

  private stopClockIfIdle(): void {
    if (this.polling.size === 0 && this.clock) {
      clearInterval(this.clock);
      this.clock = null;
    }
  }
}

export const apkBuilds = new ApkBuilds();
