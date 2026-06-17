from __future__ import annotations

import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.agent_test_code_service.schemas import AnalyzeCodeRequest, GeneratedStepCode
from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.llm_factory import llm_factory
from app.agent_test_service.log_stream import emit as emit_live

logger = get_agent_logger()

CODE_SYSTEM_PROMPT = """你是 Android UI 自动化专家，使用 uiautomator2 Python API。
根据步骤描述、屏幕截图和 UI 层级 XML，生成**单行**可执行代码。
设备对象已定义为 `d`（u2.connect 已连接），你只输出操作那一行。

只返回 JSON：
{
  "code_line": "d(text=\\"相机\\").click()",
  "confidence": 0-1,
  "reasoning": "简短说明"
}

规则：
- 只生成一行，不要 import、不要 def、不要多行
- 优先 text / resourceId / description 等稳定选择器
- 滑动用 d.swipe(sx, sy, ex, ey, duration)，duration 建议 0.3~0.8（秒）
- 坐标用像素值，结合截图尺寸计算（如 720 宽屏左滑可从 x=576 到 x=144）
- 无法操作时 code_line 可为 d.sleep(0.5) 并在 reasoning 说明
- 不要 markdown 代码块
"""


class CodeGenerator:
    async def analyze(self, request: AnalyzeCodeRequest, *, provider: str | None = None) -> GeneratedStepCode:
        chosen = provider or request.llm_provider
        llm = llm_factory.build(chosen)
        if llm is None:
            raise RuntimeError("未配置可用的代码生成模型")

        image_url = request.screen_image
        if not image_url.startswith("data:"):
            image_url = f"data:image/png;base64,{image_url}"

        xml_preview = (request.ui_xml or "")[:12000]
        emit_live(
            "intent",
            f"代码 Agent 分析步骤: {request.step_description[:80]}",
            detail={"provider": chosen, "xml_len": len(request.ui_xml or "")},
        )

        content: list[dict] = [
            {
                "type": "text",
                "text": (
                    f"步骤描述：{request.step_description}\n"
                    f"截图尺寸：{request.screen_width}x{request.screen_height}\n"
                    f"UI XML（节选）：\n{xml_preview}"
                ),
            },
            {"type": "image_url", "image_url": {"url": image_url}},
        ]

        response = await llm.ainvoke(
            [SystemMessage(content=CODE_SYSTEM_PROMPT), HumanMessage(content=content)]
        )
        raw = response.content
        if isinstance(raw, list):
            raw = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw)
        return self._parse_code(str(raw), request.step_description)

    def _parse_code(self, raw: str, description: str) -> GeneratedStepCode:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise RuntimeError(f"模型输出无法解析: {raw[:200]}")
        payload = json.loads(match.group())
        code_line = str(payload.get("code_line", "")).strip()
        if not code_line:
            raise RuntimeError("模型未返回 code_line")
        code_line = code_line.replace("```python", "").replace("```", "").strip()
        if "\n" in code_line:
            code_line = code_line.splitlines()[0].strip()
        return GeneratedStepCode(
            code_line=code_line,
            confidence=float(payload.get("confidence", 0.7)),
            reasoning=str(payload.get("reasoning", "")),
        )


code_generator = CodeGenerator()

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_step_test_file(
    *,
    run_uuid: str,
    step_order: int,
    description: str,
    serial: str,
    code_line: str,
) -> Path:
    from app.config import settings

    workspace = (Path(settings.agent_code_workspace_dir) / run_uuid).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    template = _jinja_env.get_template("u2_step_test.py.j2")
    body = template.render(
        step_order=step_order,
        description=description,
        serial=serial,
        code_line=code_line,
    )
    out_path = workspace / f"step_{step_order:03d}_test.py"
    out_path.write_text(body, encoding="utf-8")
    logger.info("[template_manager] 写入 %s", out_path)
    return out_path
