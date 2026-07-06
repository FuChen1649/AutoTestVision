import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.case import Case, CaseStep
from app.platform_service.repository import case_query_repository
from app.schemas.case import (
    CaseCreate,
    CaseListItemResponse,
    CaseListPageResponse,
    CaseResponse,
    CaseUpdate,
)

router = APIRouter(prefix="/cases", tags=["cases"])


def _build_step(step, index: int) -> CaseStep:
    metadata_json = None
    if step.metadata_json:
        metadata_json = json.dumps(step.metadata_json, ensure_ascii=False)
    return CaseStep(
        description=step.description,
        step_order=step.step_order or index,
        step_type=step.step_type,
        screen_image=step.screen_image,
        screen_width=step.screen_width,
        screen_height=step.screen_height,
        selection_x=step.selection_x,
        selection_y=step.selection_y,
        selection_width=step.selection_width,
        selection_height=step.selection_height,
        metadata_json=metadata_json,
    )


@router.get("", response_model=CaseListPageResponse)
async def list_cases(
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> CaseListPageResponse:
    cases, total = await case_query_repository.list_cases_paginated(db, q=q, page=page, size=size)
    items: list[CaseListItemResponse] = []
    for case in cases:
        last_run_status = await case_query_repository.last_run_status(db, case.id)
        script_status = case_query_repository.aggregate_script_status(case)
        items.append(
            CaseListItemResponse(
                id=case.id,
                name=case.name,
                script_content=case.script_content,
                step_count=len(case.steps),
                script_status=script_status,
                last_run_status=last_run_status,
                created_at=case.created_at,
                updated_at=case.updated_at,
            )
        )
    return CaseListPageResponse(items=items, total=total, page=page, size=size)


@router.post("", response_model=CaseResponse, status_code=201)
async def create_case(payload: CaseCreate, db: AsyncSession = Depends(get_db)) -> Case:
    case = Case(name=payload.name, script_content=payload.script_content)
    for index, step in enumerate(payload.steps):
        case.steps.append(_build_step(step, index))

    db.add(case)
    await db.commit()
    await db.refresh(case, attribute_names=["steps"])
    return case


@router.get("/{case_id}", response_model=CaseResponse)
async def get_case(case_id: int, db: AsyncSession = Depends(get_db)) -> Case:
    result = await db.execute(select(Case).options(selectinload(Case.steps)).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case 不存在")
    return case


@router.put("/{case_id}", response_model=CaseResponse)
async def update_case(case_id: int, payload: CaseUpdate, db: AsyncSession = Depends(get_db)) -> Case:
    result = await db.execute(select(Case).options(selectinload(Case.steps)).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case 不存在")

    if payload.name is not None:
        case.name = payload.name
    if payload.script_content is not None:
        case.script_content = payload.script_content
    if payload.steps is not None:
        case.steps.clear()
        for index, step in enumerate(payload.steps):
            case.steps.append(_build_step(step, index))

    await db.commit()
    await db.refresh(case, attribute_names=["steps"])
    return case


@router.delete("/{case_id}", status_code=204)
async def delete_case(case_id: int, db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case 不存在")
    await db.delete(case)
    await db.commit()
