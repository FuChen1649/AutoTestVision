from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_test_code_service.schemas import (
    AnalyzeCodeRequest,
    CodeBatchListItem,
    CodeBatchStateResponse,
    CodeRunStateResponse,
    CodeStepAdvanceResponse,
    GeneratedStepCode,
    StartCodeBatchRequest,
    StartCodeRunRequest,
)
from app.agent_test_code_service.service import agent_test_code_service
from app.agent_test_service.schemas import CaseListItem, ProvidersResponse
from app.database import get_db

router = APIRouter(prefix="/agent-test-code", tags=["agent-test-code"])


@router.get("/cases", response_model=list[CaseListItem])
async def list_cases(limit: int = Query(default=10, ge=1, le=50), db: AsyncSession = Depends(get_db)):
    return await agent_test_code_service.list_cases(db, limit=limit)


@router.get("/providers", response_model=ProvidersResponse)
async def list_providers():
    return await agent_test_code_service.get_providers()


@router.post("/analyze", response_model=GeneratedStepCode)
async def analyze_code(payload: AnalyzeCodeRequest) -> GeneratedStepCode:
    try:
        return await agent_test_code_service.analyze_code(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs", response_model=CodeRunStateResponse, status_code=201)
async def start_run(payload: StartCodeRunRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_test_code_service.start_run(payload, db)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=CodeRunStateResponse)
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await agent_test_code_service.get_run(run_id, db)
    if not run:
        raise HTTPException(status_code=404, detail="运行实例不存在")
    return run


@router.post("/runs/{run_id}/cancel", response_model=CodeRunStateResponse)
async def cancel_run(run_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_test_code_service.cancel_run(run_id, db)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return StreamingResponse(
            agent_test_code_service.stream_run(run_id, db),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/step", response_model=CodeStepAdvanceResponse)
async def advance_step(run_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_test_code_service.advance_step(run_id, db)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/batches", response_model=CodeBatchStateResponse, status_code=201)
async def start_batch(payload: StartCodeBatchRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_test_code_service.start_batch(payload, db)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/batches", response_model=list[CodeBatchListItem])
async def list_batches(limit: int = Query(default=20, ge=1, le=50), db: AsyncSession = Depends(get_db)):
    return await agent_test_code_service.list_batches(db, limit=limit)


@router.get("/runs/{run_id}/device-replay/stream")
async def stream_device_replay(
    run_id: str,
    step_interval_ms: int = Query(default=3000, ge=0, le=30000),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    try:
        return StreamingResponse(
            agent_test_code_service.stream_device_replay(run_id, db, step_interval_ms=step_interval_ms),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
