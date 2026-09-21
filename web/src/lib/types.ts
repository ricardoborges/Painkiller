/** Espelha painkiller/core/domain/models.py */

export const TASK_STATUSES = [
  'BACKLOG',
  'READY',
  'RUNNING',
  'AWAITING_ANALYST',
  'IN_REVIEW',
  'COMPLETED',
  'FAILED'
] as const;

export type TaskStatus = (typeof TASK_STATUSES)[number];

export type ClarificationStatus = 'PENDING' | 'ANSWERED';

export interface Project {
  id: string;
  name: string;
  repo_path: string;
  description: string;
  purpose: string;
  solution_description: string;
  attachments: string[];
  default_branch: string;
  repo_url?: string | null;
  created_at: string;
}

export interface ProjectDoc {
  path: string;
  filename: string;
  category: 'spec' | 'plan' | 'backlog' | 'doc';
  size_bytes: number;
  modified_at: string;
  is_session_spec?: boolean;
}

export interface ProjectDocContent {
  path: string;
  filename: string;
  content: string;
  size_bytes: number;
  modified_at: string;
}

export const SESSION_STATUSES = ['PLANNING', 'BACKLOG', 'IN_SPRINT', 'COMPLETED'] as const;
export type SessionStatus = (typeof SESSION_STATUSES)[number];

export interface IterationSession {
  id: string;
  project_id: string;
  number: number;
  title: string;
  status: SessionStatus;
  analysis_session_id?: string | null;
  spec_path?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  description: string;
  target_files: string[];
  acceptance_criteria: string[];
  dependencies: string[];
  status: TaskStatus;
  assigned_branch: string | null;
  session_id?: string | null;
  last_comment?: string | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Clarification {
  id: string;
  task_id: string;
  question: string;
  context_summary: string;
  status: ClarificationStatus;
  answer: string | null;
  created_at: string;
  answered_at: string | null;
}

export interface User {
  username: string;
  name: string;
  role: string;
}

export interface InterrogationStart {
  session_id: string;
  project_id?: string;
  question: string;
  history: { role: string; content: string }[];
}

/**
 * Rótulo e tratamento visual de cada status.
 *
 * `accent` é verdadeiro em exatamente um status: AWAITING_ANALYST. É o único
 * ponto da interface autorizado a usar cor — o agente parou e depende de você.
 */
export const STATUS_META: Record<
  TaskStatus,
  { label: string; accent: boolean; hatch: boolean; done: boolean }
> = {
  BACKLOG: { label: 'Backlog', accent: false, hatch: false, done: false },
  READY: { label: 'Pronta', accent: false, hatch: false, done: false },
  RUNNING: { label: 'Executando', accent: false, hatch: false, done: false },
  AWAITING_ANALYST: { label: 'Aguardando analista', accent: true, hatch: false, done: false },
  IN_REVIEW: { label: 'Em revisão', accent: false, hatch: false, done: false },
  COMPLETED: { label: 'Concluída', accent: false, hatch: false, done: true },
  FAILED: { label: 'Falhou', accent: false, hatch: true, done: false }
};

/** Ordem de leitura do backlog: o que exige ação primeiro. */
export const STATUS_ORDER: TaskStatus[] = [
  'AWAITING_ANALYST',
  'RUNNING',
  'READY',
  'IN_REVIEW',
  'BACKLOG',
  'FAILED',
  'COMPLETED'
];

/* ---- análise inicial interativa (Claude Code + superpowers) ---- */

export const ANALYSIS_STATUSES = [
  'STARTING',
  'WAITING_AGENT',
  'WAITING_ANALYST',
  'FINISHED',
  'FAILED'
] as const;

export type AnalysisStatus = (typeof ANALYSIS_STATUSES)[number];

export interface AnalysisSession {
  session_id: string;
  project_id: string;
  status: AnalysisStatus;
  container_name: string | null;
  exit_code: number | null;
  error: string | null;
  spec_path: string | null;
}

export type AgentEventType =
  | 'SYSTEM'
  | 'ASSISTANT'
  | 'THINKING'
  /** Pedaços em andamento; o ASSISTANT canônico chega depois com o texto todo. */
  | 'ASSISTANT_DELTA'
  | 'THINKING_DELTA'
  | 'TOOL_USE'
  | 'TOOL_RESULT'
  | 'USER'
  | 'RESULT'
  | 'ERROR'
  | 'EXIT';

export interface AgentEvent {
  type: AgentEventType;
  text: string;
  timestamp: string;
  /** Só no stream de tarefas: alvo da ferramenta (comando, arquivo), quando o backend o reconhece. */
  detail?: string | null;
}

/** Primeiro frame do stream de uma tarefa: se este servidor está mesmo executando-a. */
export interface TaskStreamState {
  active: boolean;
  started_at: string | null;
  last_event_at: string | null;
}

/* ---- custos ---- */

export type UsageSource = 'ANALYSIS' | 'TASK' | 'LLM';

export interface ModelPrice {
  /** USD por 1 milhão de tokens. */
  input_per_mtok: number;
  output_per_mtok: number;
}

/** Vale para todos os projetos; o orçamento é por projeto. */
export interface UsageSettings {
  /** Unidades da moeda local por 1 USD. */
  exchange_rate: number | null;
  local_currency: string;
  prices: Record<string, ModelPrice>;
}

export interface UsageBucket {
  key: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  calls: number;
  /** Chamadas com tokens mas sem preço conhecido — fora do custo. */
  unpriced_calls: number;
}

export interface UsageSummary {
  totals: Omit<UsageBucket, 'key'> & { total_tokens: number };
  budget: {
    budget_usd: number | null;
    spent_usd: number;
    remaining_usd: number | null;
    used_ratio: number | null;
  };
  currency: { local: string; exchange_rate: number | null };
  by_source: (UsageBucket & { key: UsageSource })[];
  by_model: (UsageBucket & {
    price: ModelPrice | null;
    price_source: 'settings' | 'catalog' | 'none';
  })[];
  daily: { date: string; cost_usd: number; tokens: number }[];
}

export interface UsageEntry {
  id: string;
  source: UsageSource;
  model: string;
  project_id: string | null;
  task_id: string | null;
  session_id: string | null;
  input_tokens: number;
  output_tokens: number;
  reported_cost_usd: number | null;
  cost_usd: number | null;
  created_at: string;
}

export interface ProviderBalance {
  provider: string;
  name: string;
  /** false = o provedor não expõe saldo por API. */
  supported: boolean;
  balance: number | null;
  currency: string | null;
  error: string | null;
}
