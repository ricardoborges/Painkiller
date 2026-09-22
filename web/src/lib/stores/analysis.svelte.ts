import { ApiError, api, openAnalysisStream } from '$lib/api';
import type { AgentEvent, AnalysisSession, ProjectDoc, Task } from '$lib/types';

export interface Turn {
  who: 'agent' | 'analyst';
  text: string;
}

/**
 * Uma sessão de análise viva, fora do ciclo de vida da rota.
 *
 * A página de análise é um componente de rota: sair dela para o backlog e
 * voltar a destruía, fechando o EventSource e zerando a transcrição. O agente
 * continuava no contêiner, mas o analista via uma tela em branco e, no pior
 * caso, subia um segundo contêiner. Mantendo o estado aqui — num módulo, não
 * num componente — navegar entre as abas do projeto passa a ser só troca de
 * view: o stream nunca fecha e nada é remontado.
 */
export class AnalysisStore {
  readonly projectId: string;
  /** Sessão iterativa dona desta conversa; sem ela o backend cai na mais recente. */
  readonly iterationSessionId: string | undefined;

  session = $state<AnalysisSession | null>(null);
  turns = $state<Turn[]>([]);
  /** Linhas não-JSON do contêiner (avisos do node, falhas de plugin). */
  diagnostics = $state<string[]>([]);
  /** Documentos do superpowers descobertos no repositório. */
  docs = $state<ProjectDoc[]>([]);

  starting = $state(false);
  startError = $state<string | null>(null);
  sendError = $state<string | null>(null);
  closing = $state(false);
  committing = $state(false);
  streamClosed = $state(false);
  loadingDocs = $state(false);

  /** Texto do turno em andamento, montado a partir dos deltas. */
  streaming = $state('');
  /** Raciocínio do modelo enquanto ele ainda não escreveu nada visível. */
  reasoning = $state('');
  /** O rascunho também sobrevive à navegação — perder o que foi digitado irrita. */
  draft = $state('');

  waitingSince = $state(Date.now());

  /** O agente devolveu o turno: é a única hora em que o analista pode digitar. */
  readonly myTurn = $derived(this.session?.status === 'WAITING_ANALYST' && !this.streamClosed);
  readonly finished = $derived(this.session?.status === 'FINISHED' || this.streamClosed);

  #dispose: (() => void) | null = null;
  #booting: Promise<void> | null = null;
  #booted = false;

  constructor(projectId: string, iterationSessionId?: string) {
    this.projectId = projectId;
    this.iterationSessionId = iterationSessionId;
  }

  get storageKey() {
    return analysisStorageKey(this.projectId, this.iterationSessionId);
  }

  /** Sobe a sessão na primeira visita; nas seguintes é no-op. */
  ensureBooted(): Promise<void> {
    if (this.#booted) return Promise.resolve();
    if (this.#booting) return this.#booting;
    this.#booting = this.boot().finally(() => {
      this.#booting = null;
    });
    return this.#booting;
  }

  remember(id: string | null) {
    try {
      if (id) {
        sessionStorage.setItem(this.storageKey, id);
        localStorage.setItem(this.storageKey, id);
      } else {
        sessionStorage.removeItem(this.storageKey);
        localStorage.removeItem(this.storageKey);
      }
    } catch {
      /* modo privado / storage bloqueado */
    }
  }

  recall(): string | null {
    try {
      return sessionStorage.getItem(this.storageKey) || localStorage.getItem(this.storageKey);
    } catch {
      return null;
    }
  }

  async boot(forceNew = false) {
    this.#booted = true;
    this.starting = true;
    this.startError = null;
    this.turns = [];
    this.diagnostics = [];
    this.streaming = '';
    this.reasoning = '';
    this.streamClosed = false;
    this.waitingSince = Date.now();
    this.refreshDocs();

    if (!forceNew) {
      try {
        const current = await api.getCurrentAnalysis(this.projectId, this.iterationSessionId);
        if (current?.session) {
          this.session = current.session;
          this.remember(this.session.session_id);
          this.attach(this.session.session_id);
          this.starting = false;
          return;
        }
      } catch {
        /* se a rota não responder, usa o fallback local */
      }

      const previous = this.recall();
      if (previous) {
        try {
          // O stream reemite o histórico, então reatar é suficiente.
          this.session = await api.getAnalysis(previous);
          this.attach(previous);
          this.starting = false;
          return;
        } catch {
          // Sessão não encontrada: limpa e recomeça.
          this.remember(null);
        }
      }
    }

    try {
      this.session = await api.startAnalysis(this.projectId, forceNew, this.iterationSessionId);
      this.remember(this.session.session_id);
      this.attach(this.session.session_id);
    } catch (e) {
      this.#booted = false;
      this.startError = e instanceof Error ? e.message : 'Falha ao subir o agente de análise.';
    } finally {
      this.starting = false;
    }
  }

