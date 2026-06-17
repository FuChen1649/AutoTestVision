import type { AgentRunState, AgentStepRecord, StepAttemptRecord } from "./agent";

export interface GeneratedStepCode {
  code_line: string;
  confidence?: number;
  reasoning?: string;
  template_path?: string | null;
  execution_output?: string | null;
  pytest_exit_code?: number | null;
}

export interface CodeStepRecord {
  step_order: number;
  step_type: string;
  description: string;
  status: string;
  generated_code?: GeneratedStepCode | null;
  verification?: { success: boolean; confidence?: number; reasoning?: string } | null;
  before_image?: string | null;
  before_image_annotated?: string | null;
  after_image?: string | null;
  ui_xml_preview?: string | null;
  error?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface CodeRunState {
  run_id: string;
  case_id: number;
  case_name: string;
  script_content?: string;
  serial?: string | null;
  status: string;
  current_step_index: number;
  total_steps: number;
  retry_count: number;
  max_retries: number;
  error?: string | null;
  llm_provider?: string | null;
  enable_verifier?: boolean;
  steps: CodeStepRecord[];
  created_at: string;
  updated_at: string;
}

export interface CodeStreamEvent {
  type: string;
  run?: CodeRunState;
  message?: string;
  logs?: unknown[];
}

export function codeRunToGalleryRun(run: CodeRunState): AgentRunState {
  const steps: AgentStepRecord[] = run.steps.map((step) => ({
    step_order: step.step_order,
    step_type: step.step_type,
    description: step.description,
    status: step.status,
    before_image: step.before_image,
    before_image_annotated: step.before_image_annotated,
    after_image: step.after_image,
    error: step.error,
    metadata: step.metadata,
    verification: step.verification,
    intent: step.generated_code
      ? {
          action: "tap",
          x: 0,
          y: 0,
          confidence: step.generated_code.confidence,
          reasoning: step.generated_code.code_line,
        }
      : null,
  }));
  const attempts: StepAttemptRecord[] = run.steps
    .filter((step) => step.before_image || step.before_image_annotated || step.after_image)
    .map((step) => ({
      step_order: step.step_order,
      attempt_index: 0,
      before_image: step.before_image,
      before_image_annotated: step.before_image_annotated,
      after_image: step.after_image,
      status: step.status,
      error: step.error,
      step_type: step.step_type,
      intent: steps.find((s) => s.step_order === step.step_order)?.intent ?? null,
      metadata: step.metadata,
    }));
  return {
    run_id: run.run_id,
    case_id: run.case_id,
    case_name: run.case_name,
    serial: run.serial,
    status: run.status,
    current_step_index: run.current_step_index,
    total_steps: run.total_steps,
    retry_count: run.retry_count,
    max_retries: run.max_retries,
    error: run.error,
    llm_provider: run.llm_provider,
    enable_verifier: run.enable_verifier,
    steps,
    attempts,
    created_at: run.created_at,
    updated_at: run.updated_at,
  };
}
