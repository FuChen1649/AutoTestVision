import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_log import PlatformTaskLog


async def append_platform_task_log(
    db: AsyncSession,
    task_uuid: str,
    message: str,
    *,
    step_order: int | None = None,
    agent_type: str = "system",
    detail: dict | None = None,
    commit: bool = False,
) -> None:
    db.add(
        PlatformTaskLog(
            task_uuid=task_uuid,
            step_order=step_order,
            agent_type=agent_type,
            message=message,
            detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
        )
    )
    if commit:
        await db.commit()