  attach(sessionId: string) {
    this.#dispose?.();
    this.#dispose = openAnalysisStream(
      sessionId,
      (e) => this.onEvent(e),
      () => {
        this.streamClosed = true;
      }
    );
  }

  commitAgentText(text: string) {
    const clean = text.trim();
    if (!clean) return;

    const last = this.turns[this.turns.length - 1];
    if (last?.who === 'agent') {
      if (last.text === clean) return;
      this.turns[this.turns.length - 1] = { who: 'agent', text: clean };
      this.turns = [...this.turns];
      return;
    }

    this.turns = [...this.turns, { who: 'agent', text: clean }];
  }

  onEvent(event: AgentEvent) {
    switch (event.type) {
      case 'ASSISTANT_DELTA':
        this.streaming += event.text;
        // Assim que o texto de verdade começa, o raciocínio perde a vez.
        this.reasoning = '';
        break;
      case 'THINKING_DELTA':
        if (!this.streaming) this.reasoning += event.text;
        break;
      case 'USER': {
        const last = this.turns[this.turns.length - 1];
        if (last?.who !== 'analyst' || last.text !== event.text) {
          this.turns = [...this.turns, { who: 'analyst', text: event.text }];
        }
        break;
      }
      case 'ASSISTANT':
        // Canônico: substitui o que foi montado por delta, então um pedaço
        // perdido no caminho não deixa o texto truncado na tela.
        if (event.text?.trim()) this.commitAgentText(event.text);
        this.streaming = '';
        this.reasoning = '';
        break;
      case 'TOOL_USE':
        if (this.streaming.trim()) this.commitAgentText(this.streaming);
        this.streaming = '';
        this.reasoning = '';
        // Quem usa a análise não é desenvolvedor: o nome da ferramenta não entra
        // na conversa, o indicador "Trabalhando." já diz que o agente está ativo.
        // Superpowers grava spec e plano em disco, então os artefatos são relidos.
        this.refreshDocs();
        break;
      case 'RESULT': {
        // O turno do agente acabou: garante que a fala final entre no histórico.
        const finalText = event.text?.trim() || this.streaming.trim();
        if (finalText) this.commitAgentText(finalText);
        this.streaming = '';
        this.reasoning = '';
        if (this.session) this.session = { ...this.session, status: 'WAITING_ANALYST' };
        this.refreshDocs();
        break;
      }
      case 'EXIT':
        if (this.session) {
          this.session = { ...this.session, status: event.text === '0' ? 'FINISHED' : 'FAILED' };
        }
        break;
      case 'ERROR':
        this.diagnostics = [...this.diagnostics, event.text];
        break;
    }
  }

  /** Envia o rascunho do composer, ou `answer` quando vem das opções clicáveis. */
  async send(answer?: string) {
    const text = (answer ?? this.draft).trim();
    if (!text || !this.session || !this.myTurn) return;

    this.turns = [...this.turns, { who: 'analyst', text }];
    if (answer === undefined) this.draft = '';
    this.streaming = '';
    this.reasoning = '';
    this.sendError = null;
    this.waitingSince = Date.now();
    this.session = { ...this.session, status: 'WAITING_AGENT' };

    try {
      await api.answerAnalysis(this.session.session_id, text);
    } catch (e) {
      this.sendError =
        e instanceof ApiError && e.status === 404
          ? 'A sessão não existe mais no servidor. Recomece a análise.'
          : e instanceof Error
            ? e.message
            : 'Falha ao enviar a resposta.';
    }
  }

  async closeSession() {
    if (!this.session) return;
    this.closing = true;
    this.sendError = null;
    try {
      await api.finishAnalysis(this.session.session_id);
    } catch (e) {
      this.sendError = e instanceof Error ? e.message : 'Falha ao encerrar a sessão.';
    } finally {
      this.closing = false;
    }
  }

  /** Importa o backlog.json. Devolve as tarefas para a página navegar. */
  async commit(): Promise<Task[] | null> {
    if (!this.session) return null;
    this.committing = true;
    this.sendError = null;
    try {
      const tasks = await api.commitAnalysisBacklog(this.session.session_id, this.iterationSessionId);
      this.remember(null);
      return tasks;
    } catch (e) {
      this.sendError = e instanceof Error ? e.message : 'Falha ao importar o backlog.';
      return null;
    } finally {
      this.committing = false;
    }
  }

  async restart() {
    if (this.session) {
      try {
        await api.stopAnalysis(this.session.session_id);
      } catch {
        /* o contêiner já pode ter morrido */
      }
    }
    this.#dispose?.();
    this.#dispose = null;
    this.remember(null);
    this.session = null;
    await this.boot(true);
  }

  async refreshDocs() {
    this.loadingDocs = true;
    try {
      this.docs = await api.listProjectDocs(this.projectId);
    } catch {
      /* falha silenciosa em background */
    } finally {
      this.loadingDocs = false;
    }
  }

  /** Só no logout: fora isso a sessão é justamente o que deve persistir. */
  dispose() {
    this.#dispose?.();
    this.#dispose = null;
    this.#booted = false;
  }
}

export function analysisStorageKey(projectId: string, iterationSessionId?: string) {
  return iterationSessionId
    ? `pk_analysis_${projectId}_${iterationSessionId}`
    : `pk_analysis_${projectId}`;
}

const stores = new Map<string, AnalysisStore>();

/** Uma conversa por sessão iterativa: a Sessão 2 não herda a da Sessão 1. */
export function analysisFor(projectId: string, iterationSessionId?: string): AnalysisStore {
  const key = `${projectId}:${iterationSessionId ?? ''}`;
  let store = stores.get(key);
  if (!store) {
    store = new AnalysisStore(projectId, iterationSessionId);
    stores.set(key, store);
  }
  return store;
}

export function disposeAnalyses() {
  for (const store of stores.values()) store.dispose();
  stores.clear();
}
