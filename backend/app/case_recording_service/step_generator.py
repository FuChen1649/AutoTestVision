from __future__ import annotations

import base64
import json
import re
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_test_service.image_annotation import annotate_before_image
from app.agent_test_service.llm_factory import llm_factory
from app.agent_test_service.schemas import ActionIntent
from app.case_recording_service.recording_annotation import annotate_recording_display, display_image_filename
from app.case_recording_service.repository import asset_url, case_recording_repository
from app.case_recording_service.schemas import GeneratedStepDraft
from app.models.case_recording import CaseRecordingEvent, CaseRecordingSession

SYSTEM_PROMPT = """你是移动端 UI 自动化测试的步骤编写助手。
用户录制了手机操作（截图中已标注操作位置），请反向生成一条与「正向 Case 步骤」一致风格的自然语言描述。

正向 Case 单步格式：动作 + 屏幕方位 + 可见特征（文字 / 图标 / 颜色 / 形状）
示例：
- 点击屏幕右上角蓝色的设置图标
- 点击左下角的 iPhone 图标
- 点击可见文字「WLAN」
- 向下滑动列表
- 长按首页搜索框
- 按下返回键

规则：
- 根据标注位置，判断用户点击/滑动的是哪个可见 UI 元素
- 必须写出屏幕方位（如左上角、右下角、屏幕中间、底部 Dock 等）
- 优先描述用户可见的文字、App 名、图标含义、按钮文案、颜色特征
- 禁止使用 Android 控件类名（LinearLayout、TextView 等）、resource-id、包名
- 禁止输出坐标数字
- 滑动需描述方向、幅度和目的
- 系统键（返回/主屏/最近任务）直接自然语言描述
- 只返回 JSON，不要 markdown 代码块

输出格式：
{"description": "点击左下角的 iPhone 图标"}
"""

StepSource = Literal["llm", "fallback"]


def screen_position_label(x: int | None, y: int | None, width: int | None, height: int | None) -> str:
    if x is None or y is None or not width or not height:
        return "屏幕"
    rx = x / width
    ry = y / height
    horizontal = "左侧" if rx < 0.33 else "中间" if rx < 0.67 else "右侧"
    vertical = "上方" if ry < 0.33 else "中部" if ry < 0.67 else "下方"
    if rx < 0.33 and ry < 0.33:
        return "左上角"
    if rx > 0.67 and ry < 0.33:
        return "右上角"
    if rx < 0.33 and ry > 0.67:
        return "左下角"
    if rx > 0.67 and ry > 0.67:
        return "右下角"
    if ry > 0.67:
        return f"底部{horizontal.replace('中间', '')}" if horizontal != "中间" else "底部"
    if ry < 0.33:
        return f"顶部{horizontal.replace('中间', '')}" if horizontal != "中间" else "顶部"
    return f"屏幕{vertical}{horizontal}"


