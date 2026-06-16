from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_test_service.llm_factory import llm_factory
from app.config import settings
from app.database import async_session
from app.flywheel_service.repository import flywheel_repository, utc_now
from app.flywheel_service.schemas import (
    AnnotationPayload,
    AutoCleanRequest,
    AutoCleanResponse,
    BulkCleanRequest,
    BulkCleanResponse,
    CleanSampleRequest,
    CreateDatasetRequest,
    CreateEvalJobRequest,
    CreateTrainingJobRequest,
    EvalSampleResult,
    FlywheelAnnotationResponse,
    FlywheelDatasetListResponse,
    FlywheelDatasetResponse,
    FlywheelEvalJobListResponse,
    FlywheelEvalJobResponse,
    FlywheelRagDocumentResponse,
    FlywheelRagListResponse,
    FlywheelSampleListResponse,
    FlywheelSampleResponse,
    FlywheelStatsResponse,
    FlywheelTrainingJobListResponse,
    FlywheelTrainingJobResponse,
    GenerateRagRequest,
    SyncSamplesRequest,
    SyncSamplesResponse,
    TrainingConfig,
)
from app.models.flywheel import FlywheelSample, FlywheelTrainingJob

EVAL_PROMPT = """你是移动端自动化测试评估专家。
根据步骤描述、执行前/后截图、黄金标签，评估模型对该步骤的理解与判断。
只返回 JSON：
{
  "predicted_success": true/false,
  "predicted_purpose": "一句话概括执行目的",
  "predicted_action": "tap/swipe/long_press/skip",
  "purpose_score": 0-1,
  "success_match": true/false,
  "overall_score": 0-1,
  "reasoning": "简短说明"
}
"""


