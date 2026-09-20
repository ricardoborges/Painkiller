import type {
  AgentEvent,
  AnalysisSession,
  Clarification,
  InterrogationStart,
  Project,
  Task,
  User
} from './types';

const TOKEN_KEY = 'pk_token';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function getToken(): string | null {
  if (typeof sessionStorage === 'undefined') return null;
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* modo privado / storage bloqueado */
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...init, headers });
  } catch (e) {
    throw new ApiError(
      'Não foi possível falar com o servidor. Verifique se o uvicorn está no ar.',
      0
    );
  }

  if (!res.ok) {
    let detail = `Erro HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      /* resposta sem corpo JSON */
    }
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const api = {
  /* ---- auth ---- */
  login: (username: string, password: string) =>
    request<{ token: string; user: User }>('/auth/login', {
      method: 'POST',
      ...json({ username, password })
    }),

  me: () => request<User>('/auth/me'),

  /* ---- projetos ---- */
  listProjects: () => request<Project[]>('/projects'),

  getProject: (id: string) => request<Project>(`/projects/${id}`),

  createProject: (body: {
    name: string;
    description?: string;
    purpose?: string;
    solution_description?: string;
  }) => request<Project>('/projects', { method: 'POST', ...json(body) }),

  updateProject: (
    id: string,
    body: {
      name?: string;
      description?: string;
      purpose?: string;
      solution_description?: string;
    }
  ) => request<Project>(`/projects/${id}`, { method: 'PUT', ...json(body) }),

  deleteProject: (id: string) =>
    request<{ status: string }>(`/projects/${id}`, { method: 'DELETE' }),

  uploadAttachment: (id: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<{ status: string; file_name: string; project: Project }>(
      `/projects/${id}/attachments`,
      { method: 'POST', body: form }
    );
  },

  /* ---- interrogação ---- */
  startInterrogation: (projectId: string) =>
    request<InterrogationStart>(`/projects/${projectId}/start-interrogation`, {
      method: 'POST'
    }),

  replyInterrogation: (sessionId: string, answer: string) =>
    request<{ reply: string; is_complete: boolean }>('/interrogation/reply', {
      method: 'POST',
      ...json({ session_id: sessionId, answer })
    }),

  commitBacklog: (sessionId: string) =>
    request<Task[]>('/interrogation/commit', {
      method: 'POST',
      ...json({ session_id: sessionId })
    }),

  /* ---- análise inicial (agente conteinerizado, streaming) ---- */

  /** Sobe o contêiner e retorna na hora; o acompanhamento é pelo stream. */
  startAnalysis: (projectId: string) =>
    request<AnalysisSession>(`/projects/${projectId}/analysis`, { method: 'POST' }),

  getAnalysis: (sessionId: string) => request<AnalysisSession>(`/analysis/${sessionId}`),

  answerAnalysis: (sessionId: string, answer: string) =>
    request<AnalysisSession>(`/analysis/${sessionId}/message`, {
      method: 'POST',
      ...json({ answer })
    }),

  /** Fecha o stdin do agente para que ele encerre o turno e saia. */
  finishAnalysis: (sessionId: string) =>
    request<AnalysisSession>(`/analysis/${sessionId}/finish`, { method: 'POST' }),

  /** Importa o .painkiller/backlog.json que o agente gravou no repositório. */
  commitAnalysisBacklog: (sessionId: string) =>
    request<Task[]>(`/analysis/${sessionId}/commit`, { method: 'POST' }),

  stopAnalysis: (sessionId: string) =>
    request<{ status: string }>(`/analysis/${sessionId}`, { method: 'DELETE' }),

  /* ---- tarefas ---- */
  listTasks: (projectId: string) => request<Task[]>(`/projects/${projectId}/tasks`),

  getTask: (id: string) => request<Task>(`/tasks/${id}`),

  /**
   * Atenção: o dispatch é síncrono no servidor — a requisição fica aberta
   * durante toda a execução do agente no contêiner. Pode levar minutos.
   */
  dispatchTask: (id: string) => request<Task>(`/tasks/${id}/dispatch`, { method: 'POST' }),

  getClarification: (taskId: string) =>
    request<Clarification | { status: 'none' }>(`/tasks/${taskId}/clarification`),

  /** Também síncrono: responde e reexecuta a tarefa do início. */
  answerClarification: (taskId: string, answer: string) =>
    request<Task>(`/tasks/${taskId}/clarification`, { method: 'POST', ...json({ answer }) })
};

/**
 * Assina o SSE da sessão de análise.
 *
 * Usa EventSource em vez de fetch porque o navegador já reconecta sozinho; o
 * backend reemite o histórico a cada assinatura, então reconectar não perde
 * conversa. Não dá para mandar Authorization aqui — nenhuma rota exige, e o
 * auth atual é um stub (ver api/routes/auth.py).
 */
export function openAnalysisStream(
  sessionId: string,
  onEvent: (event: AgentEvent) => void,
  onClose: () => void
): () => void {
  const source = new EventSource(`/api/analysis/${sessionId}/stream`);

  const forward = (e: MessageEvent) => {
    try {
      onEvent(JSON.parse(e.data) as AgentEvent);
    } catch {
      /* frame malformado: ignorar em vez de derrubar a conversa */
    }
  };

  const types: AgentEvent['type'][] = [
    'SYSTEM',
    'ASSISTANT',
    'ASSISTANT_DELTA',
    'THINKING',
    'THINKING_DELTA',
    'TOOL_USE',
    'TOOL_RESULT',
    'RESULT',
    'ERROR',
    'EXIT'
  ];
  for (const t of types) source.addEventListener(t, forward);

  source.addEventListener('CLOSE', () => {
    source.close();
    onClose();
  });

  return () => source.close();
}

/** O nome do arquivo a partir de um caminho absoluto Windows ou POSIX. */
export function baseName(path: string): string {
  return path.split('\\').pop()!.split('/').pop() ?? path;
}
