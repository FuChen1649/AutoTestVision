import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.llm_factory import default_provider, llm_factory
from app.agent_test_service.schemas import ActionIntent
from app.config import settings
from app.result_verify_service.schemas import StepPurposeReview

logger = get_agent_logger()

PURPOSE_PROMPT = """你是移动端自动化测试结果分析专家。
根据步骤描述、执行操作信息，以及执行前/执行后截图，分析该步骤实际达成的目的与效果。
只返回 JSON：
{
  "purpose": "一句话概括本步执行目的/达成的界面变化",
  "reasoning": "结合截图变化与操作的详细分析",
  "confidence": 0-1
}
"""


def _normalize_image(url: str) -> str:
    return url if url.startswith("data:") else f"data:image/png;base64,{url}"


def _format_action(intent: ActionIntent | None) -> str:
    if intent is None:
        return "无操作信息"
    if intent.action == "skip":
        return "跳过（无 UI 操作）"
    if intent.action == "tap":
        return f"点击 ({intent.x}, {intent.y})"
    if intent.action == "long_press":
        return f"长按 ({intent.x}, {intent.y})，时长 {intent.duration_ms}ms"
    if intent.action == "swipe":
        return f"滑动 ({intent.x}, {intent.y}) → ({intent.x2}, {intent.y2})"
    return intent.action


class PurposeAnalyzer:
    async def analyze_step(
        self,
        *,
        step_order: int,
        description: str,
        intent: ActionIntent | None,
        before_image: str,
        after_image: str,
        provider: str | None = None,
    ) -> StepPurposeReview:
        chosen = provider or default_provider()
        model_override = settings.agent_verify_model or None
        llm = llm_factory.build(chosen, model_override=model_override)
        if llm is None:
            raise RuntimeError("未配置可用的验证模型")

        model_name = model_override or (
            settings.agent_local_model if chosen == "local" else settings.agent_llm_model
        )
        logger.info(
            "[purpose_analyzer] step=%d provider=%s model=%s",
            step_order + 1,
            chosen,
            model_name,
        )

        response = await llm.ainvoke(
            [
                SystemMessage(content=PURPOSE_PROMPT),
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": (
                                f"步骤序号：{step_order + 1}\n"
                                f"步骤描述：{description}\n"
                                f"执行操作：{_format_action(intent)}"
                            ),
                        },
                        {"type": "text", "text": "执行前截图："},
                        {"type": "image_url", "image_url": {"url": _normalize_image(before_image)}},
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
        return self._parse_result(step_order, str(raw), model_name)

    def _parse_result(self, step_order: int, raw: str, model_name: str) -> StepPurposeReview:
        from datetime import datetime, timezone

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return StepPurposeReview(
                step_order=step_order,
                purpose="分析失败",
                reasoning="模型输出无法解析",
                confidence=0.0,
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )
        try:
            payload = json.loads(match.group())
            return StepPurposeReview(
                step_order=step_order,
                purpose=str(payload.get("purpose", "")),
                reasoning=str(payload.get("reasoning", "")),
                confidence=float(payload.get("confidence", 0.0)),
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            return StepPurposeReview(
                step_order=step_order,
                purpose="分析失败",
                reasoning=f"JSON 无效: {exc}",
                confidence=0.0,
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )


purpose_analyzer = PurposeAnalyzer()
