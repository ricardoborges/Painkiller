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
  /** Comando de verificação; null = detectado pelo conteúdo do repositório. */
  test_command?: string | null;
  deployment?: DeploymentInfo | null;
  created_at: string;
}

/* ---- publicação em produção (Coolify) ---- */

export const DEPLOYMENT_STATUSES = [
  'NOT_CONFIGURED',
  'CREATED',
  'DEPLOYING',
  'LIVE',
  'FAILED'
] as const;

export type DeploymentStatus = (typeof DEPLOYMENT_STATUSES)[number];

export interface DeploymentInfo {
  provider: string;
  build_pack: string;
  port: number;
  dockerfile_location: string | null;
  app_uuid: string | null;
  url: string | null;
  last_deployment_uuid: string | null;
  status: DeploymentStatus;
  error: string | null;
  updated_at: string;
}

export interface DeploymentView {
  /** O servidor tem as variáveis COOLIFY_*; sem elas "Publicar" fica desativado. */
  configured: boolean;
  deployment: DeploymentInfo | null;
}

export const DEPLOYMENT_LABEL: Record<DeploymentStatus, string> = {
  NOT_CONFIGURED: 'Ainda não publicado',
  CREATED: 'Aplicação criada, aguardando o primeiro deploy',
  DEPLOYING: 'Publicando',
  LIVE: 'No ar',
  FAILED: 'A publicação falhou'
};

/* ---- piloto automático ---- */

export type AutopilotState = 'IDLE' | 'RUNNING' | 'PUBLISHING' | 'DONE' | 'PAUSED' | 'FAILED';

export interface AutopilotRun {
  project_id: string;
  state: AutopilotState;
  current_task_id: string | null;
  current_task_title: string | null;
  completed: number;
  total: number;
  message: string;
  publish: boolean;
  started_at: string;
  finished_at: string | null;
}

export const AUTOPILOT_ACTIVE: AutopilotState[] = ['RUNNING', 'PUBLISHING'];

export interface ProjectDoc {
  path: string;
  filename: string;
  category: 'spec' | 'plan' | 'backlog' | 'doc';
  size_bytes: number;
  modified_at: string;
}

export interface ProjectDocContent {
  path: string;
  filename: string;
  content: string;
  size_bytes: number;
  modified_at: string;
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
  /** Fala do analista, reemitida no replay para reconstruir a conversa. */
  | 'USER'
  | 'ASSISTANT'
  | 'THINKING'
  /** Pedaços em andamento; o ASSISTANT canônico chega depois com o texto todo. */
  | 'ASSISTANT_DELTA'
  | 'THINKING_DELTA'
  | 'TOOL_USE'
  | 'TOOL_RESULT'
  | 'RESULT'
  | 'ERROR'
  | 'EXIT';

export interface AgentEvent {
  type: AgentEventType;
  text: string;
  timestamp: string;
}
