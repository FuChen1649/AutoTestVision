from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_test_service.agent_logger import get_agent_logger
from app.database import get_db
from app.result_verify_service.schemas import (
    BatchPurposeReviewResponse,
    DualVerifyResponse,
    RunPurposeReviewResponse,
    VerifyBatchRequest,
    VerifyRunRequest,
)
from app.result_verify_service.service import result_verify_service

router = APIRouter(prefix="/result-verify", tags=["result-verify"])
logger = get_agent_logger()


@router.post("/runs/{run_id}", response_model=RunPurposeReviewResponse)
async def verify_run(
    run_id: str,
    payload: VerifyRunRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> RunPurposeReviewResponse:
    logger.info("[api] POST /result-verify/runs/%s", run_id)
    try:
        return await result_verify_service.verify_run(run_id, db, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}/stream")
async def stream_verify_run(
    run_id: str,
    llm_provider: str | None = Query(default=None),
) -> StreamingResponse:
    logger.info("[api] GET /result-verify/runs/%s/stream", run_id)
    try:
        return StreamingResponse(
            result_verify_service.stream_verify_run(run_id, llm_provider=llm_provider),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=RunPurposeReviewResponse)
async def get_run_reviews(
    run_id: str, db: AsyncSession = Depends(get_db)
) -> RunPurposeReviewResponse:
    try:
        return await result_verify_service.get_run_reviews(run_id, db)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/batches/{batch_id}", response_model=BatchPurposeReviewResponse)
async def verify_batch(
    batch_id: str,
    payload: VerifyBatchRequest | None = None,
    exec_mode: Literal["position", "code"] = Query(default="position"),
    db: AsyncSession = Depends(get_db),
) -> BatchPurposeReviewResponse:
    logger.info("[api] POST /result-verify/batches/%s mode=%s", batch_id, exec_mode)
    try:
        return await result_verify_service.verify_batch(batch_id, db, payload, exec_mode=exec_mode)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/batches/{batch_id}/stream")
async def stream_verify_batch(
    batch_id: str,
    llm_provider: str | None = Query(default=None),
    exec_mode: Literal["position", "code"] = Query(default="position"),
) -> StreamingResponse:
    logger.info("[api] GET /result-verify/batches/%s/stream mode=%s", batch_id, exec_mode)
    try:
        return StreamingResponse(
            result_verify_service.stream_verify_batch(
                batch_id, llm_provider=llm_provider, exec_mode=exec_mode
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/dual/{task_id}", response_model=DualVerifyResponse)
async def verify_dual(
    task_id: str,
    payload: VerifyRunRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> DualVerifyResponse:
    logger.info("[api] POST /result-verify/dual/%s", task_id)
    try:
        return await result_verify_service.verify_dual(task_id, db, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/dual/{task_id}/stream")
async def stream_verify_dual(
    task_id: str,
    llm_provider: str | None = Query(default=None),
) -> StreamingResponse:
    logger.info("[api] GET /result-verify/dual/%s/stream", task_id)
    try:
        return StreamingResponse(
            result_verify_service.stream_verify_dual(task_id, llm_provider=llm_provider),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/dual/{task_id}", response_model=DualVerifyResponse)
async def get_dual_reviews(
    task_id: str, db: AsyncSession = Depends(get_db)
) -> DualVerifyResponse:
    try:
        return await result_verify_service.get_dual_reviews(task_id, db)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
