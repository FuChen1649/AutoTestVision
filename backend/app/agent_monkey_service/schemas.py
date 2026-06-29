from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

NodeType = Literal["root", "screen", "app", "element", "container"]
NodeStatus = Literal["discovered", "explored", "exploring", "skipped", "failed"]
SessionStatus = Literal["idle", "running", "stopped", "completed", "failed"]


class BBox(BaseModel):
    x: int
    y: int
    w: int
    h: int


class Center(BaseModel):
    x: int
    y: int


ActionStatus = Literal["pending", "executed", "failed", "skipped", "no_effect"]


class MonkeyScreenActionResponse(BaseModel):
    action_uuid: str
    screen_node_uuid: str
    action_no: int
    element_title: str
    action_type: str
    bbox: BBox | None = None
    center: Center | None = None
    data_dependency: str | None = None
    status: ActionStatus
    result_screen_uuid: str | None = None
    element_node_uuid: str | None = None
    step_index: int | None = None
    created_at: datetime
    updated_at: datetime


class MonkeyNodeResponse(BaseModel):
    node_uuid: str
    parent_node_uuid: str | None
    node_type: NodeType
    title: str
    description: str | None = None
    screenshot_url: str | None = None
    annotated_screenshot_url: str | None = None
    bbox: BBox | None = None
    center: Center | None = None
    screen_width: int | None = None
    screen_height: int | None = None
    screen_fingerprint: str | None = None
    status: NodeStatus
    depth: int
    confidence: float = 0.0
    created_at: datetime
    updated_at: datetime


class MonkeyActionRecordResponse(BaseModel):
    step_index: int
    tool_name: str
    node_uuid: str | None = None
    x: int | None = None
    y: int | None = None
    title: str | None = None
    result: str
    created_at: datetime


class MonkeyLogItem(BaseModel):
    id: int
    step_index: int | None = None
    log_type: str
    message: str
    detail: dict | None = None
    created_at: datetime


class MonkeySessionResponse(BaseModel):
    session_uuid: str
    serial: str | None
    target_app_name: str
    status: SessionStatus
    llm_provider: str | None = None
    step_count: int
    max_steps: int
    max_depth: int
    current_node_uuid: str | None = None
    focus_screen_uuid: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class MonkeyExploreStateResponse(BaseModel):
    session_uuid: str
    session: MonkeySessionResponse
    screens: list[MonkeyNodeResponse] = Field(default_factory=list)
    tree_nodes: list[MonkeyNodeResponse] = Field(default_factory=list)
    actions: list[MonkeyScreenActionResponse] = Field(default_factory=list)
    logs: list[MonkeyLogItem] = Field(default_factory=list)


class MonkeyLogsResponse(BaseModel):
    session_uuid: str
    logs: list[MonkeyLogItem] = Field(default_factory=list)
    latest_id: int = 0


class MonkeyTreeResponse(BaseModel):
    session_uuid: str
    nodes: list[MonkeyNodeResponse] = Field(default_factory=list)


class CreateMonkeySessionRequest(BaseModel):
    target_app_name: str = Field(min_length=1, max_length=120)
    serial: str | None = None
    llm_provider: str | None = None
    max_steps: int = Field(default=0, ge=0, description="0 表示不限制探索步数")
    max_depth: int = Field(default=6, ge=1, le=12)


class MonkeyStreamEvent(BaseModel):
    type: str
    session: MonkeySessionResponse | None = None
    nodes: list[MonkeyNodeResponse] = Field(default_factory=list)
    actions: list[MonkeyScreenActionResponse] = Field(default_factory=list)
    screens: list[MonkeyNodeResponse] = Field(default_factory=list)
    logs: list[MonkeyLogItem] = Field(default_factory=list)
    message: str | None = None


class ProviderInfo(BaseModel):
    id: str
    label: str
    model: str
    base_url: str
    available: bool


class ProvidersResponse(BaseModel):
    providers: list[ProviderInfo] = Field(default_factory=list)
    default: str | None = None
