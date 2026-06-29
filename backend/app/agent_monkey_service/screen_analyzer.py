from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent_test_service.llm_factory import llm_factory

ProgressCallback = Callable[[str, str], Awaitable[None]]

HOME_LAUNCHER_PROMPT = """你是 Android 主屏幕视觉定位（grounding）助手，只做一件事：在截图中找到指定应用图标的边界框。

## 坐标系（必须严格遵守）
- 原点：截图左上角 (0,0)
- 范围：x、y 均归一化到 0-1000
- 换算：x_pixel = round(x_norm / 1000 * 截图宽度)，y_pixel = round(y_norm / 1000 * 截图高度)
- 格式：[x1, y1, x2, y2]，(x1,y1)=左上角，(x2,y2)=右下角，且 x1<x2、y1<y2

## 输出（仅 JSON，无 markdown）
{
  "found": true,
  "visible_label": "图标下方实际文字（如 Phone、Messages）",
  "bbox": [x1, y1, x2, y2],
  "reasoning": "如何辨认该图标（颜色、位置、与相邻图标的区别）"
}

## 定位步骤（按顺序执行）
1. 找到底部 Dock 栏（屏幕最下方一排圆形应用图标，搜索栏上方）
2. 在 Dock 中按图标下方文字匹配目标应用（中英文别名均可）
3. 框选「圆形图标+下方文字」整体可点击区域，不要框相邻图标
4. 在 visible_label 填写你实际读到的文字；若读到的是别的应用名，设 found=false

## 常见 Dock 布局（从左到右，供空间参考）
电话/Phone → 信息/Messages → Chrome → 相册/Photos

## 禁止
- 禁止猜测：看不清或找不到时 found=false，bbox 省略
- 禁止把相邻图标当作目标（电话在最左，信息在其右侧紧邻）
- 禁止输出 candidates、screen_title 等额外字段
"""

HOME_LAUNCHER_GROUNDING_TEMPLATE = (
    "请在截图中定位应用图标：{target}\n"
    "别名：{aliases}\n"
    "截图尺寸：{width}x{height} 像素。\n"
    "请用 grounding 输出 bbox [[x1,y1,x2,y2]]，坐标 0-1000（x 相对宽、y 相对高）。\n"
    "务必核对图标下方 visible_label 是否与目标一致；不一致则 found=false。"
)

IN_APP_DISCOVERY_PROMPT = """你是 Android 应用内 UI 探索 Agent。目标应用已打开，识别当前屏幕内可点击元素。

## 坐标系
- bbox 格式：[x1, y1, x2, y2]，0-1000 归一化（x 相对截图宽，y 相对高）
- 原点在左上角；框要紧贴按钮/列表项/Tab 的可点击区域

## 输出（仅 JSON）
{
  "screen_title": "当前页面简短名称",
  "scrollable": false,
  "reached_bottom": true,
  "candidates": [
    {
      "element_title": "元素名称",
      "visible_label": "截图中实际可见文字",
      "suggested_action": "tap",
      "bbox": [x1, y1, x2, y2],
      "data_dependency": "无",
      "reasoning": "为何可点击"
    }
  ],
  "reasoning": "本屏识别说明"
}

## 规则
- 只列目标应用内部元素；排除系统状态栏、导航栏、桌面图标
- 每个 bbox 必须对应截图中真实可见的控件；visible_label 填实际文字
- suggested_action 仅 tap / long_press / swipe
- explore_state.known_elements：滚动后只补充新元素
- explore_state.parent_screen_elements：排除与父屏重复项
- 不要 markdown、不要代码块
"""

DISCOVERY_PROMPT = IN_APP_DISCOVERY_PROMPT

