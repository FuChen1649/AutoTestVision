from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_test_service.schemas import ActionIntent, VerificationResult
from app.models.agent import AgentRun, AgentRunStep
from app.models.flywheel import (
    FlywheelAnnotation,
    FlywheelDataset,
    FlywheelDatasetItem,
    FlywheelEvalJob,
    FlywheelRagDocument,
    FlywheelSample,
    FlywheelTrainingJob,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_json(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _quality_score(
    *,
    has_before: bool,
    has_after: bool,
    verification: VerificationResult | None,
    purpose: StepPurposeReview | None,
    step_status: str,
) -> float:
    score = 0.0
    if has_before:
        score += 0.25
    if has_after:
        score += 0.25
    if step_status == "success":
        score += 0.2
    if verification and verification.success:
        score += 0.15
    if purpose and purpose.purpose:
        score += 0.1
    if purpose and purpose.confidence >= 0.7:
        score += 0.05
    return round(min(score, 1.0), 3)


class FlywheelRepository:
    async def get_stats(self, db: AsyncSession) -> dict[str, int]:
        total = await db.scalar(select(func.count()).select_from(FlywheelSample)) or 0
        raw = await db.scalar(
            select(func.count()).select_from(FlywheelSample).where(FlywheelSample.cleaning_status == "raw")
        ) or 0
        cleaned = await db.scalar(
            select(func.count())
            .select_from(FlywheelSample)
            .where(FlywheelSample.cleaning_status == "cleaned")
        ) or 0
        rejected = await db.scalar(
            select(func.count())
            .select_from(FlywheelSample)
            .where(FlywheelSample.cleaning_status == "rejected")
        ) or 0
        golden = await db.scalar(
            select(func.count())
            .select_from(FlywheelAnnotation)
            .where(FlywheelAnnotation.is_golden.is_(True))
        ) or 0
        annotated = await db.scalar(select(func.count()).select_from(FlywheelAnnotation)) or 0
        with_images = await db.scalar(
            select(func.count())
            .select_from(FlywheelSample)
            .where(FlywheelSample.has_before_image.is_(True), FlywheelSample.has_after_image.is_(True))
        ) or 0
        return {
            "total_samples": total,
            "raw_count": raw,
            "cleaned_count": cleaned,
            "rejected_count": rejected,
            "golden_count": golden,
            "annotated_count": annotated,
            "with_images_count": with_images,
        }

    async def sync_from_agent_runs(
        self,
        db: AsyncSession,
        *,
        limit_runs: int,
        only_success_steps: bool,
    ) -> tuple[int, int, int]:
        runs_result = await db.execute(
            select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit_runs)
        )
        runs = runs_result.scalars().all()
        created = updated = synced = 0

        for run in runs:
            steps_result = await db.execute(
                select(AgentRunStep)
                .where(AgentRunStep.run_id == run.id)
                .order_by(AgentRunStep.step_order)
            )
            for step in steps_result.scalars().all():
                if only_success_steps and step.status != "success":
                    continue
                if not step.before_image and not step.after_image:
                    continue

                verification = None
                if step.verification_json:
                    try:
                        verification = VerificationResult.model_validate_json(step.verification_json)
                    except Exception:
                        verification = None
                purpose = None
                if step.purpose_review_json:
                    try:
                        raw = json.loads(step.purpose_review_json)
                        purpose_text = raw.get("purpose", "")
                        purpose_conf = float(raw.get("confidence", 0))
                        purpose = type("Purpose", (), {"purpose": purpose_text, "confidence": purpose_conf})()
                    except Exception:
                        purpose = None

                existing = await db.scalar(
                    select(FlywheelSample).where(
                        FlywheelSample.source_run_uuid == run.run_uuid,
                        FlywheelSample.source_step_order == step.step_order,
                    )
                )
                quality = _quality_score(
                    has_before=bool(step.before_image),
                    has_after=bool(step.after_image),
                    verification=verification,
                    purpose=purpose,
                    step_status=step.status,
                )
                payload = {
                    "case_name": run.case_name,
                    "description": step.description,
                    "step_type": step.step_type,
                    "step_status": step.status,
                    "auto_verification_success": verification.success if verification else None,
                    "auto_purpose": purpose.purpose if purpose else None,
                    "auto_confidence": purpose.confidence if purpose else None,
                    "quality_score": quality,
                    "has_before_image": bool(step.before_image),
                    "has_after_image": bool(step.after_image),
                    "synced_at": utc_now(),
                }
                if existing:
                    for key, value in payload.items():
                        setattr(existing, key, value)
                    updated += 1
                else:
                    db.add(
                        FlywheelSample(
                            source_run_uuid=run.run_uuid,
                            source_step_order=step.step_order,
                            cleaning_status="raw",
                            **payload,
                        )
                    )
                    created += 1
                synced += 1
        await db.commit()
        return synced, created, updated

    async def list_samples(
        self,
        db: AsyncSession,
        *,
        cleaning_status: str | None = None,
        golden_only: bool = False,
        min_quality: float | None = None,
        offset: int = 0,
        limit: int = 50,
        include_images: bool = False,
    ) -> tuple[list[FlywheelSample], int]:
        query = select(FlywheelSample).options(selectinload(FlywheelSample.annotation))
        count_query = select(func.count()).select_from(FlywheelSample)

        if cleaning_status:
            query = query.where(FlywheelSample.cleaning_status == cleaning_status)
            count_query = count_query.where(FlywheelSample.cleaning_status == cleaning_status)
        if min_quality is not None:
            query = query.where(FlywheelSample.quality_score >= min_quality)
            count_query = count_query.where(FlywheelSample.quality_score >= min_quality)
        if golden_only:
            query = query.join(FlywheelAnnotation).where(FlywheelAnnotation.is_golden.is_(True))
            count_query = count_query.join(FlywheelAnnotation).where(
                FlywheelAnnotation.is_golden.is_(True)
            )

        total = await db.scalar(count_query) or 0
        result = await db.execute(
            query.order_by(FlywheelSample.updated_at.desc()).offset(offset).limit(limit)
        )
        samples = list(result.scalars().all())

        if include_images and samples:
            run_uuids = {s.source_run_uuid for s in samples}
            runs_result = await db.execute(
                select(AgentRun).where(AgentRun.run_uuid.in_(run_uuids))
            )
            runs_by_uuid = {r.run_uuid: r.id for r in runs_result.scalars().all()}
            step_map: dict[tuple[str, int], AgentRunStep] = {}
            if runs_by_uuid:
                steps_result = await db.execute(
                    select(AgentRunStep).where(AgentRunStep.run_id.in_(runs_by_uuid.values()))
                )
                for step in steps_result.scalars().all():
                    run_uuid = next(
                        (uuid for uuid, rid in runs_by_uuid.items() if rid == step.run_id), None
                    )
                    if run_uuid:
                        step_map[(run_uuid, step.step_order)] = step
            for sample in samples:
                step = step_map.get((sample.source_run_uuid, sample.source_step_order))
                if step:
                    sample._before_image = step.before_image  # type: ignore[attr-defined]
                    sample._after_image = step.after_image  # type: ignore[attr-defined]

        return samples, total

    async def get_sample(self, db: AsyncSession, sample_id: int) -> FlywheelSample | None:
        return await db.scalar(
            select(FlywheelSample)
            .options(selectinload(FlywheelSample.annotation))
            .where(FlywheelSample.id == sample_id)
        )

    async def get_step_images(
        self, db: AsyncSession, run_uuid: str, step_order: int
    ) -> tuple[str | None, str | None, ActionIntent | None]:
        run = await db.scalar(select(AgentRun).where(AgentRun.run_uuid == run_uuid))
        if not run:
            return None, None, None
        step = await db.scalar(
            select(AgentRunStep).where(
                AgentRunStep.run_id == run.id, AgentRunStep.step_order == step_order
            )
        )
        if not step:
            return None, None, None
        intent = None
        if step.intent_json:
            try:
                intent = ActionIntent.model_validate_json(step.intent_json)
            except Exception:
                intent = None
        return step.before_image, step.after_image, intent

    async def upsert_annotation(
        self, db: AsyncSession, sample_id: int, payload: dict
    ) -> FlywheelAnnotation:
        annotation = await db.scalar(
            select(FlywheelAnnotation).where(FlywheelAnnotation.sample_id == sample_id)
        )
        if annotation:
            for key, value in payload.items():
                setattr(annotation, key, value)
        else:
            annotation = FlywheelAnnotation(sample_id=sample_id, **payload)
            db.add(annotation)
        sample = await self.get_sample(db, sample_id)
        if sample and payload.get("is_golden"):
            sample.cleaning_status = "golden"
        await db.commit()
        await db.refresh(annotation)
        return annotation

    async def update_sample_cleaning(
        self, db: AsyncSession, sample_id: int, payload: dict
    ) -> FlywheelSample | None:
        sample = await self.get_sample(db, sample_id)
        if not sample:
            return None
        for key, value in payload.items():
            setattr(sample, key, value)
        await db.commit()
        await db.refresh(sample)
        return sample

    async def bulk_update_cleaning(
        self, db: AsyncSession, sample_ids: list[int], payload: dict
    ) -> int:
        if not sample_ids:
            return 0
        result = await db.execute(select(FlywheelSample).where(FlywheelSample.id.in_(sample_ids)))
        samples = list(result.scalars().all())
        for sample in samples:
            for key, value in payload.items():
                setattr(sample, key, value)
        await db.commit()
        return len(samples)

    async def auto_clean(
        self,
        db: AsyncSession,
        *,
        min_quality_score: float,
        require_both_images: bool,
        require_auto_verification: bool,
        dedupe: bool,
    ) -> tuple[int, int, int]:
        result = await db.execute(
            select(FlywheelSample).where(FlywheelSample.cleaning_status == "raw")
        )
        samples = list(result.scalars().all())
        marked_cleaned = marked_rejected = deduped = 0
        seen_keys: set[tuple[str, str]] = set()

        for sample in samples:
            key = (sample.case_name, sample.description.strip())
            if dedupe and key in seen_keys:
                sample.cleaning_status = "rejected"
                sample.exclude_reason = "重复步骤描述"
                marked_rejected += 1
                deduped += 1
                continue
            seen_keys.add(key)

            if require_both_images and not (sample.has_before_image and sample.has_after_image):
                sample.cleaning_status = "rejected"
                sample.exclude_reason = "缺少执行前/后截图"
                marked_rejected += 1
                continue
            if require_auto_verification and sample.auto_verification_success is not True:
                sample.cleaning_status = "rejected"
                sample.exclude_reason = "自动验证未通过"
                marked_rejected += 1
                continue
            if sample.quality_score >= min_quality_score:
                sample.cleaning_status = "cleaned"
                marked_cleaned += 1
            else:
                sample.cleaning_status = "rejected"
                sample.exclude_reason = f"质量分低于 {min_quality_score}"
                marked_rejected += 1

        await db.commit()
        return marked_cleaned, marked_rejected, deduped

    async def create_dataset(
        self,
        db: AsyncSession,
        *,
        name: str,
        description: str,
        dataset_type: str,
        sample_ids: list[int],
        filters: dict | None,
    ) -> FlywheelDataset:
        if not sample_ids:
            raise ValueError("样本列表不能为空")
        dataset = FlywheelDataset(
            name=name,
            description=description,
            dataset_type=dataset_type,
            sample_count=len(sample_ids),
            filters_json=json.dumps(filters or {}, ensure_ascii=False),
        )
        db.add(dataset)
        await db.flush()
        for sid in sample_ids:
            db.add(FlywheelDatasetItem(dataset_id=dataset.id, sample_id=sid))
        await db.commit()
        await db.refresh(dataset)
        return dataset

    async def resolve_sample_ids(
        self,
        db: AsyncSession,
        *,
        sample_ids: list[int],
        golden_only: bool,
        cleaning_statuses: list[str] | None,
    ) -> list[int]:
        if sample_ids:
            return sample_ids
        query = select(FlywheelSample.id)
        if golden_only:
            query = query.join(FlywheelAnnotation).where(FlywheelAnnotation.is_golden.is_(True))
        elif cleaning_statuses:
            query = query.where(FlywheelSample.cleaning_status.in_(cleaning_statuses))
        else:
            query = query.where(FlywheelSample.cleaning_status.in_(["cleaned", "golden"]))
        result = await db.execute(query)
        return list(result.scalars().all())

    async def list_datasets(self, db: AsyncSession) -> list[FlywheelDataset]:
        result = await db.execute(select(FlywheelDataset).order_by(FlywheelDataset.created_at.desc()))
        return list(result.scalars().all())

    async def get_dataset(self, db: AsyncSession, dataset_id: int) -> FlywheelDataset | None:
        return await db.scalar(select(FlywheelDataset).where(FlywheelDataset.id == dataset_id))

    async def get_dataset_samples(self, db: AsyncSession, dataset_id: int) -> list[FlywheelSample]:
        result = await db.execute(
            select(FlywheelSample)
            .join(FlywheelDatasetItem, FlywheelDatasetItem.sample_id == FlywheelSample.id)
            .options(selectinload(FlywheelSample.annotation))
            .where(FlywheelDatasetItem.dataset_id == dataset_id)
        )
        return list(result.scalars().all())

    async def save_rag_documents(
        self, db: AsyncSession, documents: list[dict]
    ) -> list[FlywheelRagDocument]:
        saved: list[FlywheelRagDocument] = []
        for doc in documents:
            row = FlywheelRagDocument(
                dataset_id=doc.get("dataset_id"),
                title=doc["title"],
                content=doc["content"],
                metadata_json=json.dumps(doc.get("metadata") or {}, ensure_ascii=False),
                source_sample_ids_json=json.dumps(doc.get("source_sample_ids") or []),
            )
            db.add(row)
            saved.append(row)
        await db.commit()
        for row in saved:
            await db.refresh(row)
        return saved

    async def list_rag_documents(
        self, db: AsyncSession, dataset_id: int | None = None
    ) -> list[FlywheelRagDocument]:
        query = select(FlywheelRagDocument).order_by(FlywheelRagDocument.created_at.desc())
        if dataset_id:
            query = query.where(FlywheelRagDocument.dataset_id == dataset_id)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def create_training_job(
        self, db: AsyncSession, *, job_uuid: str, name: str, dataset_id: int, config: dict
    ) -> FlywheelTrainingJob:
        job = FlywheelTrainingJob(
            job_uuid=job_uuid,
            name=name,
            dataset_id=dataset_id,
            status="pending",
            config_json=json.dumps(config, ensure_ascii=False),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job

    async def update_training_job(self, db: AsyncSession, job_id: int, payload: dict) -> None:
        job = await db.scalar(select(FlywheelTrainingJob).where(FlywheelTrainingJob.id == job_id))
        if not job:
            return
        for key, value in payload.items():
            if key in ("metrics", "config") and isinstance(value, dict):
                setattr(job, f"{key}_json", json.dumps(value, ensure_ascii=False))
            else:
                setattr(job, key, value)
        await db.commit()

    async def get_training_job(self, db: AsyncSession, job_uuid: str) -> FlywheelTrainingJob | None:
        return await db.scalar(
            select(FlywheelTrainingJob).where(FlywheelTrainingJob.job_uuid == job_uuid)
        )

    async def list_training_jobs(self, db: AsyncSession) -> list[FlywheelTrainingJob]:
        result = await db.execute(
            select(FlywheelTrainingJob).order_by(FlywheelTrainingJob.created_at.desc())
        )
        return list(result.scalars().all())

    async def create_eval_job(
        self, db: AsyncSession, *, job_uuid: str, name: str, payload: dict
    ) -> FlywheelEvalJob:
        job = FlywheelEvalJob(
            job_uuid=job_uuid,
            name=name,
            dataset_id=payload["dataset_id"],
            training_job_id=payload.get("training_job_id"),
            llm_provider=payload.get("llm_provider"),
            model_ref=payload.get("model_ref"),
            status="pending",
            config_json=json.dumps(payload.get("config") or {}, ensure_ascii=False),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job

    async def update_eval_job(self, db: AsyncSession, job_id: int, payload: dict) -> None:
        job = await db.scalar(select(FlywheelEvalJob).where(FlywheelEvalJob.id == job_id))
        if not job:
            return
        for key, value in payload.items():
            if key in ("results", "config") and isinstance(value, dict):
                setattr(job, f"{key}_json", json.dumps(value, ensure_ascii=False))
            else:
                setattr(job, key, value)
        await db.commit()

    async def get_eval_job(self, db: AsyncSession, job_uuid: str) -> FlywheelEvalJob | None:
        return await db.scalar(select(FlywheelEvalJob).where(FlywheelEvalJob.job_uuid == job_uuid))

    async def list_eval_jobs(self, db: AsyncSession) -> list[FlywheelEvalJob]:
        result = await db.execute(
            select(FlywheelEvalJob).order_by(FlywheelEvalJob.created_at.desc())
        )
        return list(result.scalars().all())


flywheel_repository = FlywheelRepository()
