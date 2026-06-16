export type CleaningStatus = "raw" | "cleaned" | "rejected" | "golden";
export type DatasetType = "train" | "eval" | "rag";
export type JobStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export interface FlywheelStats {
  total_samples: number;
  raw_count: number;
  cleaned_count: number;
  rejected_count: number;
  golden_count: number;
  annotated_count: number;
  with_images_count: number;
}

export interface FlywheelAnnotation {
  id: number;
  sample_id: number;
  label_success: boolean | null;
  label_purpose: string | null;
  label_action: string | null;
  notes: string | null;
  annotated_by: string;
  is_golden: boolean;
  created_at: string;
  updated_at: string;
}

export interface FlywheelSample {
  id: number;
  source_run_uuid: string;
  source_step_order: number;
  case_name: string;
  description: string;
  step_type: string;
  step_status: string;
  cleaning_status: CleaningStatus;
  auto_verification_success: boolean | null;
  auto_purpose: string | null;
  auto_confidence: number | null;
  quality_score: number;
  has_before_image: boolean;
  has_after_image: boolean;
  exclude_reason: string | null;
  cleaning_notes: string | null;
  synced_at: string;
  updated_at: string;
  annotation: FlywheelAnnotation | null;
  before_image?: string | null;
  after_image?: string | null;
}

export interface FlywheelSampleListResponse {
  items: FlywheelSample[];
  total: number;
}

export interface FlywheelDataset {
  id: number;
  name: string;
  description: string;
  dataset_type: DatasetType;
  sample_count: number;
  filters_json: Record<string, unknown> | null;
  created_at: string;
}

export interface FlywheelRagDocument {
  id: number;
  dataset_id: number | null;
  title: string;
  content: string;
  metadata: Record<string, unknown> | null;
  source_sample_ids: number[];
  created_at: string;
}

export interface TrainingConfig {
  base_model: string;
  epochs: number;
  learning_rate: number;
  batch_size: number;
  val_split: number;
  max_samples?: number | null;
  lora_rank: number;
  warmup_ratio: number;
}

export interface FlywheelTrainingJob {
  id: number;
  job_uuid: string;
  name: string;
  dataset_id: number;
  status: JobStatus;
  config: TrainingConfig | null;
  progress_pct: number;
  current_stage: string | null;
  artifact_path: string | null;
  metrics: Record<string, unknown> | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface EvalSampleResult {
  sample_id: number;
  source_run_uuid: string;
  source_step_order: number;
  golden_success: boolean | null;
  predicted_success: boolean | null;
  golden_purpose: string | null;
  predicted_purpose: string | null;
  success_match: boolean | null;
  purpose_score: number | null;
  overall_score: number | null;
  reasoning: string | null;
}

export interface FlywheelEvalJob {
  id: number;
  job_uuid: string;
  name: string;
  dataset_id: number;
  training_job_id: number | null;
  llm_provider: string | null;
  model_ref: string | null;
  status: JobStatus;
  config: Record<string, unknown> | null;
  progress_pct: number;
  current_stage: string | null;
  results: Record<string, unknown> | null;
  sample_results: EvalSampleResult[];
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface AnnotationPayload {
  label_success?: boolean | null;
  label_purpose?: string | null;
  label_action?: string | null;
  notes?: string | null;
  is_golden?: boolean;
}
