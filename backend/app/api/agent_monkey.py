from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_monkey_service.repository import monkey_repository, monkey_session_dir
from app.agent_monkey_service.schemas import (
    CreateMonkeySessionRequest,
    MonkeyExploreStateResponse,
    MonkeySessionResponse,
    MonkeyTreeResponse,
    ProvidersResponse,
)
from app.agent_monkey_service.service import agent_monkey_service
from app.database import get_db

router = APIRouter(prefix="/agent-monkey", tags=["agent-monkey"])


@router.get("/providers", response_model=ProvidersResponse)
async def list_providers() -> ProvidersResponse:
    return await agent_monkey_service.get_providers()


@router.post("/sessions", response_model=MonkeySessionResponse, status_code=201)
async def create_session(
    payload: CreateMonkeySessionRequest, db: AsyncSession = Depends(get_db)
) -> MonkeySessionResponse:
    return await agent_monkey_service.create_session(payload, db)


@router.get("/sessions", response_model=list[MonkeySessionResponse])
async def list_sessions(
    limit: int = Query(default=20, ge=1, le=100), db: AsyncSession = Depends(get_db)
) -> list[MonkeySessionResponse]:
    return await agent_monkey_service.list_sessions(db, limit=limit)


@router.get("/sessions/{session_uuid}", response_model=MonkeySessionResponse)
async def get_session(session_uuid: str, db: AsyncSession = Depends(get_db)) -> MonkeySessionResponse:
    session = await agent_monkey_service.get_session(db, session_uuid)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.get("/sessions/{session_uuid}/tree", response_model=MonkeyTreeResponse)
async def get_tree(session_uuid: str, db: AsyncSession = Depends(get_db)) -> MonkeyTreeResponse:
    tree = await agent_monkey_service.get_tree(db, session_uuid)
    if not tree:
        raise HTTPException(status_code=404, detail="会话不存在")
    return tree


@router.get("/sessions/{session_uuid}/state", response_model=MonkeyExploreStateResponse)
async def get_explore_state(
    session_uuid: str, db: AsyncSession = Depends(get_db)
) -> MonkeyExploreStateResponse:
    state = await agent_monkey_service.get_explore_state(db, session_uuid)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")
    return state


@router.post("/sessions/{session_uuid}/start")
async def start_explore(session_uuid: str, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    session = await agent_monkey_service.get_session(db, session_uuid)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.status == "running":
        raise HTTPException(status_code=400, detail="会话已在运行")
    return StreamingResponse(
        agent_monkey_service.stream_explore(db, session_uuid),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_uuid}/stop", status_code=204)
async def stop_session(session_uuid: str, db: AsyncSession = Depends(get_db)) -> None:
    stopped = await agent_monkey_service.stop_session(db, session_uuid)
    if not stopped:
        raise HTTPException(status_code=404, detail="会话不存在")


@router.delete("/sessions/{session_uuid}", status_code=204)
async def delete_session(session_uuid: str, db: AsyncSession = Depends(get_db)) -> None:
    deleted = await agent_monkey_service.delete_session(db, session_uuid)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在")


@router.get("/sessions/{session_uuid}/screenshots/{filename}")
async def get_screenshot(session_uuid: str, filename: str) -> FileResponse:
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    path = monkey_session_dir(session_uuid) / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="截图不存在")
    return FileResponse(path=path, media_type="image/png", filename=safe_name)
