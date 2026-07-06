from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.report_service.schemas import ReportDetailResponse, ReportListResponse
from app.report_service.service import report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=ReportListResponse)
async def list_reports(
    exec_mode: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ReportListResponse:
    return await report_service.list_reports(db, exec_mode=exec_mode, limit=limit, offset=offset)


@router.get("/{report_id}", response_model=ReportDetailResponse)
async def get_report(
    report_id: str,
    exec_mode: str = Query(default="position"),
    db: AsyncSession = Depends(get_db),
) -> ReportDetailResponse:
    report = await report_service.get_report(db, report_id, exec_mode=exec_mode)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    return report


@router.get("/runs/{run_uuid}")
async def get_run_report(
    run_uuid: str,
    exec_mode: str = Query(default="position"),
    db: AsyncSession = Depends(get_db),
):
    report = await report_service.get_run_report(db, run_uuid, exec_mode=exec_mode)
    if not report:
        raise HTTPException(status_code=404, detail="运行报告不存在")
    return report
