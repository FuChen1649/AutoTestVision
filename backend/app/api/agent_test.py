from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.schemas import (
    ActionIntent,
    AgentLogsResponse,
    AnalyzeIntentRequest,
    CaseListItem,
    RunStateResponse,
    StartRunRequest,
    StepAdvanceResponse,
)
from app.agent_test_service.service import agent_test_service
from app.database import get_db

router = APIRouter(prefix="/agent-test", tags=["agent-test"])
logger = get_agent_logger()


@router.get("/cases", response_model=list[CaseListItem])
async def list_cases_for_agent(
    limit: int = Query(default=10, ge=1, le=50), db: AsyncSession = Depends(get_db)
) -> list[CaseListItem]:
    logger.info("[api] GET /agent-test/cases limit=%d", limit)
    return await agent_test_service.list_cases(db, limit=limit)


@router.post("/analyze", response_model=ActionIntent)
async def analyze_intent(payload: AnalyzeIntentRequest) -> ActionIntent:
    logger.info("[api] POST /agent-test/analyze")
    try:
        return await agent_test_service.analyze_intent(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs", response_model=RunStateResponse, status_code=201)
async def start_run(
    payload: StartRunRequest, db: AsyncSession = Depends(get_db)
) -> RunStateResponse:
    logger.info("[api] POST /agent-test/runs case_id=%d", payload.case_id)
    try:
        return await agent_test_service.start_run(payload, db)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=RunStateResponse)
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)) -> RunStateResponse:
    run = await agent_test_service.get_run(run_id, db)
    if not run:
        raise HTTPException(status_code=404, detail="运行实例不存在")
    return run


@router.get("/runs/{run_id}/logs", response_model=AgentLogsResponse)
async def get_run_logs(
    run_id: str,
    agent_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> AgentLogsResponse:
    try:
        return await agent_test_service.get_logs(run_id, db, agent_type=agent_type)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    logger.info("[api] GET /agent-test/runs/%s/stream", run_id)
    try:
        return StreamingResponse(
            agent_test_service.stream_run(run_id, db),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/step", response_model=StepAdvanceResponse)
async def advance_one_step(run_id: str, db: AsyncSession = Depends(get_db)) -> StepAdvanceResponse:
    try:
        return await agent_test_service.advance_step(run_id, db)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/runs/{run_id}", status_code=204)
async def cancel_run(run_id: str, db: AsyncSession = Depends(get_db)) -> None:
    cancelled = await agent_test_service.cancel_run(run_id, db)
    if not cancelled:
        raise HTTPException(status_code=404, detail="运行实例不存在")
