from datetime import datetime

from pydantic import BaseModel, Field


class TaskProgress(BaseModel):
    completed_steps: int = 0
    total_steps: int = 0
    current_step: int | None = None
    message: str | None = None


class TaskResponse(BaseModel):
    task_uuid: str
    task_type: str
    exec_mode: str | None = None
    source_case_id: int | None = None
    case_name: str | None = None
    ref_uuid: str | None = None
    parent_task_uuid: str | None = None
    status: str
    progress: TaskProgress = Field(default_factory=TaskProgress)
    serial: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    detail_path: str | None = None


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int


class CancelTaskResponse(BaseModel):
    task_uuid: str
    status: str
    message: str
