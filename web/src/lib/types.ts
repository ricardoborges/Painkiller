import { t } from './i18n/index.svelte';

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

export type HarnessType = 'agy_superpowers' | 'deepseek_superpowers' | 'maki_superpowers' | 'unreal_superpowers';

/** Harnesses que autenticam com a chave DeepSeek (dsh, maki e unreal compartilham a mesma). */
export const DEEPSEEK_KEY_HARNESSES: readonly HarnessType[] = [
  'deepseek_superpowers',
  'maki_superpowers',
  'unreal_superpowers'
];

/** Nome de cada harness, na ordem do formulário de projeto. Nomes próprios: não se traduzem. */
export const HARNESS_NAMES: Record<HarnessType, string> = {
  agy_superpowers: 'Antigravity (agy)',
  deepseek_superpowers: 'DeepSeek Harness (dsh)',
  maki_superpowers: 'Maki',
  unreal_superpowers: 'Unreal Agent'
};

/** Modelos sugeridos por harness; o primeiro é o padrão (os mesmos presets do ProjectForm). */
export const HARNESS_MODELS: Record<HarnessType, readonly string[]> = {
  agy_superpowers: ['gemini-3.8-flash', 'gemini-3.8-pro', 'gemini-2.5-flash', 'gemini-2.5-pro'],
  deepseek_superpowers: ['deepseek-flash', 'deepseek-v4-pro'],
  maki_superpowers: ['deepseek/deepseek-v4-pro', 'deepseek/deepseek-v4-flash', 'deepseek/deepseek-flash'],
  unreal_superpowers: ['deepseek-flash', 'deepseek-v4-pro']
};

export type EffortLevel = 'low' | 'medium' | 'high';

/** Harnesses com nível de esforço ajustável (agy e dsh); Maki e Unreal não têm. */
export const EFFORT_HARNESSES: readonly HarnessType[] = ['agy_superpowers', 'deepseek_superpowers'];

export const EFFORT_LEVELS: { id: EffortLevel; label: string }[] = [
  {
    id: 'low',
    get label() {
      return t('effort.low');
    }
  },
  {
    id: 'medium',
    get label() {
      return t('effort.medium');
    }
  },
  {
    id: 'high',
    get label() {
      return t('effort.high');
    }
  }
];

/** Esta edição só fabrica apps Android: web empacotado com Capacitor (o nativo em Kotlin está inativo). */
export const PROJECT_TYPES = ['android_native', 'capacitor_react'] as const;

/** Todo projeto novo nasce do Capacitor, o único template ativo. */
export const DEFAULT_TEMPLATE_ID = 'capacitor-react';

export type ProjectType = (typeof PROJECT_TYPES)[number];

export const PROJECT_TYPE_META: Record<ProjectType, { label: string; description: string }> = {
  android_native: {
    get label() {
      return t('projectType.android_native.label');
    },
    get description() {
      return t('projectType.android_native.description');
    }
  },
  capacitor_react: {
    get label() {
      return t('projectType.capacitor_react.label');
    },
    get description() {
      return t('projectType.capacitor_react.description');
    }
  }
};