TRANSITION_PROMPT = """你是 Android UI 探索 Agent，负责判断「一次操作前后页面的关系」，从而决定探索树里子节点的归属。
你会收到两张截图：第一张是操作前页面，第二张是操作后页面，以及本次操作描述与一个算法初判 hint。

输出必须是单个 JSON 对象：
{
  "relation": "new_state",
  "screen_title": "操作后页面的简短名称",
  "same_as_known_title": null,
  "reasoning": "判断依据"
}

relation 只能是以下之一：
- "new_state"：操作打开了一个值得继续探索的新页面或新弹窗/对话框（页面主体内容发生了实质变化）
- "same_state"：仍停留在操作前的同一页面（仅局部变化，如选中态、内联展开、键盘弹出），不应新建子页面
- "revisit"：操作跳转到了一个“之前已经探索过”的页面（结合 hint.candidate_title 判断），不需要重复探索
- "no_effect"：操作没有产生任何可见效果（两张截图几乎一致）

规则：
- 从桌面/Home 点击应用图标进入应用，必须判为 new_state，不能判 same_state
- hint.algo_guess 是基于图像相似度的初步猜测，可参考但以你对界面语义的判断为准
- 弹窗/对话框/底部抽屉等覆盖层若有可交互内容，应判为 new_state
- 仅当确实回到已知页面时才用 revisit，并在 same_as_known_title 填入该已知页面标题
- screen_title 用简洁中文描述操作后页面
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
    async def discover_home_launcher(
        self,
        *,
        provider: str | None,
        target_app_name: str,
        step_index: int,
        max_steps: int,
        screenshot_data_url: str,
        screen_width: int,
        screen_height: int,
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        """主屏幕：只定位目标应用图标，用于启动应用。"""
        aliases = self._target_aliases_text(target_app_name)
        grounding_text = HOME_LAUNCHER_GROUNDING_TEMPLATE.format(
            target=target_app_name,
            aliases=aliases,
            width=screen_width,
            height=screen_height,
        )
        parsed = await self._invoke_grounding(
            provider=provider,
            system_prompt=HOME_LAUNCHER_PROMPT,
            phase_label="启动应用",
            screenshot_data_url=screenshot_data_url,
            grounding_text=grounding_text,
            on_progress=on_progress,
        )
        return self._normalize_home_grounding(parsed, target_app_name)

    def _target_aliases_text(self, target_app_name: str) -> str:
        target = (target_app_name or "").strip().lower()
        alias_map = {
            "电话": "Phone, Dialer, 拨号",
            "信息": "Messages, Message, 短信",
            "短信": "Messages, Message, 信息",
            "微信": "WeChat",
            "相机": "Camera",
            "设置": "Settings",
            "浏览器": "Chrome, Browser",
            "相册": "Photos, Gallery",
        }
        for key, aliases in alias_map.items():
            if key in target or target in key:
                return aliases
        return target_app_name

    async def _invoke_grounding(
        self,
        *,
        provider: str | None,
        system_prompt: str,
        phase_label: str,
        screenshot_data_url: str,
        grounding_text: str,
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        """专用 grounding 调用：图 + 定位指令，不混入 explore_state。"""
        llm = llm_factory.build(provider)
        if llm is None:
            raise RuntimeError("未配置可用 LLM provider")

        model_desc = llm_factory.describe(provider)
        if on_progress:
            await on_progress(
                f"[模型·{phase_label}] grounding 请求 {model_desc}",
                "model",
            )
        content: list[dict] = [
            {"type": "image_url", "image_url": {"url": screenshot_data_url}},
            {"type": "text", "text": grounding_text},
        ]
        started = time.perf_counter()
        response = await llm.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=content)]
        )
        elapsed = time.perf_counter() - started
        raw = response.content
        if isinstance(raw, list):
            raw = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw)
        raw_text = str(raw).strip()
        if on_progress:
            await on_progress(
                f"[模型·{phase_label}] grounding 响应（{len(raw_text)} 字符，{elapsed:.1f}s）",
                "model",
            )
        return self._parse_json(raw_text)

    def _normalize_home_grounding(self, parsed: dict, target_app_name: str) -> dict:
        """把 grounding 结果转为 discover 兼容格式，并校验 visible_label。"""
        target = target_app_name.strip()
        found = bool(parsed.get("found", True))
        visible = str(parsed.get("visible_label") or "").strip()
        bbox_raw = parsed.get("bbox") or parsed.get("box_2d") or parsed.get("box")

        if isinstance(bbox_raw, str):
            match = re.search(r"\[[\d\s,\.\-]+\]", bbox_raw)
            if match:
                try:
                    bbox_raw = json.loads(match.group().replace(" ", ""))
                except json.JSONDecodeError:
                    pass

        label_ok = not visible or self._title_matches_target(visible, target)
        if not found or not bbox_raw or not label_ok:
            return {
                "screen_title": "主屏幕",
                "candidates": [],
                "reasoning": parsed.get("reasoning")
                or (f"visible_label「{visible}」与目标「{target}」不符" if visible and not label_ok else "未找到目标图标"),
            }

        return {
            "screen_title": "主屏幕",
            "candidates": [
                {
                    "element_title": target,
                    "visible_label": visible,
                    "suggested_action": "tap",
                    "bbox": bbox_raw,
                    "data_dependency": "无",
                    "reasoning": str(parsed.get("reasoning") or f"grounding: {visible}"),
                }
            ],
            "reasoning": parsed.get("reasoning"),
        }

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
        return self._normalize_discovery_result(
            await self._invoke(
                provider=provider,
                system_prompt=IN_APP_DISCOVERY_PROMPT,
                phase_label="元素发现",
                target_app_name=target_app_name,
                step_index=step_index,
                max_steps=max_steps,
                explore_state={**explore_state, "phase": "discover"},
                screenshot_data_url=screenshot_data_url,
                screen_width=screen_width,
                screen_height=screen_height,
                on_progress=on_progress,
                user_hint=(
                    f"截图 {screen_width}x{screen_height}。"
                    f"应用「{target_app_name}」已打开。"
                    f"每个候选必须含 visible_label（截图中真实文字）和 bbox [x1,y1,x2,y2]（0-1000）。"
                ),
            ),
            target_app_name,
            home_launch=False,
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

    async def judge_transition(
        self,
        *,
        provider: str | None,
        target_app_name: str,
        step_index: int,
        action_title: str,
        action_type: str,
        before_data_url: str,
        after_data_url: str,
        algo_guess: str,
        candidate_title: str | None,
        known_titles: list[str],
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        """根据操作前后两张截图，判断这次交互产生的页面关系（AI 决定子节点归属）。"""
        llm = llm_factory.build(provider)
        if llm is None:
            raise RuntimeError("未配置可用 LLM provider")

        model_desc = llm_factory.describe(provider)
        if on_progress:
            await on_progress(
                f"[模型·交互归属] 请求 {model_desc} 判断「{action_title}」操作前后关系",
                "model",
            )
        payload = {
            "target_app_name": target_app_name,
            "step": step_index,
            "action": {"title": action_title, "type": action_type},
            "hint": {
                "algo_guess": algo_guess,
                "candidate_title": candidate_title,
            },
            "known_screen_titles": known_titles[:40],
        }
        content: list[dict] = [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False)},
            {"type": "text", "text": "操作前页面："},
            {"type": "image_url", "image_url": {"url": before_data_url}},
            {"type": "text", "text": "操作后页面："},
            {"type": "image_url", "image_url": {"url": after_data_url}},
        ]
        started = time.perf_counter()
        response = await llm.ainvoke(
            [SystemMessage(content=TRANSITION_PROMPT), HumanMessage(content=content)]
        )
        elapsed = time.perf_counter() - started
        raw = response.content
        if isinstance(raw, list):
            raw = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw)
        parsed = self._parse_json(str(raw))
        relation = str(parsed.get("relation") or "").strip()
        if relation not in {"new_state", "same_state", "revisit", "no_effect"}:
            relation = "new_state"
        parsed["relation"] = relation
        if on_progress:
            await on_progress(
                f"[模型·交互归属] 判定 relation={relation}"
                + (f"（{parsed.get('screen_title')}）" if parsed.get("screen_title") else "")
                + f"，耗时 {elapsed:.1f}s",
                "model",
            )
        return parsed

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
        user_hint: str | None = None,
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
            {"type": "image_url", "image_url": {"url": screenshot_data_url}},
            {
                "type": "text",
                "text": (
                    (user_hint + "\n\n") if user_hint else ""
                )
                + (
                    f"截图尺寸 {screen_width}x{screen_height} 像素。\n"
                    f"目标应用：{target_app_name}\n"
                    f"bbox 用 [x1,y1,x2,y2]（0-1000，x 相对宽 y 相对高）。\n"
                    f"任务上下文：{json.dumps(payload, ensure_ascii=False)}"
                ),
            },
        ]
        started = time.perf_counter()
        response = await llm.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=content)]
        )
        elapsed = time.perf_counter() - started
        raw = response.content
        if isinstance(raw, list):
            raw = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw)
        raw_text = str(raw).strip()
        if not raw_text and hasattr(response, "additional_kwargs"):
            reasoning = response.additional_kwargs.get("reasoning_content")
            if reasoning:
                raw_text = str(reasoning)
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

    def _normalize_discovery_result(
        self, parsed: dict, target_app_name: str, *, home_launch: bool
    ) -> dict:
        """规范化候选 bbox，主屏只保留目标应用。"""
        normalized: list[dict] = []
        for item in parsed.get("candidates") or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("element_title") or item.get("title") or "").strip()
            bbox_raw = item.get("bbox") or item.get("box_2d") or item.get("box")
            if isinstance(bbox_raw, str):
                match = re.search(r"\[[\d\s,\.\-]+\]", bbox_raw)
                if match:
                    try:
                        bbox_raw = json.loads(match.group().replace(" ", ""))
                    except json.JSONDecodeError:
                        pass
            normalized.append({**item, "element_title": title, "bbox": bbox_raw})

        if home_launch:
            target = target_app_name.strip()
            matched = [c for c in normalized if self._title_matches_target(c.get("element_title", ""), target)]
            visible_ok = [
                c
                for c in normalized
                if self._title_matches_target(str(c.get("visible_label") or c.get("element_title") or ""), target)
            ]
            normalized = (matched or visible_ok)[:1]
            # 不再强行把错误 bbox 的标题改成目标名

        parsed["candidates"] = normalized
        return parsed

    @staticmethod
    def _title_matches_target(title: str, target: str) -> bool:
        left = (title or "").strip().lower()
        right = (target or "").strip().lower()
        if not left or not right:
            return False
        if left == right or left in right or right in left:
            return True
        alias_groups = [
            ("电话", "phone", "dialer", "拨号"),
            ("微信", "wechat"),
            ("相机", "camera"),
            ("设置", "settings"),
            ("短信", "messages", "message"),
            ("浏览器", "chrome", "browser"),
        ]
        for group in alias_groups:
            if any(g in right for g in group):
                if any(g in left for g in group):
                    return True
        return False

    def _parse_json(self, raw: str) -> dict:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise RuntimeError("模型输出无法解析为 JSON")
        return json.loads(match.group())


monkey_screen_analyzer = MonkeyScreenAnalyzer()
