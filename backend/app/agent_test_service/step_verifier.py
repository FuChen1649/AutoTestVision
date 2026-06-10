import base64
import json
import re
from io import BytesIO

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from PIL import Image, ImageChops

from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.llm_factory import llm_factory
from app.agent_test_service.schemas import ActionIntent, VerificationResult
from app.config import settings

logger = get_agent_logger()


VERIFY_PROMPT = """你是移动端自动化测试验证器。
对比执行前和执行后截图，以及步骤描述，判断该步骤是否执行成功。
只返回 JSON：
{
  "success": true/false,
  "confidence": 0-1,
  "reasoning": "简短说明"
}
"""


class StepVerifier:
    async def verify(
        self,
        step_description: str,
        intent: ActionIntent,
        before_image: str,
        after_image: str,
        *,
        provider: str | None = None,
    ) -> VerificationResult:
        if intent.action == "skip":
            logger.info("[step_verifier] 跳过验证")
            return VerificationResult(
                success=True,
                confidence=1.0,
                reasoning="跳过类步骤自动通过",
            )

        # 验证用模型：优先 agent_verify_model；否则跟随 provider 默认 model。
        verify_model_override = settings.agent_verify_model or None
        llm = llm_factory.build(provider, model_override=verify_model_override)
        mode = f"llm:{provider or 'default'}" if llm is not None else "diff"
        logger.info("[step_verifier] 开始验证 mode=%s desc=%s", mode, step_description[:80])
        if llm is not None:
            try:
                result = await self._verify_with_llm(llm, step_description, before_image, after_image)
                logger.info(
                    "[step_verifier] LLM 验证 provider=%s success=%s", provider, result.success
                )
                return result
            except Exception as exc:
                logger.warning(
                    "[step_verifier] LLM(%s) 失败，回退像素差异: %s", provider, exc
                )
                return self._verify_with_diff(before_image, after_image, fallback_reason=str(exc))

        result = self._verify_with_diff(before_image, after_image)
        logger.info("[step_verifier] 像素差异验证 success=%s", result.success)
        return result

    async def _verify_with_llm(
        self,
        llm: ChatOpenAI,
        step_description: str,
        before_image: str,
        after_image: str,
    ) -> VerificationResult:

        def normalize(url: str) -> str:
            return url if url.startswith("data:") else f"data:image/png;base64,{url}"

        response = await llm.ainvoke(
            [
                SystemMessage(content=VERIFY_PROMPT),
                HumanMessage(
                    content=[
                        {"type": "text", "text": f"步骤描述：{step_description}"},
                        {"type": "text", "text": "执行前截图："},
                        {"type": "image_url", "image_url": {"url": normalize(before_image)}},
                        {"type": "text", "text": "执行后截图："},
                        {"type": "image_url", "image_url": {"url": normalize(after_image)}},
                    ]
                ),
            ]
        )
        raw = response.content
        if isinstance(raw, list):
            raw = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw)
        return self._parse_result(str(raw))

    def _verify_with_diff(
        self, before_image: str, after_image: str, fallback_reason: str | None = None
    ) -> VerificationResult:
        before = self._load_image(before_image)
        after = self._load_image(after_image)

        if before.size != after.size:
            after = after.resize(before.size)

        diff = ImageChops.difference(before, after)
        histogram = diff.histogram()
        changed_pixels = sum(histogram[1:]) / 3
        total_pixels = before.size[0] * before.size[1]
        change_ratio = changed_pixels / max(total_pixels, 1)

        success = change_ratio > 0.002
        return VerificationResult(
            success=success,
            confidence=0.6 if success else 0.4,
            reasoning=fallback_reason
            or (
                f"启发式像素差异验证，变化比例 {change_ratio:.4f}"
                if success
                else "启发式验证：屏幕无明显变化"
            ),
        )

    def _load_image(self, data_url: str) -> Image.Image:
        payload = data_url.split(",", 1)[-1]
        image_bytes = base64.b64decode(payload)
        with Image.open(BytesIO(image_bytes)) as image:
            return image.convert("RGB")

    def _parse_result(self, raw: str) -> VerificationResult:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return VerificationResult(success=False, confidence=0.0, reasoning="验证器输出无法解析")
        try:
            payload = json.loads(match.group())
            return VerificationResult.model_validate(payload)
        except Exception:
            return VerificationResult(success=False, confidence=0.0, reasoning="验证器 JSON 无效")


step_verifier = StepVerifier()
