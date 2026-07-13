from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ActionType = Literal["tap", "swipe", "long_press", "key"]
NavKey = Literal["back", "home", "recents"]
SessionStatus = Literal["recording", "generating", "review", "saved", "cancelled", "failed"]


class CreateRecordingSessionRequest(BaseModel):
    serial: str | None = None
    case_name: str = "录制 Case"
    llm_provider: str | None = None


class RecordActionRequest(BaseModel):
    action_type: ActionType
    x: int | None = None
    y: int | None = None
    x2: int | None = None
    y2: int | None = None
    duration_ms: int = 300
    key: NavKey | None = None


class GeneratedStepDraft(BaseModel):
    step_order: int
    description: str
    event_uuid: str
    screen_image_url: str | None = None
    screen_width: int | None = None
    screen_height: int | None = None
    selection_x: int | None = None
    selection_y: int | None = None
    selection_width: int | None = None
    selection_height: int | None = None


class RecordingEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_uuid: str
    step_order: int
    action_type: str
    x: int | None = None
    y: int | None = None
    x2: int | None = None
    y2: int | None = None
    duration_ms: int | None = None
    key_name: str | None = None
    before_image_url: str | None = None
    after_image_url: str | None = None
    device_width: int | None = None
    device_height: int | None = None
    element_hint: str | None = None
    created_at: datetime


class RecordingSessionResponse(BaseModel):
    session_uuid: str
    serial: str | None = None
    case_name: str
    status: SessionStatus
    llm_provider: str | None = None
    event_count: int = 0
    generated_steps: list[GeneratedStepDraft] = Field(default_factory=list)
    saved_case_id: int | None = None
    error: str | None = None
    events: list[RecordingEventResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ConfirmRecordingRequest(BaseModel):
    case_name: str | None = None
    steps: list[GeneratedStepDraft] | None = None


class ConfirmRecordingResponse(BaseModel):
    case_id: int
    case_name: str
    step_count: int


class ProvidersResponse(BaseModel):
    providers: list[dict[str, str | bool]]


class RecordingLogItem(BaseModel):
    id: int
    step_order: int | None = None
    log_type: str
    message: str
    detail: dict | None = None
    created_at: datetime


class RecordingLogsResponse(BaseModel):
    items: list[RecordingLogItem]
    total: int
