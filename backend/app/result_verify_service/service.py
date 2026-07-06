from collections.abc import AsyncGenerator
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_test_code_service.repository import agent_code_repository
from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.repository import agent_repository
from app.database import async_session
from app.models.agent import AgentRun
from app.models.agent_code import AgentCodeRun
from app.result_verify_service.dual_analyzer import dual_step_analyzer
from app.result_verify_service.dual_repository import dual_verify_repository
from app.result_verify_service.purpose_analyzer import purpose_analyzer
from app.result_verify_service.repository import ExecMode, result_verify_repository
from app.result_verify_service.schemas import (
    BatchPurposeReviewResponse,
    DualStepVerifyReview,
    DualVerifyResponse,
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
        exec_mode, run = await result_verify_repository.resolve_run(db, run_uuid)
        if not run or not exec_mode:
            raise RuntimeError("运行实例不存在")

        provider = (payload.llm_provider if payload else None) or run.llm_provider
        async for _ in self._stream_analyze_run_steps(db, run, exec_mode, provider):
            pass
        exec_mode, run = await result_verify_repository.resolve_run(db, run_uuid)
        assert run is not None and exec_mode is not None
        return self._run_review_response(run, exec_mode)

    async def verify_batch(
        self,
        batch_uuid: str,
        db: AsyncSession,
        payload: VerifyBatchRequest | None = None,
        *,
        exec_mode: ExecMode = "position",
    ) -> BatchPurposeReviewResponse:
        provider = payload.llm_provider if payload else None
        run_responses: list[RunPurposeReviewResponse] = []

        if exec_mode == "code":
            batch = await result_verify_repository.get_code_batch(db, batch_uuid)
            if not batch:
                raise RuntimeError("批量任务不存在")
            if not batch.results:
                raise RuntimeError("该批次尚无 Case 结果可验证")
            for item in batch.results:
                if not item.run_uuid:
                    continue
                run = await result_verify_repository.get_code_run(db, item.run_uuid)
                if not run:
                    continue
                chosen = provider or run.llm_provider
                async for _ in self._stream_analyze_run_steps(db, run, "code", chosen):
                    pass
                run = await result_verify_repository.get_code_run(db, item.run_uuid)
                if run:
                    run_responses.append(self._run_review_response(run, "code"))
        else:
            batch = await result_verify_repository.get_position_batch(db, batch_uuid)
            if not batch:
                raise RuntimeError("批量任务不存在")
            if not batch.results:
                raise RuntimeError("该批次尚无 Case 结果可验证")
            for item in sorted(batch.results, key=lambda row: row.case_order):
                run = await result_verify_repository.get_position_run(db, item.run_uuid)
                if not run:
                    continue
                chosen = provider or run.llm_provider
                async for _ in self._stream_analyze_run_steps(db, run, "position", chosen):
                    pass
                run = await result_verify_repository.get_position_run(db, item.run_uuid)
                if run:
                    run_responses.append(self._run_review_response(run, "position"))

        return BatchPurposeReviewResponse(batch_id=batch_uuid, runs=run_responses)

    async def stream_verify_run(
        self, run_uuid: str, llm_provider: str | None = None
    ) -> AsyncGenerator[str, None]:
        async with async_session() as db:
            async for chunk in self._stream_verify_run_with_session(db, run_uuid, llm_provider):
                yield chunk

    async def stream_verify_batch(
        self, batch_uuid: str, llm_provider: str | None = None, *, exec_mode: ExecMode = "position"
    ) -> AsyncGenerator[str, None]:
        async for chunk in self._stream_verify_batch_with_session(batch_uuid, llm_provider, exec_mode):
            yield chunk

    async def _stream_verify_run_with_session(
        self, db: AsyncSession, run_uuid: str, llm_provider: str | None
    ) -> AsyncGenerator[str, None]:
        exec_mode, run = await result_verify_repository.resolve_run(db, run_uuid)
        if not run or not exec_mode:
            raise RuntimeError("运行实例不存在")

        provider = llm_provider or run.llm_provider
        yield self._sse(
            VerifyStreamEvent(
                type="start",
                exec_mode=exec_mode,
                run_id=run_uuid,
                case_name=run.case_name,
            )
        )

        try:
            async for event_type, review, step_order in self._stream_analyze_run_steps(
                db, run, exec_mode, provider
            ):
                if event_type == "step_start":
                    yield self._sse(
                        VerifyStreamEvent(
                            type="step_start",
                            exec_mode=exec_mode,
                            run_id=run_uuid,
                            step_order=step_order,
                        )
                    )
                elif event_type == "step_done" and review is not None:
                    yield self._sse(
                        VerifyStreamEvent(
                            type="step_done",
                            exec_mode=exec_mode,
                            run_id=run_uuid,
                            step_order=step_order,
                            review=review,
                        )
                    )

            exec_mode, run = await result_verify_repository.resolve_run(db, run_uuid)
            assert run is not None and exec_mode is not None
            yield self._sse(
                VerifyStreamEvent(
                    type="done",
                    exec_mode=exec_mode,
                    run_id=run_uuid,
                    message="验证完成",
                )
            )
        except Exception as exc:
            logger.exception("[result_verify] stream run 异常 run_id=%s", run_uuid)
            yield self._sse(
                VerifyStreamEvent(type="error", exec_mode=exec_mode, run_id=run_uuid, message=str(exc))
            )

    async def _stream_verify_batch_with_session(
        self, batch_uuid: str, llm_provider: str | None, exec_mode: ExecMode
    ) -> AsyncGenerator[str, None]:
        async with async_session() as db:
            if exec_mode == "code":
                batch = await result_verify_repository.get_code_batch(db, batch_uuid)
            else:
                batch = await result_verify_repository.get_position_batch(db, batch_uuid)
            if not batch:
                raise RuntimeError("批量任务不存在")
            if not batch.results:
                raise RuntimeError("该批次尚无 Case 结果可验证")

            yield self._sse(VerifyStreamEvent(type="start", exec_mode=exec_mode, batch_id=batch_uuid))

            try:
                items = (
                    list(batch.results)
                    if exec_mode == "code"
                    else sorted(batch.results, key=lambda row: row.case_order)
                )
                for item in items:
                    run_uuid = item.run_uuid
                    if not run_uuid:
                        continue
                    if exec_mode == "code":
                        run = await result_verify_repository.get_code_run(db, run_uuid)
                    else:
                        run = await result_verify_repository.get_position_run(db, run_uuid)
                    if not run:
                        continue

                    provider = llm_provider or run.llm_provider
                    yield self._sse(
                        VerifyStreamEvent(
                            type="run_start",
                            exec_mode=exec_mode,
                            batch_id=batch_uuid,
                            run_id=run.run_uuid,
                            case_name=run.case_name,
                        )
                    )

                    async for event_type, review, step_order in self._stream_analyze_run_steps(
                        db, run, exec_mode, provider
                    ):
                        if event_type == "step_start":
                            yield self._sse(
                                VerifyStreamEvent(
                                    type="step_start",
                                    exec_mode=exec_mode,
                                    batch_id=batch_uuid,
                                    run_id=run.run_uuid,
                                    step_order=step_order,
                                )
                            )
                        elif event_type == "step_done" and review is not None:
                            yield self._sse(
                                VerifyStreamEvent(
                                    type="step_done",
                                    exec_mode=exec_mode,
                                    batch_id=batch_uuid,
                                    run_id=run.run_uuid,
                                    step_order=step_order,
                                    review=review,
                                )
                            )

                    if exec_mode == "code":
                        refreshed = await result_verify_repository.get_code_run(db, run_uuid)
                    else:
                        refreshed = await result_verify_repository.get_position_run(db, run_uuid)
                    if refreshed:
                        yield self._sse(
                            VerifyStreamEvent(
                                type="run_done",
                                exec_mode=exec_mode,
                                batch_id=batch_uuid,
                                run_id=refreshed.run_uuid,
                            )
                        )

                yield self._sse(
                    VerifyStreamEvent(
                        type="done",
                        exec_mode=exec_mode,
                        batch_id=batch_uuid,
                        message="批次验证完成",
                    )
                )
            except Exception as exc:
                logger.exception("[result_verify] stream batch 异常 batch_id=%s", batch_uuid)
                yield self._sse(
                    VerifyStreamEvent(
                        type="error",
                        exec_mode=exec_mode,
                        batch_id=batch_uuid,
                        message=str(exc),
                    )
                )

    async def get_run_reviews(
        self, run_uuid: str, db: AsyncSession
    ) -> RunPurposeReviewResponse:
        exec_mode, run = await result_verify_repository.resolve_run(db, run_uuid)
        if not run or not exec_mode:
            raise RuntimeError("运行实例不存在")
        return self._run_review_response(run, exec_mode)

    def _run_review_response(
        self, run: AgentRun | AgentCodeRun, exec_mode: ExecMode
    ) -> RunPurposeReviewResponse:
        if exec_mode == "code":
            assert isinstance(run, AgentCodeRun)
            reviews = result_verify_repository.collect_reviews_code(run)
        else:
            assert isinstance(run, AgentRun)
            reviews = result_verify_repository.collect_reviews_position(run)
        return RunPurposeReviewResponse(
            run_id=run.run_uuid,
            case_name=run.case_name,
            reviews=reviews,
        )

    async def _stream_analyze_run_steps(
        self,
        db: AsyncSession,
        run: AgentRun | AgentCodeRun,
        exec_mode: ExecMode,
        provider: str | None,
    ) -> AsyncGenerator[tuple[str, StepPurposeReview | None, int | None], None]:
        for step in sorted(run.steps, key=lambda item: item.step_order):
            before_image = step.before_image_annotated or step.before_image
            after_image = step.after_image
            if not before_image or not after_image:
                logger.info(
                    "[result_verify] 跳过无截图步骤 run=%s step=%d mode=%s",
                    run.run_uuid,
                    step.step_order + 1,
                    exec_mode,
                )
                continue

            yield ("step_start", None, step.step_order)

            if exec_mode == "code":
                intent = result_verify_repository.step_intent_code(step)  # type: ignore[arg-type]
            else:
                intent = result_verify_repository.step_intent_position(step)  # type: ignore[arg-type]

            review = await purpose_analyzer.analyze_step(
                step_order=step.step_order,
                description=step.description,
                intent=intent,
                before_image=before_image,
                after_image=after_image,
                provider=provider,
            )
            if exec_mode == "code":
                await result_verify_repository.save_purpose_review_code(db, step, review)
                await agent_code_repository.commit(db)
            else:
                await result_verify_repository.save_purpose_review_position(db, step, review)
                await agent_repository.commit(db)
            logger.info(
                "[result_verify] 完成 step=%d mode=%s purpose=%s",
                step.step_order + 1,
                exec_mode,
                review.purpose[:60],
            )
            yield ("step_done", review, step.step_order)

    async def verify_dual(
        self, task_uuid: str, db: AsyncSession, payload: VerifyRunRequest | None = None
    ) -> DualVerifyResponse:
        task = await dual_verify_repository.get_task(db, task_uuid)
        if not task:
            raise RuntimeError("双脚本任务不存在")
        provider = (payload.llm_provider if payload else None) or None
        async for _ in self._stream_analyze_dual_steps(db, task, provider):
            pass
        task = await dual_verify_repository.get_task(db, task_uuid)
        assert task is not None
        return DualVerifyResponse(
            task_id=task.task_uuid,
            case_name=task.case_name or "",
            reviews=dual_verify_repository.collect_reviews(task),
        )

    async def get_dual_reviews(self, task_uuid: str, db: AsyncSession) -> DualVerifyResponse:
        task = await dual_verify_repository.get_task(db, task_uuid)
        if not task:
            raise RuntimeError("双脚本任务不存在")
        return DualVerifyResponse(
            task_id=task.task_uuid,
            case_name=task.case_name or "",
            reviews=dual_verify_repository.collect_reviews(task),
        )

    async def stream_verify_dual(
        self, task_uuid: str, llm_provider: str | None = None
    ) -> AsyncGenerator[str, None]:
        async with async_session() as db:
            task = await dual_verify_repository.get_task(db, task_uuid)
            if not task:
                raise RuntimeError("双脚本任务不存在")

            yield self._sse(
                VerifyStreamEvent(
                    type="start",
                    exec_mode="dual",
                    task_id=task_uuid,
                    case_name=task.case_name,
                )
            )

            try:
                async for event_type, review, step_order in self._stream_analyze_dual_steps(
                    db, task, llm_provider
                ):
                    if event_type == "step_start":
                        yield self._sse(
                            VerifyStreamEvent(
                                type="step_start",
                                exec_mode="dual",
                                task_id=task_uuid,
                                step_order=step_order,
                            )
                        )
                    elif event_type == "step_done" and review is not None:
                        yield self._sse(
                            VerifyStreamEvent(
                                type="step_done",
                                exec_mode="dual",
                                task_id=task_uuid,
                                step_order=step_order,
                                dual_review=review,
                            )
                        )

                yield self._sse(
                    VerifyStreamEvent(
                        type="done",
                        exec_mode="dual",
                        task_id=task_uuid,
                        message="双脚本验证完成",
                    )
                )
            except Exception as exc:
                logger.exception("[result_verify] stream dual 异常 task_id=%s", task_uuid)
                yield self._sse(
                    VerifyStreamEvent(
                        type="error",
                        exec_mode="dual",
                        task_id=task_uuid,
                        message=str(exc),
                    )
                )

    async def _stream_analyze_dual_steps(
        self,
        db: AsyncSession,
        task,
        provider: str | None,
    ) -> AsyncGenerator[tuple[str, DualStepVerifyReview | None, int | None], None]:
        pos_run, code_run = await dual_verify_repository.load_dual_runs(db, task)
        for pos_step, code_step in dual_verify_repository.iter_step_pairs(pos_run, code_run):
            images = dual_verify_repository.step_images(pos_step, code_step)
            if not images:
                logger.info(
                    "[result_verify] 跳过无完整截图的双脚步骤 task=%s step=%d",
                    task.task_uuid,
                    pos_step.step_order + 1,
                )
                continue

            pos_before, pos_after, code_before, code_after = images
            pos_action, code_action = dual_verify_repository.step_actions(pos_step, code_step)
            description = pos_step.description or code_step.description

            yield ("step_start", None, pos_step.step_order)

            review = await dual_step_analyzer.analyze_step(
                step_order=pos_step.step_order,
                description=description,
                position_before=pos_before,
                position_after=pos_after,
                code_before=code_before,
                code_after=code_after,
                position_action=pos_action,
                code_action=code_action,
                provider=provider,
            )
            await dual_verify_repository.save_review(db, task, review)
            await db.commit()
            logger.info(
                "[result_verify] 双脚步骤 step=%d consistent=%s after_match=%s",
                pos_step.step_order + 1,
                review.consistent,
                review.after_match,
            )
            yield ("step_done", review, pos_step.step_order)

    def _sse(self, event: VerifyStreamEvent) -> str:
        return f"data: {event.model_dump_json()}\n\n"


result_verify_service = ResultVerifyService()
