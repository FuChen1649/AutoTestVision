import json
import re
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.llm_factory import default_provider, llm_factory
from app.config import settings
from app.script_generation_service.verify_schemas import AssertionVerifyResult

logger = get_agent_logger()

ASSERTION_PROMPT = """你是移动端自动化测试断言验证器。
根据步骤描述（通常包含「期望」「出现」等断言语义）、当前屏幕截图与 UI 层级 XML，判断描述中的期望内容是否已在当前界面出现。
只返回 JSON：
{
  "success": true/false,
  "confidence": 0-1,
  "reasoning": "结合截图与 XML 的简短说明"
}
"""


def _normalize_image(url: str) -> str:
    return url if url.startswith("data:") else f"data:image/png;base64,{url}"


def _truncate_xml(xml: str | None, limit: int = 12000) -> str:
    if not xml:
        return "（无 UI XML）"
    text = xml.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...（XML 已截断）"


class AssertionAnalyzer:
    async def verify(
        self,
        *,
        step_order: int,
        description: str,
        screen_image: str,
        ui_xml: str | None,
        provider: str | None = None,
    ) -> AssertionVerifyResult:
        chosen = provider or default_provider()
        model_override = settings.agent_verify_model or None
        llm = llm_factory.build(chosen, model_override=model_override)
        if llm is None:
            raise RuntimeError("未配置可用的验证模型")

        model_name = model_override or (
            settings.agent_local_model if chosen == "local" else settings.agent_llm_model
        )
        logger.info(
            "[assertion_analyzer] step=%d provider=%s model=%s",
            step_order + 1,
            chosen,
            model_name,
        )

        response = await llm.ainvoke(
            [
                SystemMessage(content=ASSERTION_PROMPT),
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": (
                                f"步骤序号：{step_order + 1}\n"
                                f"步骤描述：{description}\n\n"
                                f"UI XML：\n{_truncate_xml(ui_xml)}"
                            ),
                        },
                        {"type": "text", "text": "当前屏幕截图："},
                        {"type": "image_url", "image_url": {"url": _normalize_image(screen_image)}},
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

    def _parse_result(self, step_order: int, raw: str, model_name: str) -> AssertionVerifyResult:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return AssertionVerifyResult(
                step_order=step_order,
                success=False,
                confidence=0.0,
                reasoning="模型输出无法解析",
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )
        try:
            payload = json.loads(match.group())
            return AssertionVerifyResult(
                step_order=step_order,
                success=bool(payload.get("success", False)),
                confidence=float(payload.get("confidence", 0.0)),
                reasoning=str(payload.get("reasoning", "")),
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            return AssertionVerifyResult(
                step_order=step_order,
                success=False,
                confidence=0.0,
                reasoning=f"JSON 无效: {exc}",
                model=model_name,
                reviewed_at=datetime.now(timezone.utc),
            )


assertion_analyzer = AssertionAnalyzer()
