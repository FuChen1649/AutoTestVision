import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.coordinate_mapper import (
    decode_image_size,
    model_coords_to_image_pixels,
    uses_normalized_1000_coords,
)
from app.agent_test_service.llm_factory import llm_factory
from app.agent_test_service.log_stream import emit as emit_live
from app.agent_test_service.schemas import ActionIntent, AnalyzeIntentRequest
from app.config import settings

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
- 坐标使用相对坐标系 0-1000（相对截图宽高），左上角 (0,0)，右下角 (1000,1000)
- x、y 必须是目标控件中心点；底部 Dock 图标 y 通常在 780-920 之间，「电话」在 Dock 最左侧 x 约 50-150
- 点击用 tap，拖拽/滑动用 swipe 并提供终点 x2,y2
- 长按用 long_press
- 权限类、无需 UI 操作时用 skip
- 不要输出代码或 shell 命令
"""


class IntentAnalyzer:
    async def analyze(
        self, request: AnalyzeIntentRequest, *, provider: str | None = None
    ) -> ActionIntent:
        if getattr(request, "step_type", None) == "permission_preset":
            emit_live("intent", "权限步骤应走工具链，跳过 LLM 分析")
            return ActionIntent(
                action="skip",
                confidence=0.0,
                reasoning="权限步骤应由 tools.apply_app_permissions 处理",
            )
        chosen = provider or request.llm_provider
        llm = llm_factory.build(chosen)
        mode = f"llm:{chosen or 'default'}" if llm is not None else "heuristic"
        logger.info("[intent_analyzer] 开始分析 mode=%s desc=%s", mode, request.step_description[:80])

        if llm is not None:
            model_name = self._model_name(chosen)
            emit_live(
                "intent",
                f"准备调用模型 provider={chosen or 'default'} model={model_name}",
                detail={"provider": chosen or "default", "model": model_name},
            )
            try:
                intent = await self._analyze_with_llm(llm, request, provider=chosen)
                logger.info("[intent_analyzer] LLM 分析完成 provider=%s action=%s", chosen, intent.action)
                emit_live(
                    "intent",
                    f"模型解析成功 action={intent.action}",
                    detail={"action": intent.action, "confidence": intent.confidence},
                )
                return intent
            except Exception as exc:
                logger.warning(
                    "[intent_analyzer] LLM(%s) 失败，回退启发式: %s", chosen, exc
                )
                emit_live(
                    "intent",
                    f"LLM 调用失败，回退启发式分析: {exc}",
                    detail={"error": str(exc)},
                )
                return self._analyze_with_heuristic(request, fallback_reason=str(exc))
        emit_live("intent", "未配置可用 LLM，使用启发式分析")
        intent = self._analyze_with_heuristic(request)
        logger.info("[intent_analyzer] 启发式分析完成 action=%s", intent.action)
        return intent

    def _model_name(self, provider: str | None) -> str:
        if provider == "local":
            return settings.agent_local_model
        if provider == "online":
            return settings.agent_llm_model
        # 默认/未指定时，按 default_provider 实际生效的猜测；展示用，差一点不致命
        return settings.agent_local_model if not settings.agent_llm_api_key else settings.agent_llm_model

    async def _analyze_with_llm(
        self, llm: ChatOpenAI, request: AnalyzeIntentRequest, *, provider: str | None = None
    ) -> ActionIntent:
        image_url = request.screen_image
        if not image_url.startswith("data:"):
            image_url = f"data:image/png;base64,{image_url}"

        try:
            actual_width, actual_height = decode_image_size(image_url)
        except Exception:
            actual_width, actual_height = request.screen_width, request.screen_height

        if (actual_width, actual_height) != (request.screen_width, request.screen_height):
            logger.warning(
                "[intent_analyzer] 截图尺寸不一致 declared=%dx%d actual=%dx%d",
                request.screen_width,
                request.screen_height,
                actual_width,
                actual_height,
            )

        coord_hint = (
            "坐标请输出 0-1000 相对值（相对截图宽高）"
            if uses_normalized_1000_coords(provider=provider)
            else "坐标基于当前截图像素，左上角为 (0,0)"
        )

        content: list[dict] = [
            {
                "type": "text",
                "text": (
                    f"步骤描述：{request.step_description}\n"
                    f"截图尺寸：{actual_width}x{actual_height}\n"
                    f"{coord_hint}"
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

        emit_live(
            "intent",
            f"已发送截图（{actual_width}x{actual_height}），等待模型响应...",
            detail={
                "has_reference": request.reference_image is not None,
                "declared_size": f"{request.screen_width}x{request.screen_height}",
                "actual_size": f"{actual_width}x{actual_height}",
            },
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=content),
            ]
        )
        raw = response.content
        if isinstance(raw, list):
            raw = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw)
        raw_str = str(raw)
        emit_live(
            "intent",
            f"收到模型响应（{len(raw_str)} 字符），开始解析 JSON",
            detail={"raw_preview": raw_str[:200]},
        )
        return self._parse_intent(raw_str, request, provider=provider)

    def _analyze_with_heuristic(
        self, request: AnalyzeIntentRequest, fallback_reason: str | None = None
    ) -> ActionIntent:
        text = request.step_description.lower()
        width = request.screen_width
        height = request.screen_height

        if "权限" in request.step_description or request.step_description.strip() == "应用权限修改":
            emit_live("intent", "识别为权限类步骤，跳过 LLM 分析")
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

    def _parse_intent(
        self, raw: str, request: AnalyzeIntentRequest, *, provider: str | None = None
    ) -> ActionIntent:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return self._analyze_with_heuristic(request, fallback_reason="模型输出无法解析")
        try:
            payload = json.loads(match.group())
            intent = ActionIntent.model_validate(payload)
            if intent.action == "skip" or intent.x is None or intent.y is None:
                return intent

            try:
                image_width, image_height = decode_image_size(request.screen_image)
            except Exception:
                image_width, image_height = request.screen_width, request.screen_height

            model_name = self._model_name(provider)
            return model_coords_to_image_pixels(
                intent,
                image_width,
                image_height,
                provider=provider,
                model_name=model_name,
            )
        except Exception:
            return self._analyze_with_heuristic(request, fallback_reason="模型 JSON 无效")


intent_analyzer = IntentAnalyzer()
