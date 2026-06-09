import asyncio
import uuid
from copy import deepcopy
from datetime import datetime

from app.agent_test_service.schemas import RunStateResponse, RunStatus, StepExecutionRecord
from app.agent_test_service.state import HarnessAgentState, utc_now


class StateManager:
    def __init__(self) -> None:
        self._runs: dict[str, HarnessAgentState] = {}
        self._lock = asyncio.Lock()

    async def create_run(
        self,
        case_id: int,
        case_name: str,
        steps: list[StepExecutionRecord],
        serial: str | None,
        max_retries: int,
    ) -> HarnessAgentState:
        run_id = str(uuid.uuid4())
        now = utc_now()
        state: HarnessAgentState = {
            "run_id": run_id,
            "case_id": case_id,
            "case_name": case_name,
            "serial": serial,
            "status": "pending",
            "current_step_index": 0,
            "total_steps": len(steps),
            "retry_count": 0,
            "max_retries": max_retries,
            "error": None,
            "steps": steps,
            "should_continue": True,
            "created_at": now,
            "updated_at": now,
        }
        async with self._lock:
            self._runs[run_id] = state
        return deepcopy(state)

    async def get_run(self, run_id: str) -> HarnessAgentState | None:
        async with self._lock:
            state = self._runs.get(run_id)
            return deepcopy(state) if state else None

    async def save_run(self, state: HarnessAgentState) -> HarnessAgentState:
        state["updated_at"] = utc_now()
        async with self._lock:
            self._runs[state["run_id"]] = deepcopy(state)
        return deepcopy(state)

    async def update_status(self, run_id: str, status: RunStatus, error: str | None = None) -> None:
        async with self._lock:
            state = self._runs.get(run_id)
            if not state:
                return
            state["status"] = status
            state["error"] = error
            state["updated_at"] = utc_now()

    async def delete_run(self, run_id: str) -> bool:
        async with self._lock:
            return self._runs.pop(run_id, None) is not None

    def to_response(self, state: HarnessAgentState) -> RunStateResponse:
        return RunStateResponse(
            run_id=state["run_id"],
            case_id=state["case_id"],
            case_name=state["case_name"],
            serial=state.get("serial"),
            status=state.get("status", "pending"),
            current_step_index=state.get("current_step_index", 0),
            total_steps=state.get("total_steps", 0),
            retry_count=state.get("retry_count", 0),
            max_retries=state.get("max_retries", 1),
            error=state.get("error"),
            steps=state.get("steps", []),
            created_at=state.get("created_at", utc_now()),
            updated_at=state.get("updated_at", utc_now()),
        )


state_manager = StateManager()
