import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.script_generation_service.service import (
    GenerateScriptsRequest,
    GenerateScriptsResponse,
    CaseScriptsResponse,
    ScriptGenPrerequisitesResponse,
    script_generation_service,
)

router = APIRouter(tags=["script-generation"])


def _sse_payload(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/script-generation/prerequisites", response_model=ScriptGenPrerequisitesResponse)
async def get_script_generation_prerequisites(
    position_serial: str | None = Query(default=None),
    code_serial: str | None = Query(default=None),
) -> ScriptGenPrerequisitesResponse:
    return script_generation_service.get_prerequisites(position_serial, code_serial)


@router.get("/cases/{case_id}/scripts", response_model=CaseScriptsResponse)
async def get_case_scripts(case_id: int, db: AsyncSession = Depends(get_db)) -> CaseScriptsResponse:
    try:
        return await script_generation_service.get_case_scripts(db, case_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/cases/{case_id}/generate-scripts", response_model=GenerateScriptsResponse)
async def start_generate_scripts(
    case_id: int,
    payload: GenerateScriptsRequest,
    db: AsyncSession = Depends(get_db),
) -> GenerateScriptsResponse:
    try:
        return await script_generation_service.start_generation(db, case_id, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/script-generation/{task_uuid}/stream")
async def stream_script_generation(task_uuid: str):
    async def event_generator():
        async for event in script_generation_service.stream(task_uuid):
            yield _sse_payload(event.model_dump(mode="json"))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