class RecordingStepGenerator:
    async def generate(
        self,
        db: AsyncSession,
        session: CaseRecordingSession,
        events: list[CaseRecordingEvent],
        *,
        provider: str | None = None,
    ) -> list[GeneratedStepDraft]:
        if not events:
            return []

        await case_recording_repository.add_log(
            db,
            session,
            log_type="generate_start",
            message=f"开始生成 {len(events)} 条自然语言步骤",
            detail={"provider": provider, "event_count": len(events)},
        )

        drafts: list[GeneratedStepDraft] = []
        for event in events:
            description, source, llm_meta = await self._generate_single_step(
                db, session, event, provider=provider
            )
            screen_url, sel_x, sel_y, sel_w, sel_h = self._build_display_image(session, event)
            drafts.append(
                GeneratedStepDraft(
                    step_order=event.step_order,
                    description=description,
                    event_uuid=event.event_uuid,
                    screen_image_url=screen_url,
                    screen_width=event.device_width,
                    screen_height=event.device_height,
                    selection_x=sel_x,
                    selection_y=sel_y,
                    selection_width=sel_w,
                    selection_height=sel_h,
                )
            )
            await case_recording_repository.add_log(
                db,
                session,
                log_type="step_result",
                step_order=event.step_order,
                message=f"步骤 {event.step_order + 1} 生成完成",
                detail={
                    "event_uuid": event.event_uuid,
                    "description": description,
                    "source": source,
                    "before_image": event.before_image_path,
                    "after_image": event.after_image_path,
                    "screen_image_url": screen_url,
                    **llm_meta,
                },
            )

        await case_recording_repository.add_log(
            db,
            session,
            log_type="generate_done",
            message=f"全部 {len(drafts)} 条步骤生成完成",
            detail={"step_count": len(drafts)},
        )
        return drafts

    def _build_display_image(
        self, session: CaseRecordingSession, event: CaseRecordingEvent
    ) -> tuple[str | None, int | None, int | None, int | None, int | None]:
        before_image = case_recording_repository.read_image_data_uri(
            session.session_uuid, event.before_image_path
        )
        if not before_image:
            return (
                asset_url(session.session_uuid, event.before_image_path),
                event.x,
                event.y,
                48 if event.x is not None else None,
                48 if event.y is not None else None,
            )

        annotated, sel_x, sel_y, sel_w, sel_h = annotate_recording_display(before_image, event)
        filename = display_image_filename(event.step_order)
        if "," in annotated:
            encoded = annotated.split(",", 1)[1]
        else:
            encoded = annotated
        case_recording_repository.save_png(session.session_uuid, filename, base64.b64decode(encoded))
        return asset_url(session.session_uuid, filename), sel_x, sel_y, sel_w, sel_h

    async def _generate_single_step(
        self,
        db: AsyncSession,
        session: CaseRecordingSession,
        event: CaseRecordingEvent,
        *,
        provider: str | None,
    ) -> tuple[str, StepSource, dict]:
        step_no = event.step_order + 1
        operation = self._operation_context(event)
        await case_recording_repository.add_log(
            db,
            session,
            log_type="step_start",
            step_order=event.step_order,
            message=f"开始生成步骤 {step_no}",
            detail={"event_uuid": event.event_uuid, "operation": operation},
        )

        llm = llm_factory.build(provider)
        if llm is None:
            fallback = self._fallback_description(event)
            await case_recording_repository.add_log(
                db,
                session,
                log_type="llm_skip",
                step_order=event.step_order,
                message=f"步骤 {step_no} 无可用 LLM，使用规则回退",
                detail={"reason": "no_llm", "description": fallback},
            )
            return fallback, "fallback", {"reason": "no_llm"}

        if event.action_type == "key":
            human_content = self._build_key_prompt(event)
            llm_input = {"system_prompt": SYSTEM_PROMPT, "user_message": human_content, "provider": provider}
            messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=human_content)]
        else:
            before_image = case_recording_repository.read_image_data_uri(
                session.session_uuid, event.before_image_path
            )
            if not before_image:
                fallback = self._fallback_description(event)
                await case_recording_repository.add_log(
                    db,
                    session,
                    log_type="llm_skip",
                    step_order=event.step_order,
                    message=f"步骤 {step_no} 缺少操作前截图，使用规则回退",
                    detail={"reason": "no_screenshot", "description": fallback},
                )
                return fallback, "fallback", {"reason": "no_screenshot"}

            intent = self._event_to_intent(event)
            annotated_image = annotate_before_image(before_image, intent)
            human_content = self._build_multimodal_prompt(event, operation)
            llm_input = {
                "system_prompt": SYSTEM_PROMPT,
                "user_message": human_content,
                "provider": provider,
                "annotated_image": True,
                "operation": operation,
            }
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(
                    content=[
                        {"type": "text", "text": human_content},
                        {"type": "image_url", "image_url": {"url": annotated_image}},
                    ]
                ),
            ]

        await case_recording_repository.add_log(
            db,
            session,
            log_type="llm_input",
            step_order=event.step_order,
            message=f"步骤 {step_no} LLM 输入",
            detail=llm_input,
        )

        try:
            response = await llm.ainvoke(messages)
            text = response.content if isinstance(response.content, str) else str(response.content)
            await case_recording_repository.add_log(
                db,
                session,
                log_type="llm_output",
                step_order=event.step_order,
                message=f"步骤 {step_no} LLM 输出",
                detail={"raw_response": text},
            )
            description = self._parse_single_description(text)
            if description:
                return description, "llm", {"parsed": True}
            fallback = self._fallback_description(event)
            await case_recording_repository.add_log(
                db,
                session,
                log_type="llm_parse_error",
                step_order=event.step_order,
                message=f"步骤 {step_no} LLM 输出解析失败，使用规则回退",
                detail={"raw_response": text, "fallback": fallback},
            )
            return fallback, "fallback", {"parsed": False}
        except Exception as exc:
            fallback = self._fallback_description(event)
            await case_recording_repository.add_log(
                db,
                session,
                log_type="llm_error",
                step_order=event.step_order,
                message=f"步骤 {step_no} LLM 调用失败",
                detail={"error": str(exc), "fallback": fallback},
            )
            return fallback, "fallback", {"error": str(exc)}

    def _event_to_intent(self, event: CaseRecordingEvent) -> ActionIntent:
        action = event.action_type
        if action == "key":
            action = "skip"
        return ActionIntent(
            action=action,  # type: ignore[arg-type]
            x=event.x,
            y=event.y,
            x2=event.x2,
            y2=event.y2,
            duration_ms=event.duration_ms or 300,
        )

    def _operation_context(self, event: CaseRecordingEvent) -> dict:
        width = event.device_width or 0
        height = event.device_height or 0
        ctx: dict = {
            "action_type": event.action_type,
            "screen_width": width,
            "screen_height": height,
        }
        if event.action_type == "key":
            ctx["key"] = event.key_name
            return ctx
        if event.x is not None and event.y is not None:
            ctx["x"] = event.x
            ctx["y"] = event.y
            ctx["position_hint"] = screen_position_label(event.x, event.y, width, height)
        if event.action_type == "swipe":
            ctx["x2"] = event.x2
            ctx["y2"] = event.y2
            if event.x2 is not None and event.y2 is not None:
                ctx["end_position_hint"] = screen_position_label(event.x2, event.y2, width, height)
        if event.duration_ms is not None:
            ctx["duration_ms"] = event.duration_ms
        return ctx

    def _build_multimodal_prompt(self, event: CaseRecordingEvent, operation: dict) -> str:
        action_labels = {
            "tap": "点击",
            "long_press": "长按",
            "swipe": "滑动",
        }
        action_label = action_labels.get(event.action_type, event.action_type)
        lines = [
            "请根据标注截图（已标出用户操作位置）反向生成一条自然语言 Case 步骤。",
            f"操作类型：{action_label}",
            f"屏幕尺寸：{event.device_width}x{event.device_height}",
        ]
        if event.x is not None and event.y is not None:
            lines.append(f"操作位置（像素坐标，仅供理解区域，不要写入最终描述）：({event.x}, {event.y})")
            if operation.get("position_hint"):
                lines.append(f"位置区域参考：{operation['position_hint']}")
        if event.action_type == "swipe" and event.x2 is not None and event.y2 is not None:
            lines.append(f"滑动终点（像素坐标，不要写入最终描述）：({event.x2}, {event.y2})")
            if operation.get("end_position_hint"):
                lines.append(f"终点区域参考：{operation['end_position_hint']}")
        lines.append(
            "请识别标注位置处的可见 UI 元素，输出与正向 Case 一致的单步描述（动作+方位+可见特征）。"
        )
        return "\n".join(lines)

    def _build_key_prompt(self, event: CaseRecordingEvent) -> str:
        key_labels = {"back": "返回键", "home": "主屏键", "recents": "最近任务键"}
        key_label = key_labels.get(event.key_name or "", event.key_name or "系统键")
        return f"用户按下了{key_label}，请生成一条自然语言 Case 步骤。"

    def _parse_single_description(self, text: str) -> str | None:
        cleaned = text.strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
        if fence:
            cleaned = fence.group(1).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                desc = str(data.get("description", "")).strip()
                return desc or None
        except json.JSONDecodeError:
            pass
        if cleaned and not cleaned.startswith("{"):
            return cleaned.splitlines()[0].strip() or None
        return None

    def _fallback_description(self, event: CaseRecordingEvent) -> str:
        width = event.device_width
        height = event.device_height
        if event.action_type == "key":
            key_labels = {"back": "按下返回键", "home": "按下主屏键", "recents": "打开最近任务"}
            return key_labels.get(event.key_name or "", "按下系统键")
        pos = screen_position_label(event.x, event.y, width, height)
        if event.action_type == "long_press":
            return f"长按{pos}区域"
        if event.action_type == "swipe":
            end_pos = screen_position_label(event.x2, event.y2, width, height)
            return f"从{pos}向{end_pos}滑动"
        return f"点击{pos}区域"


recording_step_generator = RecordingStepGenerator()
