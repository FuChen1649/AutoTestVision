from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ActionType = Literal["tap", "swipe", "long_press", "skip"]
RunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class ActionIntent(BaseModel):
    action: ActionType
    x: int | None = None
    y: int | None = None
    x2: int | None = None
    y2: int | None = None
    duration_ms: int = 300
    confidence: float = Field(ge=0, le=1, default=0.0)
    reasoning: str = ""


class VerificationResult(BaseModel):
    success: bool
    confidence: float = Field(ge=0, le=1, default=0.0)
    reasoning: str = ""


class StepAttemptRecord(BaseModel):
    step_order: int
    attempt_index: int
    before_image: str | None = None
    before_image_annotated: str | None = None
    after_image: str | None = None
    status: str = "running"
    error: str | None = None
    step_type: str | None = None
    intent: ActionIntent | None = None
    metadata: dict | None = None


class StepExecutionRecord(BaseModel):
    step_order: int
    step_type: str
    description: str
    status: Literal["pending", "running", "success", "failed", "skipped"] = "pending"
    intent: ActionIntent | None = None
    verification: VerificationResult | None = None
    before_image: str | None = None
    before_image_annotated: str | None = None
    after_image: str | None = None
    reference_image: str | None = None
    reference_x: int | None = None
    reference_y: int | None = None
    reference_width: int | None = None
    reference_height: int | None = None
    error: str | None = None
    metadata: dict | None = None


class AnalyzeIntentRequest(BaseModel):
    step_description: str
    screen_image: str
    screen_width: int = Field(gt=0)
    screen_height: int = Field(gt=0)
    reference_image: str | None = None
    reference_x: int | None = None
    reference_y: int | None = None
    reference_width: int | None = None
    reference_height: int | None = None
    llm_provider: str | None = None


class StartRunRequest(BaseModel):
    case_id: int
    serial: str | None = None
    auto_run: bool = False
    max_retries: int = Field(default=1, ge=0, le=3)
    llm_provider: str | None = None
    enable_verifier: bool = False


class RunStateResponse(BaseModel):
    run_id: str
    case_id: int
    case_name: str
    serial: str | None
    status: RunStatus
    current_step_index: int
    total_steps: int
    retry_count: int
    max_retries: int
    error: str | None = None
    llm_provider: str | None = None
    enable_verifier: bool = False
    steps: list[StepExecutionRecord] = Field(default_factory=list)
    attempts: list[StepAttemptRecord] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ProviderInfo(BaseModel):
    id: str
    label: str
    model: str
    base_url: str
    available: bool


class ProvidersResponse(BaseModel):
    providers: list[ProviderInfo] = Field(default_factory=list)
    default: str | None = None


class StepAdvanceResponse(BaseModel):
    run: RunStateResponse
    finished: bool
    message: str


class AgentLogItem(BaseModel):
    id: int
    step_order: int | None
    agent_type: str
    message: str
    detail: dict | None = None
    created_at: datetime


class AgentLogsResponse(BaseModel):
    run_id: str
    logs: list[AgentLogItem] = Field(default_factory=list)


class CaseListItem(BaseModel):
    id: int
    name: str
    step_count: int
    updated_at: datetime


class StreamEvent(BaseModel):
    type: str
    node: str | None = None
    run: RunStateResponse | None = None
    logs: list[AgentLogItem] = Field(default_factory=list)
    message: str | None = None


class DeviceReplayStreamEvent(BaseModel):
    type: Literal["start", "recover", "step", "wait", "done", "error"]
    message: str | None = None
    step_order: int | None = None
    step_index: int | None = None
    total_steps: int | None = None
    action: str | None = None
