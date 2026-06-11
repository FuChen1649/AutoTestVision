from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.repository import agent_repository
from app.database import async_session
from app.result_verify_service.purpose_analyzer import purpose_analyzer
from app.result_verify_service.repository import result_verify_repository
from app.result_verify_service.schemas import (
    BatchPurposeReviewResponse,
    RunPurposeReviewResponse,
    StepPurposeReview,
    VerifyBatchRequest,
    VerifyRunRequest,
    VerifyStreamEvent,
)

logger = get_agent_logger()


class ResultVerifyService:
    async def verify_run(
        self, run_uuid: str, db: AsyncSession, payload: VerifyRunRequest | None = None
    ) -> RunPurposeReviewResponse:
        run = await result_verify_repository.get_run(db, run_uuid)
        if not run:
            raise RuntimeError("运行实例不存在")

        provider = (payload.llm_provider if payload else None) or run.llm_provider
        async for _ in self._stream_analyze_run_steps(db, run, provider):
            pass
        run = await result_verify_repository.get_run(db, run_uuid)
        assert run is not None
        return RunPurposeReviewResponse(
            run_id=run.run_uuid,
            case_name=run.case_name,
            reviews=result_verify_repository.collect_reviews(run),
        )

    async def verify_batch(
        self, batch_uuid: str, db: AsyncSession, payload: VerifyBatchRequest | None = None
    ) -> BatchPurposeReviewResponse:
        batch = await agent_repository.get_batch_by_uuid(db, batch_uuid)
        if not batch:
            raise RuntimeError("批量任务不存在")
        if not batch.results:
            raise RuntimeError("该批次尚无 Case 结果可验证")

        provider = payload.llm_provider if payload else None
        run_responses: list[RunPurposeReviewResponse] = []
        for item in sorted(batch.results, key=lambda row: row.case_order):
            run = await result_verify_repository.get_run(db, item.run_uuid)
            if not run:
                continue
            chosen = provider or run.llm_provider
            async for _ in self._stream_analyze_run_steps(db, run, chosen):
                pass
            run = await result_verify_repository.get_run(db, item.run_uuid)
            if run:
                run_responses.append(
                    RunPurposeReviewResponse(
                        run_id=run.run_uuid,
                        case_name=run.case_name,
                        reviews=result_verify_repository.collect_reviews(run),
                    )
                )
        return BatchPurposeReviewResponse(batch_id=batch_uuid, runs=run_responses)

    async def stream_verify_run(
        self, run_uuid: str, llm_provider: str | None = None
    ) -> AsyncGenerator[str, None]:
        async with async_session() as db:
            async for chunk in self._stream_verify_run_with_session(db, run_uuid, llm_provider):
                yield chunk

    async def stream_verify_batch(
        self, batch_uuid: str, llm_provider: str | None = None
    ) -> AsyncGenerator[str, None]:
        async with async_session() as db:
            batch = await agent_repository.get_batch_by_uuid(db, batch_uuid)
            if not batch:
                raise RuntimeError("批量任务不存在")
            if not batch.results:
                raise RuntimeError("该批次尚无 Case 结果可验证")

        async for chunk in self._stream_verify_batch_with_session(batch_uuid, llm_provider):
            yield chunk

    async def _stream_verify_run_with_session(
        self, db: AsyncSession, run_uuid: str, llm_provider: str | None
    ) -> AsyncGenerator[str, None]:
        run = await result_verify_repository.get_run(db, run_uuid)
        if not run:
            raise RuntimeError("运行实例不存在")

        provider = llm_provider or run.llm_provider
        yield self._sse(
            VerifyStreamEvent(type="start", run_id=run_uuid, case_name=run.case_name)
        )

        try:
            async for event_type, review, step_order in self._stream_analyze_run_steps(
                db, run, provider
            ):
                if event_type == "step_start":
                    yield self._sse(
                        VerifyStreamEvent(
                            type="step_start",
                            run_id=run_uuid,
                            step_order=step_order,
                        )
                    )
                elif event_type == "step_done" and review is not None:
                    run = await result_verify_repository.get_run(db, run_uuid)
                    assert run is not None
                    yield self._sse(
                        VerifyStreamEvent(
                            type="step_done",
                            run_id=run_uuid,
                            step_order=step_order,
                            review=review,
                            run=agent_repository.to_response(run),
                        )
                    )

            run = await result_verify_repository.get_run(db, run_uuid)
            assert run is not None
            yield self._sse(
                VerifyStreamEvent(
                    type="done",
                    run_id=run_uuid,
                    run=agent_repository.to_response(run),
                    message="验证完成",
                )
            )
        except Exception as exc:
            logger.exception("[result_verify] stream run 异常 run_id=%s", run_uuid)
            yield self._sse(
                VerifyStreamEvent(type="error", run_id=run_uuid, message=str(exc))
            )

    async def _stream_verify_batch_with_session(
        self, batch_uuid: str, llm_provider: str | None
    ) -> AsyncGenerator[str, None]:
        async with async_session() as db:
            batch = await agent_repository.get_batch_by_uuid(db, batch_uuid)
            if not batch:
                raise RuntimeError("批量任务不存在")
            if not batch.results:
                raise RuntimeError("该批次尚无 Case 结果可验证")

            yield self._sse(VerifyStreamEvent(type="start", batch_id=batch_uuid))

            try:
                for item in sorted(batch.results, key=lambda row: row.case_order):
                    run = await result_verify_repository.get_run(db, item.run_uuid)
                    if not run:
                        continue

                    provider = llm_provider or run.llm_provider
                    yield self._sse(
                        VerifyStreamEvent(
                            type="run_start",
                            batch_id=batch_uuid,
                            run_id=run.run_uuid,
                            case_name=run.case_name,
                        )
                    )

                    async for event_type, review, step_order in self._stream_analyze_run_steps(
                        db, run, provider
                    ):
                        if event_type == "step_start":
                            yield self._sse(
                                VerifyStreamEvent(
                                    type="step_start",
                                    batch_id=batch_uuid,
                                    run_id=run.run_uuid,
                                    step_order=step_order,
                                )
                            )
                        elif event_type == "step_done" and review is not None:
                            run = await result_verify_repository.get_run(db, run.run_uuid)
                            assert run is not None
                            yield self._sse(
                                VerifyStreamEvent(
                                    type="step_done",
                                    batch_id=batch_uuid,
                                    run_id=run.run_uuid,
                                    step_order=step_order,
                                    review=review,
                                    run=agent_repository.to_response(run),
                                )
                            )

                    run = await result_verify_repository.get_run(db, item.run_uuid)
                    if run:
                        yield self._sse(
                            VerifyStreamEvent(
                                type="run_done",
                                batch_id=batch_uuid,
                                run_id=run.run_uuid,
                                run=agent_repository.to_response(run),
                            )
                        )

                yield self._sse(
                    VerifyStreamEvent(
                        type="done",
                        batch_id=batch_uuid,
                        message="批次验证完成",
                    )
                )
            except Exception as exc:
                logger.exception("[result_verify] stream batch 异常 batch_id=%s", batch_uuid)
                yield self._sse(
                    VerifyStreamEvent(type="error", batch_id=batch_uuid, message=str(exc))
                )

    async def get_run_reviews(
        self, run_uuid: str, db: AsyncSession
    ) -> RunPurposeReviewResponse:
        run = await result_verify_repository.get_run(db, run_uuid)
        if not run:
            raise RuntimeError("运行实例不存在")
        return RunPurposeReviewResponse(
            run_id=run.run_uuid,
            case_name=run.case_name,
            reviews=result_verify_repository.collect_reviews(run),
        )

    async def _stream_analyze_run_steps(
        self, db: AsyncSession, run, provider: str | None
    ) -> AsyncGenerator[tuple[str, StepPurposeReview | None, int | None], None]:
        for step in sorted(run.steps, key=lambda item: item.step_order):
            before_image = step.before_image_annotated or step.before_image
            after_image = step.after_image
            if not before_image or not after_image:
                logger.info(
                    "[result_verify] 跳过无截图步骤 run=%s step=%d",
                    run.run_uuid,
                    step.step_order + 1,
                )
                continue

            yield ("step_start", None, step.step_order)

            intent = result_verify_repository.step_intent(step)
            review = await purpose_analyzer.analyze_step(
                step_order=step.step_order,
                description=step.description,
                intent=intent,
                before_image=before_image,
                after_image=after_image,
                provider=provider,
            )
            await result_verify_repository.save_purpose_review(db, step, review)
            await agent_repository.commit(db)
            logger.info(
                "[result_verify] 完成 step=%d purpose=%s",
                step.step_order + 1,
                review.purpose[:60],
            )
            yield ("step_done", review, step.step_order)

    def _sse(self, event: VerifyStreamEvent) -> str:
        return f"data: {event.model_dump_json()}\n\n"


result_verify_service = ResultVerifyService()
