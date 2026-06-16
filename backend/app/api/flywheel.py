from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
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
    FlywheelDatasetListResponse,
    FlywheelDatasetResponse,
    FlywheelEvalJobListResponse,
    FlywheelEvalJobResponse,
    FlywheelRagListResponse,
    FlywheelSampleListResponse,
    FlywheelSampleResponse,
    FlywheelStatsResponse,
    FlywheelTrainingJobListResponse,
    FlywheelTrainingJobResponse,
    GenerateRagRequest,
    SyncSamplesRequest,
    SyncSamplesResponse,
)
from app.flywheel_service.service import flywheel_service

router = APIRouter(prefix="/flywheel", tags=["flywheel"])


@router.get("/stats", response_model=FlywheelStatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)) -> FlywheelStatsResponse:
    return await flywheel_service.get_stats(db)


@router.post("/sync", response_model=SyncSamplesResponse)
async def sync_samples(
    request: SyncSamplesRequest, db: AsyncSession = Depends(get_db)
) -> SyncSamplesResponse:
    return await flywheel_service.sync_samples(db, request)


@router.get("/samples", response_model=FlywheelSampleListResponse)
async def list_samples(
    cleaning_status: str | None = None,
    golden_only: bool = False,
    min_quality: float | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=200),
    include_images: bool = False,
    db: AsyncSession = Depends(get_db),
) -> FlywheelSampleListResponse:
    return await flywheel_service.list_samples(
        db,
        cleaning_status=cleaning_status,
        golden_only=golden_only,
        min_quality=min_quality,
        offset=offset,
        limit=limit,
        include_images=include_images,
    )


@router.get("/samples/{sample_id}", response_model=FlywheelSampleResponse)
async def get_sample(sample_id: int, db: AsyncSession = Depends(get_db)) -> FlywheelSampleResponse:
    sample = await flywheel_service.get_sample_detail(db, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="样本不存在")
    return sample


@router.put("/samples/{sample_id}/annotation")
async def annotate_sample(
    sample_id: int, payload: AnnotationPayload, db: AsyncSession = Depends(get_db)
):
    try:
        return await flywheel_service.annotate_sample(db, sample_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/samples/{sample_id}/cleaning", response_model=FlywheelSampleResponse)
async def clean_sample(
    sample_id: int, payload: CleanSampleRequest, db: AsyncSession = Depends(get_db)
) -> FlywheelSampleResponse:
    try:
        return await flywheel_service.clean_sample(db, sample_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/cleaning/bulk", response_model=BulkCleanResponse)
async def bulk_clean(payload: BulkCleanRequest, db: AsyncSession = Depends(get_db)) -> BulkCleanResponse:
    return await flywheel_service.bulk_clean(db, payload)


@router.post("/cleaning/auto", response_model=AutoCleanResponse)
async def auto_clean(payload: AutoCleanRequest, db: AsyncSession = Depends(get_db)) -> AutoCleanResponse:
    return await flywheel_service.auto_clean(db, payload)


@router.post("/datasets", response_model=FlywheelDatasetResponse)
async def create_dataset(
    payload: CreateDatasetRequest, db: AsyncSession = Depends(get_db)
) -> FlywheelDatasetResponse:
    try:
        return await flywheel_service.create_dataset(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/datasets", response_model=FlywheelDatasetListResponse)
async def list_datasets(db: AsyncSession = Depends(get_db)) -> FlywheelDatasetListResponse:
    return await flywheel_service.list_datasets(db)


@router.post("/rag/generate", response_model=FlywheelRagListResponse)
async def generate_rag(
    payload: GenerateRagRequest, db: AsyncSession = Depends(get_db)
) -> FlywheelRagListResponse:
    return await flywheel_service.generate_rag(db, payload)


@router.get("/rag", response_model=FlywheelRagListResponse)
async def list_rag(
    dataset_id: int | None = None, db: AsyncSession = Depends(get_db)
) -> FlywheelRagListResponse:
    return await flywheel_service.list_rag(db, dataset_id)


@router.post("/training/jobs", response_model=FlywheelTrainingJobResponse)
async def create_training_job(
    payload: CreateTrainingJobRequest, db: AsyncSession = Depends(get_db)
) -> FlywheelTrainingJobResponse:
    try:
        return await flywheel_service.create_training_job(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/training/jobs", response_model=FlywheelTrainingJobListResponse)
async def list_training_jobs(db: AsyncSession = Depends(get_db)) -> FlywheelTrainingJobListResponse:
    return await flywheel_service.list_training_jobs(db)


@router.get("/training/jobs/{job_uuid}", response_model=FlywheelTrainingJobResponse)
async def get_training_job(job_uuid: str, db: AsyncSession = Depends(get_db)) -> FlywheelTrainingJobResponse:
    try:
        return await flywheel_service.get_training_job(db, job_uuid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/training/jobs/{job_uuid}/start", response_model=FlywheelTrainingJobResponse)
async def start_training_job(
    job_uuid: str, db: AsyncSession = Depends(get_db)
) -> FlywheelTrainingJobResponse:
    try:
        return await flywheel_service.start_training_job(db, job_uuid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/eval/jobs", response_model=FlywheelEvalJobResponse)
async def create_eval_job(
    payload: CreateEvalJobRequest, db: AsyncSession = Depends(get_db)
) -> FlywheelEvalJobResponse:
    try:
        return await flywheel_service.create_eval_job(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/eval/jobs", response_model=FlywheelEvalJobListResponse)
async def list_eval_jobs(db: AsyncSession = Depends(get_db)) -> FlywheelEvalJobListResponse:
    return await flywheel_service.list_eval_jobs(db)


@router.get("/eval/jobs/{job_uuid}", response_model=FlywheelEvalJobResponse)
async def get_eval_job(job_uuid: str, db: AsyncSession = Depends(get_db)) -> FlywheelEvalJobResponse:
    try:
        return await flywheel_service.get_eval_job(db, job_uuid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/eval/jobs/{job_uuid}/start", response_model=FlywheelEvalJobResponse)
async def start_eval_job(job_uuid: str, db: AsyncSession = Depends(get_db)) -> FlywheelEvalJobResponse:
    try:
        return await flywheel_service.start_eval_job(db, job_uuid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
