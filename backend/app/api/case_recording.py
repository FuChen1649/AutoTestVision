from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.case_recording_service.repository import recording_session_dir
from app.case_recording_service.schemas import (
    ConfirmRecordingRequest,
    ConfirmRecordingResponse,
    CreateRecordingSessionRequest,
    ProvidersResponse,
    RecordActionRequest,
    RecordingLogsResponse,
    RecordingLogItem,
    RecordingSessionResponse,
)
from app.case_recording_service.service import case_recording_service
from app.database import get_db

router = APIRouter(prefix="/case-recording", tags=["case-recording"])


@router.get("/providers", response_model=ProvidersResponse)
async def list_providers() -> ProvidersResponse:
    return await case_recording_service.get_providers()


@router.post("/sessions", response_model=RecordingSessionResponse, status_code=201)
async def create_session(
    payload: CreateRecordingSessionRequest, db: AsyncSession = Depends(get_db)
) -> RecordingSessionResponse:
    return await case_recording_service.create_session(payload, db)


@router.get("/sessions/{session_uuid}", response_model=RecordingSessionResponse)
async def get_session(session_uuid: str, db: AsyncSession = Depends(get_db)) -> RecordingSessionResponse:
    session = await case_recording_service.get_session(db, session_uuid)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.get("/sessions/{session_uuid}/logs", response_model=RecordingLogsResponse)
async def get_session_logs(
    session_uuid: str,
    after_id: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> RecordingLogsResponse:
    logs = await case_recording_service.get_logs(db, session_uuid, after_id=after_id)
    if not logs:
        raise HTTPException(status_code=404, detail="会话不存在")
    return logs


@router.post("/sessions/{session_uuid}/actions", response_model=RecordingSessionResponse)
async def record_action(
    session_uuid: str,
    payload: RecordActionRequest,
    db: AsyncSession = Depends(get_db),
) -> RecordingSessionResponse:
    try:
        return await case_recording_service.record_action(db, session_uuid, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/sessions/{session_uuid}/stop", response_model=RecordingSessionResponse)
async def stop_recording(
    session_uuid: str, db: AsyncSession = Depends(get_db)
) -> RecordingSessionResponse:
    try:
        return await case_recording_service.stop_recording(db, session_uuid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sessions/{session_uuid}/confirm", response_model=ConfirmRecordingResponse)
async def confirm_recording(
    session_uuid: str,
    payload: ConfirmRecordingRequest,
    db: AsyncSession = Depends(get_db),
) -> ConfirmRecordingResponse:
    try:
        return await case_recording_service.confirm_save(db, session_uuid, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sessions/{session_uuid}/cancel", status_code=204)
async def cancel_session(session_uuid: str, db: AsyncSession = Depends(get_db)) -> None:
    cancelled = await case_recording_service.cancel_session(db, session_uuid)
    if not cancelled:
        raise HTTPException(status_code=404, detail="会话不存在")


@router.delete("/sessions/{session_uuid}", status_code=204)
async def delete_session(session_uuid: str, db: AsyncSession = Depends(get_db)) -> None:
    deleted = await case_recording_service.delete_session(db, session_uuid)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在")


@router.get("/sessions/{session_uuid}/assets/{filename}")
async def get_asset(session_uuid: str, filename: str) -> FileResponse:
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    path = recording_session_dir(session_uuid) / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="资源不存在")
    media = "application/xml" if safe_name.endswith(".xml") else "image/png"
    return FileResponse(path=path, media_type=media, filename=safe_name)
