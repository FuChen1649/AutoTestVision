from pydantic import BaseModel, Field

from app.agent_test_code_service.schemas import CodeBatchStateResponse
from app.agent_test_service.schemas import BatchStateResponse


class UnifiedBatchRequest(BaseModel):
    case_ids: list[int] = Field(min_length=1)
    exec_mode: str = Field(default="position", pattern="^(position|code|dual)$")
    serial: str | None = None
    llm_provider: str | None = None
    enable_verifier: bool = False


class UnifiedBatchResponse(BaseModel):
    exec_mode: str
    task_uuid: str | None = None
    position_batch: BatchStateResponse | None = None
    code_batch: CodeBatchStateResponse | None = None