export interface ProjectTemplate {
  id: string;
  name: string;
  description: string;
  project_type: ProjectType;
  coolify_compatible: boolean;
  skill_path?: string | null;
  skill_filename?: string | null;
  scaffold_path?: string | null;
  scaffold_filename?: string | null;
  /** Sem .zip do admin, os projetos nascem do arcabouço embutido. */
  bundled_scaffold: boolean;
  prompt: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** A prévia do app: o último build web incorporado, mostrado no smartphone do backlog. */
export interface AppPreview {
  /** Só um app web (Capacitor) tem prévia; o Kotlin nativo, não. */
  supported: boolean;
  available: boolean;
  /** Carregada por iframe, sem cabeçalhos: a chave assinada já vem na URL. */
  url: string | null;
  task_id: string | null;
  task_title: string | null;
  built_at: string | null;
}

export interface Project {
  id: string;
  name: string;
  repo_path: string;
  description: string;
  purpose: string;
  solution_description: string;
  implementation_notes?: string;
  attachments: string[];
  default_branch: string;
  repo_url?: string | null;
  coolify_project_uuid?: string | null;
  test_url?: string | null;
  production_url?: string | null;
  harness?: HarnessType;
  model?: string | null;
  effort?: EffortLevel | null;
  /** Idioma do agente: entrevista, specs, backlog, código e commits. */
  language?: 'pt-BR' | 'en-US';
  /** Template de que o projeto nasceu; fixo depois da criação. */
  template_id?: string;
  has_api_key?: boolean;
  masked_api_key?: string | null;
  /** O repositório tem backend/ (FastAPI) ao lado do app. */
  has_backend?: boolean;
  created_at: string;
}

export interface ProjectDoc {
  path: string;
  filename: string;
  category: 'spec' | 'plan' | 'brainstorming' | 'backlog' | 'doc';
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
  /** Falso numa sessão direta; a primeira é sempre guiada. */
  guided?: boolean;
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
  /** Issue espelhada no Gitea; nula enquanto o espelho não a criou. */
  issue_number?: number | null;
  issue_url?: string | null;
  /** Desligado, o agente vai direto ao ponto, sem as skills do superpowers. */
  use_superpowers?: boolean;
  /** Escrita à mão no backlog: só essas podem ser excluídas. */
  manual?: boolean;
  /** Acumulado de todas as execuções: tempo de relógio e tokens do agente. */
  elapsed_seconds?: number;
  input_tokens?: number;
  output_tokens?: number;
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
  id: string;
  username: string;
  name: string;
  email: string;
  role: 'admin' | 'user';
  /** Conta no Gitea dona dos repositórios deste usuário. */
  gitea_username: string | null;
}

export interface AuthConfig {
  /** Login com Google configurado no servidor. */
  google: boolean;
  /** Já existe um administrador (criado no primeiro acesso). */
  break_glass: boolean;
  /** Instalação nova: a única coisa a fazer é criar o administrador. */
  first_access: boolean;
}

export interface RegisterData {
  first_name: string;
  last_name: string;
  email: string;
  password: string;
  confirm_password: string;
}

export interface RegisterResult {
  status: string;
  email: string;
  message: string;
}

export interface VerifyCodeData {
  email: string;
  code: string;
}

export interface SmtpConfigData {
  smtp_host?: string;
  smtp_port?: number;
  smtp_user?: string;
  smtp_password?: string;
  smtp_from?: string;
  smtp_tls?: boolean;
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
  BACKLOG: {
    get label() {
      return t('status.BACKLOG');
    },
    accent: false, hatch: false, done: false
  },
  READY: {
    get label() {
      return t('status.READY');
    },
    accent: false, hatch: false, done: false
  },
  RUNNING: {
    get label() {
      return t('status.RUNNING');
    },
    accent: false, hatch: false, done: false
  },
  AWAITING_ANALYST: {
    get label() {
      return t('status.AWAITING_ANALYST');
    },
    accent: true, hatch: false, done: false
  },
  IN_REVIEW: {
    get label() {
      return t('status.IN_REVIEW');
    },
    accent: false, hatch: false, done: false
  },
  COMPLETED: {
    get label() {
      return t('status.COMPLETED');
    },
    accent: false, hatch: false, done: true
  },
  FAILED: {
    get label() {
      return t('status.FAILED');
    },
    accent: false, hatch: true, done: false
  }
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

/** Um arquivo que a branch da tarefa mudou (GET /tasks/{id}/changes). */
export interface FileChange {
  path: string;
  /** A (novo), M (alterado), D (removido). */
  status: 'A' | 'M' | 'D';
  additions: number;
  deletions: number;
  binary: boolean;
  /** Só os hunks; null para binário ou quando a resposta passou do teto. */
  patch: string | null;
  truncated: boolean;
}

export interface BranchChanges {
  branch: string;
  base_branch: string;
  /** false: a branch ainda não existe ou já foi apagada. */
  available: boolean;
  /** A branch está em checkout: inclui o que o agente ainda não commitou. */
  live: boolean;
  files: FileChange[];
  /** Arquivos além do teto do servidor, só contados. */
  omitted: number;
  /** Já incorporada: o diff vem do commit de merge, mesmo com a branch apagada. */
  merged: boolean;
  merge_commit: string | null;
  /** O mesmo diff no Gitea (commit de merge ou comparação), quando há repositório. */
  web_url: string | null;
}

export interface AgentEvent {
  type: AgentEventType;
  text: string;
  timestamp: string;
  /** Só no stream de tarefas: alvo da ferramenta (comando, arquivo), quando o backend o reconhece. */
  detail?: string | null;
  /** Só na análise: erro anunciado pelo harness (sem saldo, chave recusada), não ruído. */
  fatal?: boolean;
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

/** Definido pelo admin, vale para todos os projetos; o orçamento é por projeto. */
export interface UsageSettings {
  /** Unidades da moeda local por 1 USD. */
  exchange_rate: number | null;
  local_currency: string;
  /** Preço por modelo para qualquer harness (lista anterior aos preços por harness). */
  prices: Record<string, ModelPrice>;
  /** Preço por harness e modelo: o que cada projeto herda do seu harness. */
  harness_prices: Partial<Record<HarnessType, Record<string, ModelPrice>>>;
}

/** Preços de um projeto: os herdados do admin e os que ele sobrescreve. */
export interface ProjectPrices {
  harness: HarnessType;
  /** Modelo efetivo do projeto (o escolhido ou o padrão do harness). */
  model: string;
  inherited: Record<string, ModelPrice>;
  overrides: Record<string, ModelPrice>;
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
    price_source: 'project' | 'settings' | 'catalog' | 'none';
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

export type EnvironmentType = 'test' | 'production';
export type DeploymentStatus = 'PENDING' | 'BUILDING' | 'HEALTHY' | 'FAILED' | 'STOPPED';

export type ApkVariant = 'debug' | 'release';
export type ApkBuildStatus = 'BUILDING' | 'SUCCESS' | 'FAILED';

/** APK gerado da branch padrão; o release sai assinado com a chave do projeto. */
export interface ApkBuild {
  id: string;
  project_id: string;
  variant: ApkVariant;
  status: ApkBuildStatus;
  branch: string;
  commit_sha?: string | null;
  size_bytes?: number | null;
  logs?: string | null;
  error?: string | null;
  /** O arquivo ainda existe no disco (builds antigos são podados). */
  available: boolean;
  created_at: string;
  finished_at?: string | null;
}

/** Link assinado e temporário do APK, para o QR code (o celular não tem sessão). */
export interface ApkLink {
  url: string;
  expires_at: string;
  /** A URL pública da plataforma é local (localhost): o celular não a alcança. */
  local: boolean;
}

/** Para onde vai um segredo do projeto: o build do app (VITE_*) ou só o backend. */
export type SecretScope = 'app' | 'server';

/** Segredo como a API o mostra: nunca o valor. */
export interface ProjectSecret {
  name: string;
  scope: SecretScope;
  updated_at: string;
}

/** O que o deploy publica: o build web do app ou o backend/ (cada um é uma aplicação no Coolify). */
export type DeploymentComponent = 'app' | 'backend';

export interface DeploymentRecord {
  id: string;
  project_id: string;
  task_id?: string | null;
  session_id?: string | null;
  environment: EnvironmentType;
  component?: DeploymentComponent;
  branch: string;
  commit_sha?: string | null;
  status: DeploymentStatus;
  coolify_app_uuid?: string | null;
  coolify_deployment_uuid?: string | null;
  url?: string | null;
  logs?: string | null;
  created_at: string;
  updated_at: string;
}

export interface EnvironmentStatus {
  url: string | null;
  status: DeploymentStatus | null;
  branch: string | null;
  updated_at: string | null;
  deployment_id: string | null;
}

export interface EnvironmentStatusResponse {
  project_id: string;
  test: EnvironmentStatus;
  production: EnvironmentStatus;
  /** Só quando o projeto tem backend/. */
  backend?: { test: EnvironmentStatus; production: EnvironmentStatus } | null;
}


/* ---- setup inicial (wizard do admin) ---- */

export type SetupStep = 'environment' | 'google' | 'coolify';
export type SetupStepStatus = 'pending' | 'done' | 'skipped';

export interface SetupImageRow {
  harness: string;
  images: string[];
  present: boolean;
}

export interface SetupEnvironment {
  public_url: string;
  public_url_saved: boolean;
  /** Validade das sessões, em horas. */
  session_ttl_hours: number;
  in_container: boolean;
  host_root: string | null;
  /** De onde veio o valor: salvo no wizard ou detectado no contêiner. */
  host_root_source: 'settings' | 'detected' | null;
  detected_host_root: string | null;
  docker_ok: boolean;
  images: SetupImageRow[];
}

export interface SetupGoogle {
  client_id: string;
  has_secret: boolean;
  masked_secret: string | null;
  allowed_domains: string;
  redirect_uris: { painkiller: string; gitea: string };
  enabled: boolean;
}

export interface SetupCoolify {
  dashboard_url: string;
  has_token: boolean;
  masked_token: string | null;
  server_uuid: string;
  wildcard_domain: string;
  suggested_wildcard_domain: string;
  root_email: string | null;
  has_root_password: boolean;
}

export interface SetupSmtp {
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_password_set: boolean;
  smtp_from: string;
  smtp_tls: boolean;
}

export interface SetupState {
  completed: boolean;
  admin_username: string | null;
  steps: Record<SetupStep, SetupStepStatus>;
  environment: SetupEnvironment;
  google: SetupGoogle;
  coolify: SetupCoolify;
  smtp?: SetupSmtp;
}

export interface CoolifyCheck {
  reachable: boolean;
  token_ok: boolean;
  version: string | null;
  /** usable = o Coolify validou SSH e Docker e aceita deploy nele. */
  servers: { uuid: string; name: string; ip: string; usable: boolean }[];
  error: string | null;
}

export interface CoolifyStatus {
  container: {
    reachable: boolean;
    root_user: boolean;
    root_email: string | null;
    api_enabled: boolean;
    error: string | null;
  };
  api: CoolifyCheck;
  coolify: SetupCoolify;
}

export interface CoolifyBootstrapResult {
  created_user: boolean;
  email: string;
  /** Só vem quando a conta root foi criada agora. */
  password: string | null;
  api: CoolifyCheck;
  state: SetupState;
}

export interface KeyValidation {
  /** null = não foi possível confirmar (rede, provedor fora). */
  valid: boolean | null;
  detail: string | null;
}
