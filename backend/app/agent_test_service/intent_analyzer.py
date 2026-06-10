import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.llm_factory import llm_factory
from app.agent_test_service.schemas import ActionIntent, AnalyzeIntentRequest

logger = get_agent_logger()


SYSTEM_PROMPT = """你是移动端 UI 自动化测试的多模态意图分析器。
根据单步自然语言描述和屏幕截图，判断需要执行的人为操作，只返回 JSON，不要生成脚本。

输出 JSON 格式：
{
  "action": "tap" | "swipe" | "long_press" | "skip",
  "x": 整数,
  "y": 整数,
  "x2": 整数或 null,
  "y2": 整数或 null,
  "duration_ms": 整数,
  "confidence": 0-1,
  "reasoning": "简短说明"
}

规则：
- 坐标基于当前截图像素，左上角为 (0,0)
- 点击用 tap，拖拽/滑动用 swipe 并提供终点 x2,y2
- 长按用 long_press
- 权限类、无需 UI 操作时用 skip
- 不要输出代码或 shell 命令
"""


class IntentAnalyzer:
    async def analyze(
        self, request: AnalyzeIntentRequest, *, provider: str | None = None
    ) -> ActionIntent:
        chosen = provider or request.llm_provider
        llm = llm_factory.build(chosen)
        mode = f"llm:{chosen or 'default'}" if llm is not None else "heuristic"
        logger.info("[intent_analyzer] 开始分析 mode=%s desc=%s", mode, request.step_description[:80])
        if llm is not None:
            try:
                intent = await self._analyze_with_llm(llm, request)
                logger.info("[intent_analyzer] LLM 分析完成 provider=%s action=%s", chosen, intent.action)
                return intent
            except Exception as exc:
                logger.warning(
                    "[intent_analyzer] LLM(%s) 失败，回退启发式: %s", chosen, exc
                )
                return self._analyze_with_heuristic(request, fallback_reason=str(exc))
        intent = self._analyze_with_heuristic(request)
        logger.info("[intent_analyzer] 启发式分析完成 action=%s", intent.action)
        return intent

    async def _analyze_with_llm(
        self, llm: ChatOpenAI, request: AnalyzeIntentRequest
    ) -> ActionIntent:
        image_url = request.screen_image
        if not image_url.startswith("data:"):
            image_url = f"data:image/png;base64,{image_url}"

        content: list[dict] = [
            {
                "type": "text",
                "text": (
                    f"步骤描述：{request.step_description}\n"
                    f"截图尺寸：{request.screen_width}x{request.screen_height}"
                ),
            },
            {"type": "image_url", "image_url": {"url": image_url}},
        ]

        if request.reference_image:
            ref_url = request.reference_image
            if not ref_url.startswith("data:"):
                ref_url = f"data:image/png;base64,{ref_url}"
            content.append({"type": "text", "text": "参考区域截图（用户框选）："})
            content.append({"type": "image_url", "image_url": {"url": ref_url}})

        response = await llm.ainvoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=content),
            ]
        )
        raw = response.content
        if isinstance(raw, list):
            raw = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw)
        return self._parse_intent(str(raw), request)

    def _analyze_with_heuristic(
        self, request: AnalyzeIntentRequest, fallback_reason: str | None = None
    ) -> ActionIntent:
        text = request.step_description.lower()
        width = request.screen_width
        height = request.screen_height

        if "权限" in request.step_description or request.step_description.strip() == "应用权限修改":
            return ActionIntent(
                action="skip",
                confidence=0.9,
                reasoning="权限前置步骤，无需 UI 操作",
            )

        if request.reference_x is not None and request.reference_y is not None:
            ref_w = request.reference_width or 1
            ref_h = request.reference_height or 1
            x = request.reference_x + ref_w // 2
            y = request.reference_y + ref_h // 2
        else:
            x = width // 2
            y = height // 2

        if any(keyword in text for keyword in ("滑动", "swipe", "拖拽", "拖动")):
            return ActionIntent(
                action="swipe",
                x=x,
                y=int(height * 0.7),
                x2=x,
                y2=int(height * 0.3),
                duration_ms=400,
                confidence=0.55,
                reasoning=fallback_reason or "启发式：识别为向上滑动",
            )

        if any(keyword in text for keyword in ("长按", "long press", "long_press")):
            return ActionIntent(
                action="long_press",
                x=x,
                y=y,
                duration_ms=800,
                confidence=0.55,
                reasoning=fallback_reason or "启发式：识别为长按",
            )

        return ActionIntent(
            action="tap",
            x=x,
            y=y,
            confidence=0.55,
            reasoning=fallback_reason or "启发式：默认识别为点击",
        )

    def _parse_intent(self, raw: str, request: AnalyzeIntentRequest) -> ActionIntent:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return self._analyze_with_heuristic(request, fallback_reason="模型输出无法解析")
        try:
            payload = json.loads(match.group())
            intent = ActionIntent.model_validate(payload)
            if intent.action != "skip" and intent.x is not None and intent.y is not None:
                intent.x = max(0, min(intent.x, request.screen_width - 1))
                intent.y = max(0, min(intent.y, request.screen_height - 1))
            return intent
        except Exception:
            return self._analyze_with_heuristic(request, fallback_reason="模型 JSON 无效")


intent_analyzer = IntentAnalyzer()
