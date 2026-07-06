from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_test_code_service.schemas import StartCodeBatchRequest
from app.agent_test_code_service.service import agent_test_code_service
from app.agent_test_service.schemas import StartBatchRequest
from app.agent_test_service.service import agent_test_service
from app.api.batch_schemas import UnifiedBatchRequest, UnifiedBatchResponse
from app.database import get_db
from app.platform_service.task_service import register_platform_task, sync_task_status

router = APIRouter(prefix="/batch", tags=["batch"])


@router.post("", response_model=UnifiedBatchResponse)
async def start_unified_batch(
    payload: UnifiedBatchRequest,
    db: AsyncSession = Depends(get_db),
) -> UnifiedBatchResponse:
    parent_task = await register_platform_task(
        db,
        task_type="batch",
        exec_mode=payload.exec_mode,
        serial=payload.serial,
        status="running",
        progress={"total_cases": len(payload.case_ids), "message": "批量任务启动中"},
        commit=True,
    )

    response = UnifiedBatchResponse(exec_mode=payload.exec_mode, task_uuid=parent_task.task_uuid)

    try:
        if payload.exec_mode in ("position", "dual"):
            pos_batch = await agent_test_service.start_batch(
                StartBatchRequest(
                    case_ids=payload.case_ids,
                    serial=payload.serial,
                    llm_provider=payload.llm_provider,
                    enable_verifier=payload.enable_verifier,
                ),
                db,
            )
            response.position_batch = pos_batch
            await register_platform_task(
                db,
                task_type="batch",
                exec_mode="position",
                ref_uuid=pos_batch.batch_id,
                parent_task_uuid=parent_task.task_uuid,
                serial=payload.serial,
                status=pos_batch.status,
                progress={
                    "total_cases": pos_batch.total_cases,
                    "completed_cases": pos_batch.completed_cases,
                },
                commit=True,
            )

        if payload.exec_mode in ("code", "dual"):
            code_batch = await agent_test_code_service.start_batch(
                StartCodeBatchRequest(
                    case_ids=payload.case_ids,
                    serial=payload.serial,
                    llm_provider=payload.llm_provider,
                    enable_verifier=payload.enable_verifier,
                ),
                db,
            )
            response.code_batch = code_batch
            await register_platform_task(
                db,
                task_type="batch",
                exec_mode="code",
                ref_uuid=code_batch.batch_id,
                parent_task_uuid=parent_task.task_uuid,
                serial=payload.serial,
                status=code_batch.status,
                progress={
                    "total_cases": len(payload.case_ids),
                    "completed_cases": len(code_batch.results),
                },
                commit=True,
            )

        ref_uuid = None
        if response.position_batch:
            ref_uuid = response.position_batch.batch_id
        elif response.code_batch:
            ref_uuid = response.code_batch.batch_id

        await sync_task_status(
            db,
            parent_task.task_uuid,
            status="running",
            ref_uuid=ref_uuid,
            progress={"total_cases": len(payload.case_ids), "message": "批量任务已启动"},
            commit=True,
        )
        return response
    except Exception as exc:
        await sync_task_status(db, parent_task.task_uuid, status="failed", error=str(exc), commit=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
