import json
import random
import re
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.llm_factory import default_provider, llm_factory
from app.config import settings
from app.script_generation_service.verify_schemas import (
    AssertionDualConsistencyReview,
    SampledStepAnnotationReview,
)

logger = get_agent_logger()

ANNOTATION_VERIFY_PROMPT = """你是移动端自动化测试标注质量审查专家。
你会收到：步骤描述、执行前标注截图、执行后截图、以及该步的操作说明。
请判断：
1. 执行前标注（框/标记）是否准确标出了本步应操作的 UI 目标
2. 执行前→执行后的界面变化是否符合步骤描述的预期

只返回 JSON：
{
  "annotation_correct": true/false,
  "flow_correct": true/false,
  "reasoning": "详细说明",
  "confidence": 0-1
}
"""

ASSERTION_DUAL_PROMPT = """你是移动端双脚本断言一致性审查专家。
同一步断言会在 Position 与 Code 两台设备上分别截图。请判断两张截图的界面状态是否一致（允许分辨率、状态栏等微小差异）。
只返回 JSON：
{
  "consistent": true/false,
  "reasoning": "详细说明",
  "confidence": 0-1
}
"""


def _normalize_image(url: str) -> str:
    return url if url.startswith("data:") else f"data:image/png;base64,{url}"


def sample_step_sections(total_steps: int, per_section: int = 3) -> list[tuple[str, list[int]]]:
    if total_steps <= 0:
        return []
    if total_steps <= per_section:
        return [("begin", list(range(total_steps)))]

    third = max(1, total_steps // 3)
    begin_pool = list(range(0, min(third, total_steps)))
    mid_start = max(0, total_steps // 2 - per_section // 2)
    middle_pool = list(range(mid_start, min(mid_start + third + per_section, total_steps)))
    end_start = max(0, total_steps - third - per_section + 1)
    end_pool = list(range(end_start, total_steps))

    def pick(pool: list[int]) -> list[int]:
        if len(pool) <= per_section:
            return sorted(pool)
        return sorted(random.sample(pool, per_section))

    sections: list[tuple[str, list[int]]] = []
    for name, pool in (("begin", begin_pool), ("middle", middle_pool), ("end", end_pool)):
        orders = pick(pool)
        if orders:
            sections.append((name, orders))
    return sections


class CompletionVerifier:
    async def review_annotation(
        self,
        *,
        step_order: int,
        section: str,
        description: str,
        before_annotated: str,
        after_image: str,
        action_summary: str,
        provider: str | None = None,
    ) -> SampledStepAnnotationReview:
        chosen = provider or default_provider()
        model_override = settings.agent_verify_model or None
        llm = llm_factory.build(chosen, model_override=model_override)
        if llm is None:
            raise RuntimeError("未配置可用的验证模型")

        model_name = model_override or (
            settings.agent_local_model if chosen == "local" else settings.agent_llm_model
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=ANNOTATION_VERIFY_PROMPT),
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": (
                                f"步骤序号：{step_order + 1}\n"
                                f"所属抽样段：{section}\n"
                                f"步骤描述：{description}\n"
                                f"操作说明：{action_summary}"
                            ),
                        },
                        {"type": "text", "text": "执行前（标注）截图："},
                        {"type": "image_url", "image_url": {"url": _normalize_image(before_annotated)}},
                        {"type": "text", "text": "执行后截图："},
                        {"type": "image_url", "image_url": {"url": _normalize_image(after_image)}},
                    ]
                ),
            ]
        )
        raw = response.content
        if isinstance(raw, list):
            raw = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in raw
            )
        return self._parse_annotation(step_order, section, str(raw), model_name)

    async def review_assertion_dual(
        self,
        *,
        step_order: int,
        description: str,
        position_image: str,
        code_image: str,
        provider: str | None = None,
    ) -> AssertionDualConsistencyReview:
        chosen = provider or default_provider()
        model_override = settings.agent_verify_model or None
        llm = llm_factory.build(chosen, model_override=model_override)
        if llm is None:
            raise RuntimeError("未配置可用的验证模型")

        model_name = model_override or (
            settings.agent_local_model if chosen == "local" else settings.agent_llm_model
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=ASSERTION_DUAL_PROMPT),
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": (
                                f"断言步骤序号：{step_order + 1}\n"
                                f"步骤描述：{description}"
                            ),
                        },
                        {"type": "text", "text": "Position 设备截图："},
                        {"type": "image_url", "image_url": {"url": _normalize_image(position_image)}},
                        {"type": "text", "text": "Code 设备截图："},
                        {"type": "image_url", "image_url": {"url": _normalize_image(code_image)}},
                    ]
                ),
            ]
        )
        raw = response.content
        if isinstance(raw, list):
            raw = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in raw
            )
        return self._parse_assertion_dual(step_order, str(raw), model_name)

    def _parse_annotation(
        self, step_order: int, section: str, raw: str, model_name: str
    ) -> SampledStepAnnotationReview:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return SampledStepAnnotationReview(
                step_order=step_order,
                section=section,  # type: ignore[arg-type]
                annotation_correct=False,
                flow_correct=False,
                reasoning="模型输出无法解析",
                confidence=0.0,
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )
        try:
            payload = json.loads(match.group())
            return SampledStepAnnotationReview(
                step_order=step_order,
                section=section,  # type: ignore[arg-type]
                annotation_correct=bool(payload.get("annotation_correct", False)),
                flow_correct=bool(payload.get("flow_correct", False)),
                reasoning=str(payload.get("reasoning", "")),
                confidence=float(payload.get("confidence", 0.0)),
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            return SampledStepAnnotationReview(
                step_order=step_order,
                section=section,  # type: ignore[arg-type]
                annotation_correct=False,
                flow_correct=False,
                reasoning=f"JSON 无效: {exc}",
                confidence=0.0,
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )

    def _parse_assertion_dual(
        self, step_order: int, raw: str, model_name: str
    ) -> AssertionDualConsistencyReview:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return AssertionDualConsistencyReview(
                step_order=step_order,
                consistent=False,
                reasoning="模型输出无法解析",
                confidence=0.0,
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )
        try:
            payload = json.loads(match.group())
            return AssertionDualConsistencyReview(
                step_order=step_order,
                consistent=bool(payload.get("consistent", False)),
                reasoning=str(payload.get("reasoning", "")),
                confidence=float(payload.get("confidence", 0.0)),
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            return AssertionDualConsistencyReview(
                step_order=step_order,
                consistent=False,
                reasoning=f"JSON 无效: {exc}",
                confidence=0.0,
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )


completion_verifier = CompletionVerifier()
