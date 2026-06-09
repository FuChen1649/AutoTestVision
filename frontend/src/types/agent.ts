export interface CaseListItem {
  id: number;
  name: string;
  step_count: number;
  updated_at: string;
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
  steps: AgentStepRecord[];
  created_at: string;
  updated_at: string;
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
