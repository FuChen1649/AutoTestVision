from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.agent_test_service.schemas import (
    AgentLogItem,
    AgentLogsResponse,
    CaseListItem,
    ProviderInfo,
    ProvidersResponse,
    RunStatus,
    StepPurposeReviewRecord,
    VerificationResult,
)


class GeneratedStepCode(BaseModel):
    code_line: str = ""
    confidence: float = Field(ge=0, le=1, default=0.0)
    reasoning: str = ""
    template_path: str | None = None
    execution_output: str | None = None
    pytest_exit_code: int | None = None


class CodeStepExecutionRecord(BaseModel):
    step_order: int
    step_type: str
    description: str
    status: Literal["pending", "running", "success", "failed", "skipped"] = "pending"
    generated_code: GeneratedStepCode | None = None
    verification: VerificationResult | None = None
    before_image: str | None = None
    before_image_annotated: str | None = None
    after_image: str | None = None
    ui_xml_preview: str | None = None
    reference_image: str | None = None
    reference_x: int | None = None
    reference_y: int | None = None
    reference_width: int | None = None
    reference_height: int | None = None
    error: str | None = None
    metadata: dict | None = None
    purpose_review: StepPurposeReviewRecord | None = None


class AnalyzeCodeRequest(BaseModel):
    step_description: str
    screen_image: str
    screen_width: int = Field(gt=0)
    screen_height: int = Field(gt=0)
    ui_xml: str = ""
    llm_provider: str | None = None


class StartCodeRunRequest(BaseModel):
    case_id: int
    serial: str | None = None
    auto_run: bool = False
    max_retries: int = Field(default=1, ge=0, le=3)
    llm_provider: str | None = None
    enable_verifier: bool = False


class CodeRunStateResponse(BaseModel):
    run_id: str
    case_id: int
    case_name: str
    script_content: str = ""
    serial: str | None
    status: RunStatus
    current_step_index: int
    total_steps: int
    retry_count: int
    max_retries: int
    error: str | None = None
    llm_provider: str | None = None
    enable_verifier: bool = False
    steps: list[CodeStepExecutionRecord] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CodeStepAdvanceResponse(BaseModel):
    run: CodeRunStateResponse
    finished: bool
    message: str


class CodeStreamEvent(BaseModel):
    type: str
    run: CodeRunStateResponse | None = None
    message: str | None = None
    logs: list[AgentLogItem] | None = None


class StartCodeBatchRequest(BaseModel):
    case_ids: list[int] = Field(min_length=1)
    serial: str | None = None
    llm_provider: str | None = None
    enable_verifier: bool = False
    max_retries: int = Field(default=1, ge=0, le=3)


class CodeBatchListItem(BaseModel):
    batch_id: str
    status: str
    case_count: int
    llm_provider: str | None = None
    created_at: datetime
    updated_at: datetime


class CodeBatchStateResponse(BaseModel):
    batch_id: str
    status: str
    llm_provider: str | None = None
    enable_verifier: bool = False
    results: list[dict] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


__all__ = [
    "GeneratedStepCode",
    "CodeStepExecutionRecord",
    "AnalyzeCodeRequest",
    "StartCodeRunRequest",
    "CodeRunStateResponse",
    "CodeStepAdvanceResponse",
    "CodeStreamEvent",
    "StartCodeBatchRequest",
    "CodeBatchListItem",
    "CodeBatchStateResponse",
    "AgentLogItem",
    "AgentLogsResponse",
    "CaseListItem",
    "ProviderInfo",
    "ProvidersResponse",
]
