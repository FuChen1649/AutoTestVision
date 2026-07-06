from datetime import datetime

from pydantic import BaseModel


class LogEntryResponse(BaseModel):
    id: int
    source: str
    run_uuid: str | None = None
    session_uuid: str | None = None
    step_order: int | None = None
    agent_type: str
    message: str
    detail: dict | None = None
    created_at: datetime


class LogListResponse(BaseModel):
    items: list[LogEntryResponse]
    total: int
