from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.log_service.schemas import LogListResponse
from app.log_service.service import log_service

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=LogListResponse)
async def list_logs(
    source: str | None = Query(default=None),
    run_uuid: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> LogListResponse:
    return await log_service.list_logs(
        db, source=source, run_uuid=run_uuid, limit=limit, offset=offset
    )
