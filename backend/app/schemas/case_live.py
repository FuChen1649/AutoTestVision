from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.case import CaseResponse, CaseStepCreate

AgentLiveMode = Literal["position", "code"]


class LiveStepExecuteRequest(BaseModel):
    """自然语言 Case 编写时提交单步并触发 AgentTest 执行。"""

    case_id: int | None = None
    case_name: str = "未命名 Case"
    script_content: str = ""
    steps: list[CaseStepCreate] = Field(default_factory=list)
    commit_step_index: int = Field(ge=0, description="本次确认执行的步骤下标（含）")
    agent_mode: AgentLiveMode = "position"
    run_id: str | None = None
    serial: str | None = None
    llm_provider: str | None = None
    enable_verifier: bool = False
    max_retries: int = Field(default=1, ge=0, le=3)


class LiveStepExecuteResponse(BaseModel):
    case: CaseResponse
    run_id: str
    agent_mode: AgentLiveMode
    run: dict[str, Any]
    finished: bool
    message: str
