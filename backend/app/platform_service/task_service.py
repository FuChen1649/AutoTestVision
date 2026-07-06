import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_test_service import batch_registry, run_registry
from app.models.task import PlatformTask
from app.platform_service.repository import task_repository
from app.platform_service.schemas import CancelTaskResponse, TaskListResponse, TaskProgress, TaskResponse


def _progress_from_task(task: PlatformTask) -> TaskProgress:
    if not task.progress_json:
        return TaskProgress()
    try:
        data = json.loads(task.progress_json)
        return TaskProgress.model_validate(data)
    except Exception:
        return TaskProgress()


def _detail_path(task: PlatformTask) -> str | None:
    if task.task_type == "script_generation" and task.source_case_id:
        return f"/agent/generate/{task.source_case_id}"
    if task.task_type == "run":
        if task.exec_mode == "code" and task.ref_uuid:
            return f"/agent/execute/{task.source_case_id}?mode=code&runId={task.ref_uuid}"
        if task.ref_uuid and task.source_case_id:
            return f"/agent/execute/{task.source_case_id}?mode=position&runId={task.ref_uuid}"
    if task.task_type == "batch" and task.ref_uuid:
        return f"/reports?batchId={task.ref_uuid}&mode={task.exec_mode or 'position'}"
    if task.task_type == "verify" and task.ref_uuid:
        return f"/reports?runId={task.ref_uuid}"
    return None


def task_to_response(task: PlatformTask) -> TaskResponse:
    return TaskResponse(
        task_uuid=task.task_uuid,
        task_type=task.task_type,
        exec_mode=task.exec_mode,
        source_case_id=task.source_case_id,
        case_name=task.case_name,
        ref_uuid=task.ref_uuid,
        parent_task_uuid=task.parent_task_uuid,
        status=task.status,
        progress=_progress_from_task(task),
        serial=task.serial,
        error=task.error,
        created_at=task.created_at,
        updated_at=task.updated_at,
        detail_path=_detail_path(task),
    )


async def register_platform_task(
    db: AsyncSession,
    *,
    task_type: str,
    exec_mode: str | None = None,
    source_case_id: int | None = None,
    case_name: str | None = None,
    ref_uuid: str | None = None,
    parent_task_uuid: str | None = None,
    serial: str | None = None,
    status: str = "pending",
    progress: dict | None = None,
    commit: bool = True,
) -> PlatformTask:
    task = await task_repository.create(
        db,
        task_type=task_type,
        exec_mode=exec_mode,
        source_case_id=source_case_id,
        case_name=case_name,
        ref_uuid=ref_uuid,
        parent_task_uuid=parent_task_uuid,
        serial=serial,
        status=status,
        progress=progress,
    )
    if commit:
        await db.commit()
        await db.refresh(task)
    return task


async def sync_task_status(
    db: AsyncSession,
    task_uuid: str,
    *,
    status: str | None = None,
    progress: dict | None = None,
    error: str | None = None,
    ref_uuid: str | None = None,
    commit: bool = True,
) -> PlatformTask | None:
    task = await task_repository.get_by_uuid(db, task_uuid)
    if not task:
        return None
    await task_repository.update_status(
        db, task, status=status, progress=progress, error=error, ref_uuid=ref_uuid
    )
    if commit:
        await db.commit()
        await db.refresh(task)
    return task


class TaskService:
    async def list_tasks(
        self,
        db: AsyncSession,
        *,
        task_type: str | None = None,
        status: str | None = None,
        case_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TaskListResponse:
        tasks, total = await task_repository.list_tasks(
            db,
            task_type=task_type,
            status=status,
            case_id=case_id,
            limit=limit,
            offset=offset,
        )
        return TaskListResponse(items=[task_to_response(t) for t in tasks], total=total)

    async def get_task(self, db: AsyncSession, task_uuid: str) -> TaskResponse | None:
        task = await task_repository.get_by_uuid(db, task_uuid)
        if not task:
            return None
        return task_to_response(task)

    async def cancel_task(self, db: AsyncSession, task_uuid: str) -> CancelTaskResponse:
        task = await task_repository.get_by_uuid(db, task_uuid)
        if not task:
            raise RuntimeError("任务不存在")
        if task.status in ("completed", "failed", "cancelled"):
            return CancelTaskResponse(task_uuid=task_uuid, status=task.status, message="任务已结束")

        if task.task_type == "run" and task.ref_uuid:
            if task.exec_mode == "code":
                from app.agent_test_code_service.run_registry import request_cancel as code_cancel

                code_cancel(task.ref_uuid)
            else:
                run_registry.request_cancel(task.ref_uuid)
        elif task.task_type == "batch" and task.ref_uuid:
            if task.exec_mode == "code":
                from app.agent_test_code_service import batch_registry as code_batch_registry

                code_batch_registry.request_cancel(task.ref_uuid)
            else:
                batch_registry.request_cancel(task.ref_uuid)
        elif task.task_type == "script_generation" and task.ref_uuid:
            from app.script_generation_service.registry import script_gen_registry

            script_gen_registry.cancel(task.ref_uuid)

        await task_repository.update_status(db, task, status="cancelled")
        await db.commit()
        return CancelTaskResponse(task_uuid=task_uuid, status="cancelled", message="已请求取消")


task_service = TaskService()
