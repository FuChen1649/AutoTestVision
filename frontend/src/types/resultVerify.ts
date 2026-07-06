import type { AgentRunState } from "./agent";

export interface StepPurposeReview {
  step_order: number;
  purpose: string;
  reasoning: string;
  confidence?: number;
  model?: string | null;
  reviewed_at: string;
}

export interface RunPurposeReview {
  run_id: string;
  case_name: string;
  reviews: StepPurposeReview[];
}

export interface BatchPurposeReview {
  batch_id: string;
  runs: RunPurposeReview[];
}

export interface DualStepVerifyReview {
  step_order: number;
  consistent: boolean;
  before_match: boolean;
  after_match: boolean;
  purpose: string;
  reasoning: string;
  confidence?: number;
  model?: string | null;
  reviewed_at: string;
}

export interface DualVerifyResult {
  task_id: string;
  case_name: string;
  reviews: DualStepVerifyReview[];
}

export interface VerifyStreamEvent {
  type: string;
  exec_mode?: "position" | "code" | "dual" | null;
  batch_id?: string | null;
  task_id?: string | null;
  run_id?: string | null;
  case_name?: string | null;
  step_order?: number | null;
  review?: StepPurposeReview | null;
  dual_review?: DualStepVerifyReview | null;
  run?: AgentRunState | null;
  message?: string | null;
}
