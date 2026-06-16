from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


CleaningStatus = Literal["raw", "cleaned", "rejected", "golden"]
DatasetType = Literal["train", "eval", "rag"]
JobStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class FlywheelStatsResponse(BaseModel):
    total_samples: int = 0
    raw_count: int = 0
    cleaned_count: int = 0
    rejected_count: int = 0
    golden_count: int = 0
    annotated_count: int = 0
    with_images_count: int = 0


class SyncSamplesRequest(BaseModel):
    limit_runs: int = Field(default=100, ge=1, le=500)
    only_success_steps: bool = False


class SyncSamplesResponse(BaseModel):
    synced: int
    created: int
    updated: int


class AnnotationPayload(BaseModel):
    label_success: bool | None = None
    label_purpose: str | None = None
    label_action: str | None = None
    notes: str | None = None
    is_golden: bool = False


class FlywheelAnnotationResponse(BaseModel):
    id: int
    sample_id: int
    label_success: bool | None = None
    label_purpose: str | None = None
    label_action: str | None = None
    notes: str | None = None
    annotated_by: str = "human"
    is_golden: bool = False
    created_at: datetime
    updated_at: datetime


class FlywheelSampleResponse(BaseModel):
    id: int
    source_run_uuid: str
    source_step_order: int
    case_name: str
    description: str
    step_type: str
    step_status: str
    cleaning_status: CleaningStatus
    auto_verification_success: bool | None = None
    auto_purpose: str | None = None
    auto_confidence: float | None = None
    quality_score: float = 0.0
    has_before_image: bool = False
    has_after_image: bool = False
    exclude_reason: str | None = None
    cleaning_notes: str | None = None
    synced_at: datetime
    updated_at: datetime
    annotation: FlywheelAnnotationResponse | None = None
    before_image: str | None = None
    after_image: str | None = None


class FlywheelSampleListResponse(BaseModel):
    items: list[FlywheelSampleResponse]
    total: int


class CleanSampleRequest(BaseModel):
    cleaning_status: CleaningStatus
    cleaning_notes: str | None = None
    exclude_reason: str | None = None


class BulkCleanRequest(BaseModel):
    sample_ids: list[int] = Field(default_factory=list)
    cleaning_status: CleaningStatus
    cleaning_notes: str | None = None


class BulkCleanResponse(BaseModel):
    updated: int


class AutoCleanRequest(BaseModel):
    min_quality_score: float = Field(default=0.5, ge=0, le=1)
    require_both_images: bool = True
    require_auto_verification: bool = False
    dedupe: bool = True


class AutoCleanResponse(BaseModel):
    marked_cleaned: int
    marked_rejected: int
    deduped: int


class CreateDatasetRequest(BaseModel):
    name: str
    description: str = ""
    dataset_type: DatasetType = "train"
    sample_ids: list[int] = Field(default_factory=list)
    golden_only: bool = False
    cleaning_statuses: list[CleaningStatus] | None = None


class FlywheelDatasetResponse(BaseModel):
    id: int
    name: str
    description: str
    dataset_type: DatasetType
    sample_count: int
    filters_json: dict | None = None
    created_at: datetime


class FlywheelDatasetListResponse(BaseModel):
    items: list[FlywheelDatasetResponse]


class GenerateRagRequest(BaseModel):
    dataset_id: int | None = None
    golden_only: bool = True
    use_llm_summary: bool = False
    llm_provider: str | None = None


class FlywheelRagDocumentResponse(BaseModel):
    id: int
    dataset_id: int | None = None
    title: str
    content: str
    metadata: dict | None = None
    source_sample_ids: list[int] = Field(default_factory=list)
    created_at: datetime


class FlywheelRagListResponse(BaseModel):
    items: list[FlywheelRagDocumentResponse]
    export_path: str | None = None


class TrainingConfig(BaseModel):
    base_model: str = "Qwen2.5-VL-7B-Instruct"
    epochs: int = Field(default=3, ge=1, le=50)
    learning_rate: float = Field(default=2e-5, gt=0)
    batch_size: int = Field(default=4, ge=1, le=64)
    val_split: float = Field(default=0.1, ge=0, le=0.5)
    max_samples: int | None = Field(default=None, ge=1)
    lora_rank: int = Field(default=8, ge=1, le=128)
    warmup_ratio: float = Field(default=0.05, ge=0, le=0.5)


class CreateTrainingJobRequest(BaseModel):
    name: str
    dataset_id: int
    config: TrainingConfig = Field(default_factory=TrainingConfig)


class FlywheelTrainingJobResponse(BaseModel):
    id: int
    job_uuid: str
    name: str
    dataset_id: int
    status: JobStatus
    config: TrainingConfig | None = None
    progress_pct: float = 0.0
    current_stage: str | None = None
    artifact_path: str | None = None
    metrics: dict | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class FlywheelTrainingJobListResponse(BaseModel):
    items: list[FlywheelTrainingJobResponse]


class EvalConfig(BaseModel):
    score_dimensions: list[str] = Field(
        default_factory=lambda: ["success", "purpose", "action"]
    )
    temperature: float = Field(default=0, ge=0, le=2)


class CreateEvalJobRequest(BaseModel):
    name: str
    dataset_id: int
    training_job_id: int | None = None
    llm_provider: str | None = None
    model_ref: str | None = None
    config: EvalConfig = Field(default_factory=EvalConfig)


class EvalSampleResult(BaseModel):
    sample_id: int
    source_run_uuid: str
    source_step_order: int
    golden_success: bool | None = None
    predicted_success: bool | None = None
    golden_purpose: str | None = None
    predicted_purpose: str | None = None
    success_match: bool | None = None
    purpose_score: float | None = None
    overall_score: float | None = None
    reasoning: str | None = None


class FlywheelEvalJobResponse(BaseModel):
    id: int
    job_uuid: str
    name: str
    dataset_id: int
    training_job_id: int | None = None
    llm_provider: str | None = None
    model_ref: str | None = None
    status: JobStatus
    config: EvalConfig | None = None
    progress_pct: float = 0.0
    current_stage: str | None = None
    results: dict | None = None
    sample_results: list[EvalSampleResult] = Field(default_factory=list)
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class FlywheelEvalJobListResponse(BaseModel):
    items: list[FlywheelEvalJobResponse]
