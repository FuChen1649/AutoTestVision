from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.agent_monkey_service.schemas import BBox, Center
from app.agent_test_service.llm_factory import llm_factory


SYSTEM_PROMPT = """你是 Android UI 探索 Agent（AgentMonkeyTest）。
根据当前截图、已有探索树、操作历史，补充可点击元素，并选择下一步工具调用。

可用工具（tool_call.name）：
- go_home：回到主屏幕
- go_back：按返回键
- tap_coordinates：点击坐标，args: x,y（0-1000 相对坐标）
- tap_node：点击已记录节点，args: node_uuid
- navigate_to_node：按历史坐标逐步导航到某节点（会先 go_home 再沿路径点击），args: node_uuid
- stop：结束探索

输出必须是单个 JSON 对象：
{
  "current_screen": {
    "title": "当前屏幕名称",
    "screen_key": "唯一键",
    "is_new_screen": true/false
  },
  "discovered_nodes": [
    {
      "client_id": "tmp_1",
      "parent_client_id": "current_screen",
      "node_type": "app|element|screen|container",
      "title": "元素名",
      "bbox": {"x":0,"y":0,"w":80,"h":80},
      "clickable": true,
      "confidence": 0.9,
      "reasoning": "简短说明"
    }
  ],
  "tool_call": {
    "name": "tap_coordinates",
    "args": {"x": 500, "y": 300, "node_uuid": null},
    "reason": "为什么要执行"
  },
  "reasoning": "整体说明"
}

规则：
- bbox 使用 0-1000 相对坐标
- 优先探索与目标应用相关的未访问节点
- 若已在目标应用内，优先发现可点击 element
- 不要输出代码或 markdown
"""


class MonkeyScreenAnalyzer:
    async def analyze_step(
        self,
        *,
        provider: str | None,
        target_app_name: str,
        step_index: int,
        max_steps: int,
        tree_json: dict,
        action_history: list[dict],
        screenshot_data_url: str,
        screen_width: int,
        screen_height: int,
    ) -> dict:
        llm = llm_factory.build(provider)
        if llm is None:
            raise RuntimeError("未配置可用 LLM provider")

        payload = {
            "target_app_name": target_app_name,
            "step": step_index,
            "max_steps": max_steps,
            "screen_size": {"width": screen_width, "height": screen_height},
            "exploration_tree": tree_json,
            "action_history": action_history[-20:],
        }
        content: list[dict] = [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False)},
            {"type": "image_url", "image_url": {"url": screenshot_data_url}},
        ]
        response = await llm.ainvoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=content)]
        )
        raw = response.content
        if isinstance(raw, list):
            raw = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw)
        return self._parse_json(str(raw))

    def _parse_json(self, raw: str) -> dict:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise RuntimeError("模型输出无法解析为 JSON")
        return json.loads(match.group())


monkey_screen_analyzer = MonkeyScreenAnalyzer()
