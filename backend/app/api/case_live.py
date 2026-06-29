from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.case_live_service.service import case_live_service
from app.database import get_db
from app.schemas.case_live import LiveStepExecuteRequest, LiveStepExecuteResponse

router = APIRouter(prefix="/cases/live", tags=["cases-live"])


@router.post("/execute-step", response_model=LiveStepExecuteResponse)
async def execute_live_step(
    payload: LiveStepExecuteRequest, db: AsyncSession = Depends(get_db)
) -> LiveStepExecuteResponse:
    try:
        return await case_live_service.execute_step(payload, db)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
