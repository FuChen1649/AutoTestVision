from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.platform_service.schemas import CancelTaskResponse, TaskListResponse, TaskResponse
from app.platform_service.task_service import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    task_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    case_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> TaskListResponse:
    return await task_service.list_tasks(
        db,
        task_type=task_type,
        status=status,
        case_id=case_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{task_uuid}", response_model=TaskResponse)
async def get_task(task_uuid: str, db: AsyncSession = Depends(get_db)) -> TaskResponse:
    task = await task_service.get_task(db, task_uuid)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.post("/{task_uuid}/cancel", response_model=CancelTaskResponse)
async def cancel_task(task_uuid: str, db: AsyncSession = Depends(get_db)) -> CancelTaskResponse:
    try:
        return await task_service.cancel_task(db, task_uuid)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
