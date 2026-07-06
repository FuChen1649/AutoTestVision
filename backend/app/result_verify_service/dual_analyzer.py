import json
import re
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent_test_code_service.schemas import GeneratedStepCode
from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.llm_factory import default_provider, llm_factory
from app.agent_test_service.schemas import ActionIntent
from app.config import settings
from app.result_verify_service.schemas import DualStepVerifyReview

logger = get_agent_logger()

DUAL_VERIFY_PROMPT = """你是移动端双脚本自动化测试验证专家。
同一步骤会通过两种实现方式执行：
- Position 路径：视觉坐标 / 意图驱动点击
- Code 路径：uiautomator2 代码选择器

两种方式实现不同，但**屏幕表现理论上应一致**。你会收到该步骤的描述、两侧的执行前/执行后截图。

请判断：
1. Position 执行前后是否体现步骤意图
2. Code 执行前后是否体现步骤意图
3. 两侧「执行前」界面是否一致（允许分辨率、状态栏等微小差异）
4. 两侧「执行后」界面是否一致（这是双脚本一致性的核心）

只返回 JSON：
{
  "consistent": true,
  "before_match": true,
  "after_match": true,
  "purpose": "一句话概括本步应达成的界面效果",
  "reasoning": "结合四张截图的对比分析，说明一致或不一致的原因",
  "confidence": 0-1
}
"""


def _normalize_image(url: str) -> str:
    return url if url.startswith("data:") else f"data:image/png;base64,{url}"


def _format_position_action(intent_json: str | None) -> str:
    if not intent_json:
        return "无操作记录"
    try:
        intent = ActionIntent.model_validate_json(intent_json)
    except Exception:
        return "无操作记录"
    if intent.action == "tap":
        return f"点击 ({intent.x}, {intent.y})"
    if intent.action == "long_press":
        return f"长按 ({intent.x}, {intent.y})"
    if intent.action == "swipe":
        return f"滑动 ({intent.x}, {intent.y}) → ({intent.x2}, {intent.y2})"
    if intent.action == "skip":
        return "跳过"
    return intent.action


def _format_code_action(generated_json: str | None) -> str:
    if not generated_json:
        return "无代码记录"
    try:
        generated = GeneratedStepCode.model_validate_json(generated_json)
        return generated.code_line or "无代码记录"
    except Exception:
        return "无代码记录"


class DualStepAnalyzer:
    async def analyze_step(
        self,
        *,
        step_order: int,
        description: str,
        position_before: str,
        position_after: str,
        code_before: str,
        code_after: str,
        position_action: str,
        code_action: str,
        provider: str | None = None,
    ) -> DualStepVerifyReview:
        chosen = provider or default_provider()
        model_override = settings.agent_verify_model or None
        llm = llm_factory.build(chosen, model_override=model_override)
        if llm is None:
            raise RuntimeError("未配置可用的验证模型")

        model_name = model_override or (
            settings.agent_local_model if chosen == "local" else settings.agent_llm_model
        )
        logger.info(
            "[dual_analyzer] step=%d provider=%s model=%s",
            step_order + 1,
            chosen,
            model_name,
        )

        response = await llm.ainvoke(
            [
                SystemMessage(content=DUAL_VERIFY_PROMPT),
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": (
                                f"步骤序号：{step_order + 1}\n"
                                f"步骤描述：{description}\n"
                                f"Position 操作：{position_action}\n"
                                f"Code 操作：{code_action}\n\n"
                                "以下四张图按顺序为：Position 执行前、Position 执行后、Code 执行前、Code 执行后。"
                            ),
                        },
                        {"type": "text", "text": "Position 执行前："},
                        {"type": "image_url", "image_url": {"url": _normalize_image(position_before)}},
                        {"type": "text", "text": "Position 执行后："},
                        {"type": "image_url", "image_url": {"url": _normalize_image(position_after)}},
                        {"type": "text", "text": "Code 执行前："},
                        {"type": "image_url", "image_url": {"url": _normalize_image(code_before)}},
                        {"type": "text", "text": "Code 执行后："},
                        {"type": "image_url", "image_url": {"url": _normalize_image(code_after)}},
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

    def _parse_result(self, step_order: int, raw: str, model_name: str) -> DualStepVerifyReview:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return DualStepVerifyReview(
                step_order=step_order,
                consistent=False,
                before_match=False,
                after_match=False,
                purpose="分析失败",
                reasoning="模型输出无法解析",
                confidence=0.0,
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )
        try:
            payload = json.loads(match.group())
            return DualStepVerifyReview(
                step_order=step_order,
                consistent=bool(payload.get("consistent", False)),
                before_match=bool(payload.get("before_match", False)),
                after_match=bool(payload.get("after_match", False)),
                purpose=str(payload.get("purpose", "")),
                reasoning=str(payload.get("reasoning", "")),
                confidence=float(payload.get("confidence", 0.0)),
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            return DualStepVerifyReview(
                step_order=step_order,
                consistent=False,
                before_match=False,
                after_match=False,
                purpose="分析失败",
                reasoning=f"JSON 无效: {exc}",
                confidence=0.0,
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )


dual_step_analyzer = DualStepAnalyzer()
