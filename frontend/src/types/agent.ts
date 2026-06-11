export interface CaseStepPreview {
  step_order: number;
  step_type?: string;
  description: string;
}

export interface CaseListItem {
  id: number;
  name: string;
  step_count: number;
  updated_at: string;
  steps: CaseStepPreview[];
}

export interface ActionIntent {
  action: "tap" | "swipe" | "long_press" | "skip";
  x?: number | null;
  y?: number | null;
  x2?: number | null;
  y2?: number | null;
  duration_ms?: number;
  confidence?: number;
  reasoning?: string;
}

export interface VerificationResult {
  success: boolean;
  confidence?: number;
  reasoning?: string;
}

export interface StepPurposeReviewRecord {
  step_order: number;
  purpose: string;
  reasoning: string;
  confidence?: number;
  model?: string | null;
  reviewed_at: string;
}

export interface StepAttemptRecord {
  step_order: number;
  attempt_index: number;
  before_image?: string | null;
  before_image_annotated?: string | null;
  after_image?: string | null;
  status: string;
  error?: string | null;
  step_type?: string | null;
  intent?: ActionIntent | null;
  metadata?: Record<string, unknown> | null;
}

export interface AgentStepRecord {
  step_order: number;
  step_type: string;
  description: string;
  status: string;
  intent?: ActionIntent | null;
  verification?: VerificationResult | null;
  before_image?: string | null;
  before_image_annotated?: string | null;
  after_image?: string | null;
  error?: string | null;
  metadata?: Record<string, unknown> | null;
  purpose_review?: StepPurposeReviewRecord | null;
}

export interface AgentRunState {
  run_id: string;
  case_id: number;
  case_name: string;
  serial?: string | null;
  status: string;
  current_step_index: number;
  total_steps: number;
  retry_count: number;
  max_retries: number;
  error?: string | null;
  llm_provider?: string | null;
  enable_verifier?: boolean;
  steps: AgentStepRecord[];
  attempts: StepAttemptRecord[];
  created_at: string;
  updated_at: string;
}

export interface ProviderInfo {
  id: string;
  label: string;
  model: string;
  base_url: string;
  available: boolean;
}

export interface ProvidersResponse {
  providers: ProviderInfo[];
  default: string | null;
}

export interface AgentLogItem {
  id: number;
  step_order?: number | null;
  agent_type: string;
  message: string;
  detail?: Record<string, unknown> | null;
  created_at: string;
}

export interface StreamEvent {
  type: string;
  node?: string | null;
  run?: AgentRunState | null;
  logs?: AgentLogItem[];
  message?: string | null;
}

export interface DeviceReplayStreamEvent {
  type: "start" | "recover" | "step" | "wait" | "done" | "error";
  message?: string | null;
  step_order?: number | null;
  step_index?: number | null;
  total_steps?: number | null;
  action?: string | null;
}

export interface BatchResultItem {
  result_id: number;
  run_id: string;
  case_id: number;
  case_name: string;
  case_order: number;
  status: string;
  total_steps: number;
  passed_steps: number;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BatchState {
  batch_id: string;
  status: string;
  serial?: string | null;
  llm_provider?: string | null;
  enable_verifier?: boolean;
  total_cases: number;
  completed_cases: number;
  passed_cases: number;
  failed_cases: number;
  error?: string | null;
  results: BatchResultItem[];
  created_at: string;
  updated_at: string;
}

export interface BatchListItem {
  batch_id: string;
  status: string;
  total_cases: number;
  completed_cases: number;
  passed_cases: number;
  failed_cases: number;
  llm_provider?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BatchStreamEvent {
  type: string;
  batch?: BatchState | null;
  result?: BatchResultItem | null;
  run?: AgentRunState | null;
  logs?: AgentLogItem[];
  message?: string | null;
}
