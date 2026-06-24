from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent_test_service.llm_factory import llm_factory

ProgressCallback = Callable[[str, str], Awaitable[None]]

DISCOVERY_PROMPT = """你是 Android UI 迷宫探索 Agent（AgentMonkeyTest）。
当前任务：首次进入该屏幕，识别与目标应用相关的所有可探索元素。

输出必须是单个 JSON 对象：
{
  "target_app_on_screen": true,
  "screen_title": "当前屏幕名称",
  "candidates": [
    {
      "element_title": "相机",
      "suggested_action": "tap",
      "bbox": {"x": 100, "y": 200, "w": 80, "h": 80},
      "data_dependency": "无",
      "reasoning": "可点击图标"
    }
  ],
  "reasoning": "整体说明，含识别到的元素数量"
}

规则：
- bbox 使用 0-1000 相对坐标，数字将标注在 bbox 中心操作位置
- suggested_action 只能是 tap / long_press / swipe
- 一次性列出当前屏幕上所有与目标应用相关的可点击元素
- 若目标应用不在屏幕上，优先给出其桌面图标
- 不要输出 next_action_no、should_stop
- 不要输出代码或 markdown
"""

EXECUTE_PROMPT = """你是 Android UI 迷宫探索 Agent（AgentMonkeyTest）。
当前任务：辅助确认下一个待执行操作（可选补充 1 个新元素）。

输出必须是单个 JSON 对象：
{
  "screen_title": "当前屏幕名称",
  "candidates": [],
  "next_action_no": 1,
  "should_stop": false,
  "reasoning": "说明"
}

规则：
- candidates 仅补充尚未记录的新元素；无新元素则返回空数组
- next_action_no 必须对应当前屏幕 pending 的编号；优先最小 pending
- bbox 使用 0-1000 相对坐标
- 不要输出代码或 markdown
"""


class MonkeyScreenAnalyzer:
    async def discover_screen(
        self,
        *,
        provider: str | None,
        target_app_name: str,
        step_index: int,
        max_steps: int,
        explore_state: dict,
        screenshot_data_url: str,
        screen_width: int,
        screen_height: int,
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        return await self._invoke(
            provider=provider,
            system_prompt=DISCOVERY_PROMPT,
            phase_label="元素发现",
            target_app_name=target_app_name,
            step_index=step_index,
            max_steps=max_steps,
            explore_state={**explore_state, "phase": "discover"},
            screenshot_data_url=screenshot_data_url,
            screen_width=screen_width,
            screen_height=screen_height,
            on_progress=on_progress,
        )

    async def analyze_step(
        self,
        *,
        provider: str | None,
        target_app_name: str,
        step_index: int,
        max_steps: int,
        explore_state: dict,
        screenshot_data_url: str,
        screen_width: int,
        screen_height: int,
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        return await self._invoke(
            provider=provider,
            system_prompt=EXECUTE_PROMPT,
            phase_label="执行辅助",
            target_app_name=target_app_name,
            step_index=step_index,
            max_steps=max_steps,
            explore_state={**explore_state, "phase": "execute"},
            screenshot_data_url=screenshot_data_url,
            screen_width=screen_width,
            screen_height=screen_height,
            on_progress=on_progress,
        )

    async def _invoke(
        self,
        *,
        provider: str | None,
        system_prompt: str,
        phase_label: str,
        target_app_name: str,
        step_index: int,
        max_steps: int,
        explore_state: dict,
        screenshot_data_url: str,
        screen_width: int,
        screen_height: int,
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        llm = llm_factory.build(provider)
        if llm is None:
            raise RuntimeError("未配置可用 LLM provider")

        model_desc = llm_factory.describe(provider)
        if on_progress:
            await on_progress(
                f"[模型·{phase_label}] 请求 {model_desc}，截图 {screen_width}x{screen_height}",
                "model",
            )

        payload = {
            "target_app_name": target_app_name,
            "step": step_index,
            "max_steps": max_steps if max_steps > 0 else None,
            "screen_size": {"width": screen_width, "height": screen_height},
            "explore_state": explore_state,
        }
        content: list[dict] = [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False)},
            {"type": "image_url", "image_url": {"url": screenshot_data_url}},
        ]
        started = time.perf_counter()
        response = await llm.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=content)]
        )
        elapsed = time.perf_counter() - started
        raw = response.content
        if isinstance(raw, list):
            raw = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw)
        raw_text = str(raw)
        if on_progress:
            await on_progress(
                f"[模型·{phase_label}] 收到响应（{len(raw_text)} 字符，耗时 {elapsed:.1f}s），解析 JSON…",
                "model",
            )
        parsed = self._parse_json(raw_text)
        candidate_count = len(parsed.get("candidates") or [])
        if on_progress:
            await on_progress(
                f"[模型·{phase_label}] 解析完成：{candidate_count} 个候选元素"
                + (f"，屏幕标题「{parsed.get('screen_title')}」" if parsed.get("screen_title") else ""),
                "model",
            )
        return parsed

    def _parse_json(self, raw: str) -> dict:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise RuntimeError("模型输出无法解析为 JSON")
        return json.loads(match.group())


monkey_screen_analyzer = MonkeyScreenAnalyzer()