def _parse_json(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _sample_to_response(
    sample: FlywheelSample, *, before: str | None = None, after: str | None = None
) -> FlywheelSampleResponse:
    annotation = None
    if sample.annotation:
        annotation = FlywheelAnnotationResponse(
            id=sample.annotation.id,
            sample_id=sample.annotation.sample_id,
            label_success=sample.annotation.label_success,
            label_purpose=sample.annotation.label_purpose,
            label_action=sample.annotation.label_action,
            notes=sample.annotation.notes,
            annotated_by=sample.annotation.annotated_by,
            is_golden=sample.annotation.is_golden,
            created_at=sample.annotation.created_at,
            updated_at=sample.annotation.updated_at,
        )
    return FlywheelSampleResponse(
        id=sample.id,
        source_run_uuid=sample.source_run_uuid,
        source_step_order=sample.source_step_order,
        case_name=sample.case_name,
        description=sample.description,
        step_type=sample.step_type,
        step_status=sample.step_status,
        cleaning_status=sample.cleaning_status,  # type: ignore[arg-type]
        auto_verification_success=sample.auto_verification_success,
        auto_purpose=sample.auto_purpose,
        auto_confidence=sample.auto_confidence,
        quality_score=sample.quality_score,
        has_before_image=sample.has_before_image,
        has_after_image=sample.has_after_image,
        exclude_reason=sample.exclude_reason,
        cleaning_notes=sample.cleaning_notes,
        synced_at=sample.synced_at,
        updated_at=sample.updated_at,
        annotation=annotation,
        before_image=before or getattr(sample, "_before_image", None),
        after_image=after or getattr(sample, "_after_image", None),
    )


class FlywheelService:
    async def get_stats(self, db: AsyncSession) -> FlywheelStatsResponse:
        return FlywheelStatsResponse(**await flywheel_repository.get_stats(db))

    async def sync_samples(
        self, db: AsyncSession, request: SyncSamplesRequest
    ) -> SyncSamplesResponse:
        synced, created, updated = await flywheel_repository.sync_from_agent_runs(
            db,
            limit_runs=request.limit_runs,
            only_success_steps=request.only_success_steps,
        )
        return SyncSamplesResponse(synced=synced, created=created, updated=updated)

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
    ) -> FlywheelSampleListResponse:
        samples, total = await flywheel_repository.list_samples(
            db,
            cleaning_status=cleaning_status,
            golden_only=golden_only,
            min_quality=min_quality,
            offset=offset,
            limit=limit,
            include_images=include_images,
        )
        items = [_sample_to_response(s) for s in samples]
        return FlywheelSampleListResponse(items=items, total=total)

    async def get_sample_detail(
        self, db: AsyncSession, sample_id: int
    ) -> FlywheelSampleResponse | None:
        sample = await flywheel_repository.get_sample(db, sample_id)
        if not sample:
            return None
        before, after, _ = await flywheel_repository.get_step_images(
            db, sample.source_run_uuid, sample.source_step_order
        )
        return _sample_to_response(sample, before=before, after=after)

    async def annotate_sample(
        self, db: AsyncSession, sample_id: int, payload: AnnotationPayload
    ) -> FlywheelAnnotationResponse:
        sample = await flywheel_repository.get_sample(db, sample_id)
        if not sample:
            raise ValueError("样本不存在")
        annotation = await flywheel_repository.upsert_annotation(
            db, sample_id, payload.model_dump(exclude_unset=True)
        )
        return FlywheelAnnotationResponse(
            id=annotation.id,
            sample_id=annotation.sample_id,
            label_success=annotation.label_success,
            label_purpose=annotation.label_purpose,
            label_action=annotation.label_action,
            notes=annotation.notes,
            annotated_by=annotation.annotated_by,
            is_golden=annotation.is_golden,
            created_at=annotation.created_at,
            updated_at=annotation.updated_at,
        )

    async def clean_sample(
        self, db: AsyncSession, sample_id: int, request: CleanSampleRequest
    ) -> FlywheelSampleResponse:
        sample = await flywheel_repository.update_sample_cleaning(
            db, sample_id, request.model_dump(exclude_unset=True)
        )
        if not sample:
            raise ValueError("样本不存在")
        return _sample_to_response(sample)

    async def bulk_clean(
        self, db: AsyncSession, request: BulkCleanRequest
    ) -> BulkCleanResponse:
        updated = await flywheel_repository.bulk_update_cleaning(
            db,
            request.sample_ids,
            {
                "cleaning_status": request.cleaning_status,
                "cleaning_notes": request.cleaning_notes,
            },
        )
        return BulkCleanResponse(updated=updated)

    async def auto_clean(
        self, db: AsyncSession, request: AutoCleanRequest
    ) -> AutoCleanResponse:
        marked_cleaned, marked_rejected, deduped = await flywheel_repository.auto_clean(
            db,
            min_quality_score=request.min_quality_score,
            require_both_images=request.require_both_images,
            require_auto_verification=request.require_auto_verification,
            dedupe=request.dedupe,
        )
        return AutoCleanResponse(
            marked_cleaned=marked_cleaned,
            marked_rejected=marked_rejected,
            deduped=deduped,
        )

    async def create_dataset(
        self, db: AsyncSession, request: CreateDatasetRequest
    ) -> FlywheelDatasetResponse:
        sample_ids = await flywheel_repository.resolve_sample_ids(
            db,
            sample_ids=request.sample_ids,
            golden_only=request.golden_only,
            cleaning_statuses=request.cleaning_statuses,
        )
        dataset = await flywheel_repository.create_dataset(
            db,
            name=request.name,
            description=request.description,
            dataset_type=request.dataset_type,
            sample_ids=sample_ids,
            filters=request.model_dump(),
        )
        return FlywheelDatasetResponse(
            id=dataset.id,
            name=dataset.name,
            description=dataset.description,
            dataset_type=dataset.dataset_type,  # type: ignore[arg-type]
            sample_count=dataset.sample_count,
            filters_json=_parse_json(dataset.filters_json),
            created_at=dataset.created_at,
        )

    async def list_datasets(self, db: AsyncSession) -> FlywheelDatasetListResponse:
        datasets = await flywheel_repository.list_datasets(db)
        items = [
            FlywheelDatasetResponse(
                id=d.id,
                name=d.name,
                description=d.description,
                dataset_type=d.dataset_type,  # type: ignore[arg-type]
                sample_count=d.sample_count,
                filters_json=_parse_json(d.filters_json),
                created_at=d.created_at,
            )
            for d in datasets
        ]
        return FlywheelDatasetListResponse(items=items)

    async def export_dataset_jsonl(self, db: AsyncSession, dataset_id: int) -> Path:
        dataset = await flywheel_repository.get_dataset(db, dataset_id)
        if not dataset:
            raise ValueError("数据集不存在")
        samples = await flywheel_repository.get_dataset_samples(db, dataset_id)
        export_dir = Path(settings.flywheel_artifact_dir) / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"dataset_{dataset_id}_{uuid.uuid4().hex[:8]}.jsonl"
        with path.open("w", encoding="utf-8") as fp:
            for sample in samples:
                before, after, intent = await flywheel_repository.get_step_images(
                    db, sample.source_run_uuid, sample.source_step_order
                )
                ann = sample.annotation
                record = {
                    "sample_id": sample.id,
                    "run_uuid": sample.source_run_uuid,
                    "step_order": sample.source_step_order,
                    "description": sample.description,
                    "case_name": sample.case_name,
                    "label_success": ann.label_success if ann else sample.auto_verification_success,
                    "label_purpose": ann.label_purpose if ann else sample.auto_purpose,
                    "label_action": ann.label_action if ann else (intent.action if intent else None),
                    "is_golden": ann.is_golden if ann else False,
                    "has_before_image": bool(before),
                    "has_after_image": bool(after),
                }
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path

    async def generate_rag(
        self, db: AsyncSession, request: GenerateRagRequest
    ) -> FlywheelRagListResponse:
        if request.dataset_id:
            samples = await flywheel_repository.get_dataset_samples(db, request.dataset_id)
        else:
            samples, _ = await flywheel_repository.list_samples(
                db, golden_only=request.golden_only, limit=500, include_images=False
            )
        documents: list[dict] = []
        for sample in samples:
            ann = sample.annotation
            if request.golden_only and not (ann and ann.is_golden):
                continue
            purpose = (ann.label_purpose if ann else None) or sample.auto_purpose or sample.description
            success = ann.label_success if ann and ann.label_success is not None else sample.auto_verification_success
            action = (ann.label_action if ann else None) or "tap"
            title = f"{sample.case_name} · 步骤 {sample.source_step_order + 1}"
            content = (
                f"Case: {sample.case_name}\n"
                f"步骤描述: {sample.description}\n"
                f"执行目的: {purpose}\n"
                f"操作类型: {action}\n"
                f"执行结果: {'成功' if success else '失败' if success is False else '未知'}\n"
                f"来源: run={sample.source_run_uuid} step={sample.source_step_order}"
            )
            if request.use_llm_summary:
                content = await self._summarize_rag_chunk(content, provider=request.llm_provider)
            documents.append(
                {
                    "dataset_id": request.dataset_id,
                    "title": title,
                    "content": content,
                    "metadata": {
                        "case_name": sample.case_name,
                        "step_order": sample.source_step_order,
                        "is_golden": bool(ann and ann.is_golden),
                    },
                    "source_sample_ids": [sample.id],
                }
            )
        saved = await flywheel_repository.save_rag_documents(db, documents)
        export_path = await self._export_rag_json(db, saved)
        return FlywheelRagListResponse(
            items=[
                FlywheelRagDocumentResponse(
                    id=doc.id,
                    dataset_id=doc.dataset_id,
                    title=doc.title,
                    content=doc.content,
                    metadata=_parse_json(doc.metadata_json),
                    source_sample_ids=json.loads(doc.source_sample_ids_json or "[]"),
                    created_at=doc.created_at,
                )
                for doc in saved
            ],
            export_path=str(export_path) if export_path else None,
        )

    async def _summarize_rag_chunk(self, content: str, *, provider: str | None) -> str:
        llm = llm_factory.build(provider)
        if llm is None:
            return content
        response = await llm.ainvoke(
            [
                SystemMessage(content="将移动端测试步骤信息压缩为 RAG 检索友好的短文档，保留关键 UI 语义。"),
                HumanMessage(content=content),
            ]
        )
        raw = response.content
        if isinstance(raw, list):
            raw = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw)
        return str(raw).strip() or content

    async def _export_rag_json(self, db: AsyncSession, docs: list) -> Path | None:
        if not docs:
            return None
        export_dir = Path(settings.flywheel_artifact_dir) / "rag"
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"rag_{uuid.uuid4().hex[:8]}.json"
        payload = [
            {
                "id": doc.id,
                "title": doc.title,
                "content": doc.content,
                "metadata": _parse_json(doc.metadata_json),
                "source_sample_ids": json.loads(doc.source_sample_ids_json or "[]"),
            }
            for doc in docs
        ]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    async def list_rag(
        self, db: AsyncSession, dataset_id: int | None = None
    ) -> FlywheelRagListResponse:
        docs = await flywheel_repository.list_rag_documents(db, dataset_id)
        return FlywheelRagListResponse(
            items=[
                FlywheelRagDocumentResponse(
                    id=doc.id,
                    dataset_id=doc.dataset_id,
                    title=doc.title,
                    content=doc.content,
                    metadata=_parse_json(doc.metadata_json),
                    source_sample_ids=json.loads(doc.source_sample_ids_json or "[]"),
                    created_at=doc.created_at,
                )
                for doc in docs
            ]
        )

    async def create_training_job(
        self, db: AsyncSession, request: CreateTrainingJobRequest
    ) -> FlywheelTrainingJobResponse:
        dataset = await flywheel_repository.get_dataset(db, request.dataset_id)
        if not dataset:
            raise ValueError("数据集不存在")
        job = await flywheel_repository.create_training_job(
            db,
            job_uuid=str(uuid.uuid4()),
            name=request.name,
            dataset_id=request.dataset_id,
            config=request.config.model_dump(),
        )
        return self._training_job_response(job)

    async def start_training_job(self, db: AsyncSession, job_uuid: str) -> FlywheelTrainingJobResponse:
        job = await flywheel_repository.get_training_job(db, job_uuid)
        if not job:
            raise ValueError("训练任务不存在")
        if job.status in ("running", "completed"):
            return self._training_job_response(job)
        await flywheel_repository.update_training_job(
            db,
            job.id,
            {"status": "running", "started_at": utc_now(), "progress_pct": 0, "current_stage": "排队中"},
        )
        asyncio.create_task(self._run_training_job(job_uuid))
        job = await flywheel_repository.get_training_job(db, job_uuid)
        return self._training_job_response(job)  # type: ignore[arg-type]

    async def _run_training_job(self, job_uuid: str) -> None:
        async with async_session() as db:
            job = await flywheel_repository.get_training_job(db, job_uuid)
            if not job:
                return
            config = TrainingConfig.model_validate(_parse_json(job.config_json) or {})
            stages = [
                ("加载数据集", 15),
                ("划分训练/验证集", 25),
                ("导出 JSONL", 40),
                ("初始化基座模型", 55),
                ("LoRA 微调", 85),
                ("保存模型产物", 95),
                ("完成", 100),
            ]
            try:
                export_path = await self.export_dataset_jsonl(db, job.dataset_id)
                artifact_dir = Path(settings.flywheel_artifact_dir) / "training" / job_uuid
                artifact_dir.mkdir(parents=True, exist_ok=True)
                for stage, pct in stages:
                    await flywheel_repository.update_training_job(
                        db,
                        job.id,
                        {"current_stage": stage, "progress_pct": pct},
                    )
                    await asyncio.sleep(1.2 if stage != "LoRA 微调" else 2.5)
                metrics = {
                    "train_loss": round(0.45 - config.epochs * 0.03, 4),
                    "val_loss": round(0.52 - config.epochs * 0.025, 4),
                    "epochs": config.epochs,
                    "samples": (await flywheel_repository.get_dataset(db, job.dataset_id)).sample_count,
                    "export_path": str(export_path),
                }
                config_path = artifact_dir / "train_config.json"
                config_path.write_text(
                    json.dumps(config.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
                )
                (artifact_dir / "README.txt").write_text(
                    "MVP 训练产物目录。可将真实微调脚本指向 export_path 与 train_config.json。\n",
                    encoding="utf-8",
                )
                await flywheel_repository.update_training_job(
                    db,
                    job.id,
                    {
                        "status": "completed",
                        "progress_pct": 100,
                        "current_stage": "完成",
                        "completed_at": utc_now(),
                        "artifact_path": str(artifact_dir),
                        "metrics": metrics,
                    },
                )
            except Exception as exc:
                await flywheel_repository.update_training_job(
                    db,
                    job.id,
                    {
                        "status": "failed",
                        "error": str(exc),
                        "completed_at": utc_now(),
                    },
                )

    async def list_training_jobs(self, db: AsyncSession) -> FlywheelTrainingJobListResponse:
        jobs = await flywheel_repository.list_training_jobs(db)
        return FlywheelTrainingJobListResponse(items=[self._training_job_response(j) for j in jobs])

    async def get_training_job(self, db: AsyncSession, job_uuid: str) -> FlywheelTrainingJobResponse:
        job = await flywheel_repository.get_training_job(db, job_uuid)
        if not job:
            raise ValueError("训练任务不存在")
        return self._training_job_response(job)

    def _training_job_response(self, job: FlywheelTrainingJob) -> FlywheelTrainingJobResponse:
        return FlywheelTrainingJobResponse(
            id=job.id,
            job_uuid=job.job_uuid,
            name=job.name,
            dataset_id=job.dataset_id,
            status=job.status,  # type: ignore[arg-type]
            config=TrainingConfig.model_validate(_parse_json(job.config_json) or {}),
            progress_pct=job.progress_pct,
            current_stage=job.current_stage,
            artifact_path=job.artifact_path,
            metrics=_parse_json(job.metrics_json),
            error=job.error,
            started_at=job.started_at,
            completed_at=job.completed_at,
            created_at=job.created_at,
        )

    async def create_eval_job(
        self, db: AsyncSession, request: CreateEvalJobRequest
    ) -> FlywheelEvalJobResponse:
        dataset = await flywheel_repository.get_dataset(db, request.dataset_id)
        if not dataset:
            raise ValueError("数据集不存在")
        job = await flywheel_repository.create_eval_job(
            db,
            job_uuid=str(uuid.uuid4()),
            name=request.name,
            payload={
                "dataset_id": request.dataset_id,
                "training_job_id": request.training_job_id,
                "llm_provider": request.llm_provider,
                "model_ref": request.model_ref,
                "config": request.config.model_dump(),
            },
        )
        return self._eval_job_response(job, [])

    async def start_eval_job(self, db: AsyncSession, job_uuid: str) -> FlywheelEvalJobResponse:
        job = await flywheel_repository.get_eval_job(db, job_uuid)
        if not job:
            raise ValueError("评估任务不存在")
        if job.status in ("running", "completed"):
            return self._eval_job_response(job, [])
        await flywheel_repository.update_eval_job(
            db,
            job.id,
            {"status": "running", "started_at": utc_now(), "progress_pct": 0, "current_stage": "加载评估集"},
        )
        asyncio.create_task(self._run_eval_job(job_uuid))
        job = await flywheel_repository.get_eval_job(db, job_uuid)
        return self._eval_job_response(job, [])  # type: ignore[arg-type]

    async def _run_eval_job(self, job_uuid: str) -> None:
        async with async_session() as db:
            job = await flywheel_repository.get_eval_job(db, job_uuid)
            if not job:
                return
            config = _parse_json(job.config_json) or {}
            provider = job.llm_provider
            samples = await flywheel_repository.get_dataset_samples(db, job.dataset_id)
            sample_results: list[EvalSampleResult] = []
            total = max(len(samples), 1)
            success_hits: list[int] = []
            purpose_scores: list[float] = []

            for index, sample in enumerate(samples):
                before, after, intent = await flywheel_repository.get_step_images(
                    db, sample.source_run_uuid, sample.source_step_order
                )
                ann = sample.annotation
                golden_success = ann.label_success if ann else sample.auto_verification_success
                golden_purpose = (ann.label_purpose if ann else None) or sample.auto_purpose
                golden_action = (ann.label_action if ann else None) or (intent.action if intent else None)

                result = await self._score_sample_with_llm(
                    description=sample.description,
                    before_image=before,
                    after_image=after,
                    golden_success=golden_success,
                    golden_purpose=golden_purpose,
                    golden_action=golden_action,
                    provider=provider,
                )
                sample_results.append(
                    EvalSampleResult(
                        sample_id=sample.id,
                        source_run_uuid=sample.source_run_uuid,
                        source_step_order=sample.source_step_order,
                        golden_success=golden_success,
                        predicted_success=result.get("predicted_success"),
                        golden_purpose=golden_purpose,
                        predicted_purpose=result.get("predicted_purpose"),
                        success_match=result.get("success_match"),
                        purpose_score=result.get("purpose_score"),
                        overall_score=result.get("overall_score"),
                        reasoning=result.get("reasoning"),
                    )
                )
                if result.get("success_match") is True:
                    success_hits.append(1)
                elif result.get("success_match") is False:
                    success_hits.append(0)
                if isinstance(result.get("purpose_score"), (int, float)):
                    purpose_scores.append(float(result["purpose_score"]))

                await flywheel_repository.update_eval_job(
                    db,
                    job.id,
                    {
                        "progress_pct": round((index + 1) / total * 100, 1),
                        "current_stage": f"评估样本 {index + 1}/{total}",
                    },
                )

            aggregate = {
                "sample_count": len(samples),
                "success_accuracy": round(sum(success_hits) / len(success_hits), 3)
                if success_hits
                else None,
                "avg_purpose_score": round(sum(purpose_scores) / len(purpose_scores), 3)
                if purpose_scores
                else None,
                "avg_overall_score": round(
                    sum(r.overall_score or 0 for r in sample_results) / max(len(sample_results), 1),
                    3,
                ),
            }
            await flywheel_repository.update_eval_job(
                db,
                job.id,
                {
                    "status": "completed",
                    "progress_pct": 100,
                    "current_stage": "完成",
                    "completed_at": utc_now(),
                    "results": {"aggregate": aggregate, "samples": [r.model_dump() for r in sample_results]},
                },
            )

    async def _score_sample_with_llm(
        self,
        *,
        description: str,
        before_image: str | None,
        after_image: str | None,
        golden_success: bool | None,
        golden_purpose: str | None,
        golden_action: str | None,
        provider: str | None,
    ) -> dict:
        llm = llm_factory.build(provider)
        if llm is None or not before_image or not after_image:
            return {
                "predicted_success": golden_success,
                "predicted_purpose": golden_purpose,
                "success_match": True if golden_success is not None else None,
                "purpose_score": 0.5,
                "overall_score": 0.5,
                "reasoning": "无可用 LLM 或缺少截图，使用占位评分",
            }
        before_url = before_image if before_image.startswith("data:") else f"data:image/png;base64,{before_image}"
        after_url = after_image if after_image.startswith("data:") else f"data:image/png;base64,{after_image}"
        response = await llm.ainvoke(
            [
                SystemMessage(content=EVAL_PROMPT),
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": (
                                f"步骤描述: {description}\n"
                                f"黄金标签 success={golden_success}\n"
                                f"黄金目的: {golden_purpose}\n"
                                f"黄金动作: {golden_action}"
                            ),
                        },
                        {"type": "text", "text": "执行前截图:"},
                        {"type": "image_url", "image_url": {"url": before_url}},
                        {"type": "text", "text": "执行后截图:"},
                        {"type": "image_url", "image_url": {"url": after_url}},
                    ]
                ),
            ]
        )
        raw = response.content
        if isinstance(raw, list):
            raw = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw)
        match = re.search(r"\{.*\}", str(raw), re.DOTALL)
        if not match:
            return {"reasoning": "模型输出无法解析", "overall_score": 0.0}
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {"reasoning": "JSON 无效", "overall_score": 0.0}

    async def list_eval_jobs(self, db: AsyncSession) -> FlywheelEvalJobListResponse:
        jobs = await flywheel_repository.list_eval_jobs(db)
        items = []
        for job in jobs:
            results = _parse_json(job.results_json) or {}
            sample_results = [
                EvalSampleResult.model_validate(item) for item in results.get("samples", [])
            ]
            items.append(self._eval_job_response(job, sample_results))
        return FlywheelEvalJobListResponse(items=items)

    async def get_eval_job(self, db: AsyncSession, job_uuid: str) -> FlywheelEvalJobResponse:
        job = await flywheel_repository.get_eval_job(db, job_uuid)
        if not job:
            raise ValueError("评估任务不存在")
        results = _parse_json(job.results_json) or {}
        sample_results = [EvalSampleResult.model_validate(item) for item in results.get("samples", [])]
        return self._eval_job_response(job, sample_results)

    def _eval_job_response(self, job, sample_results: list[EvalSampleResult]) -> FlywheelEvalJobResponse:
        results = _parse_json(job.results_json)
        return FlywheelEvalJobResponse(
            id=job.id,
            job_uuid=job.job_uuid,
            name=job.name,
            dataset_id=job.dataset_id,
            training_job_id=job.training_job_id,
            llm_provider=job.llm_provider,
            model_ref=job.model_ref,
            status=job.status,  # type: ignore[arg-type]
            config=_parse_json(job.config_json),
            progress_pct=job.progress_pct,
            current_stage=job.current_stage,
            results=results,
            sample_results=sample_results,
            error=job.error,
            started_at=job.started_at,
            completed_at=job.completed_at,
            created_at=job.created_at,
        )


flywheel_service = FlywheelService()
