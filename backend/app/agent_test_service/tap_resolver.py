"""点击坐标精修：优先 uiautomator 定位，避免视觉模型点偏。"""

from __future__ import annotations

import re

from app.agent_monkey_service.launcher_locator import (
    find_clickable_by_text,
    find_launcher_icon,
    find_overflow_menu,
)
from app.agent_test_service.schemas import ActionIntent

_APP_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"电话|phone|dialer|拨号", re.I), "电话"),
    (re.compile(r"信息|短信|messages?", re.I), "信息"),
    (re.compile(r"微信|wechat", re.I), "微信"),
    (re.compile(r"相机|camera", re.I), "相机"),
    (re.compile(r"设置|settings", re.I), "设置"),
    (re.compile(r"chrome|浏览器|browser", re.I), "浏览器"),
    (re.compile(r"相册|photos?|图库", re.I), "相册"),
    (re.compile(r"gmail|邮件|邮箱", re.I), "Gmail"),
    (re.compile(r"play\s*store|应用商店", re.I), "Play Store"),
]

_TEXT_EXTRACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:下方)?文本[：:]\s*([^\s，,。.]+)", re.I),
    re.compile(r"(?:点击|点选|选择|按).*?[「『\"']([^」』\"']+)[」』\"']", re.I),
    re.compile(r"(?:click|tap)\s+.*?['\"]([^'\"]+)['\"]", re.I),
    re.compile(
        r"(?:Recents|Contacts|Favorites|Keypad|Voicemail|Voicemall|通话|联系人|最近|拨号)",
        re.I,
    ),
]

_OVERFLOW_STEP_RE = re.compile(
    r"三个.*点|点状|竖.*点|ellipsis|overflow|更多选项|溢出|菜单按钮",
    re.I,
)
_LAUNCHER_CONTEXT_RE = re.compile(
    r"主屏|桌面|home\s*screen|launcher|dock|主屏幕|回到桌面|返回桌面|"
    r"打开|启动|开启|launch|start",
    re.I,
)
_IN_APP_STEP_RE = re.compile(
    r"tab|标签|页签|菜单|输入|搜索|按钮|列表|详情|键盘|拨号键|"
    r"导航栏|toolbar|toolbar|弹窗|dialog|确认|取消|保存|删除|编辑|"
    r"recents|contacts|favorites|keypad|通话记录|联系人|收藏|拨号盘",
    re.I,
)
_COORD_HINT_MAX_DX = 0.38
_COORD_HINT_MAX_DY = 0.38


def _coords_near_hint(
    hint_x: int | None,
    hint_y: int | None,
    center_x: int,
    center_y: int,
    *,
    screen_width: int,
    screen_height: int,
    max_dx: float = _COORD_HINT_MAX_DX,
    max_dy: float = _COORD_HINT_MAX_DY,
) -> bool:
    if hint_x is None or hint_y is None or screen_width <= 0 or screen_height <= 0:
        return True
    dx = abs(center_x - hint_x) / screen_width
    dy = abs(center_y - hint_y) / screen_height
    return dx <= max_dx and dy <= max_dy


def _apply_ui_hit(
    intent: ActionIntent,
    center_x: int,
    center_y: int,
    *,
    label: str,
    reasoning: str,
    screen_width: int,
    screen_height: int,
) -> ActionIntent:
    if not _coords_near_hint(
        intent.x,
        intent.y,
        center_x,
        center_y,
        screen_width=screen_width,
        screen_height=screen_height,
    ):
        return intent.model_copy(
            update={
                "reasoning": (
                    (intent.reasoning or "")
                    + f"；uiautomator 命中「{label}」({center_x},{center_y}) 但与视觉坐标偏差过大，保留模型坐标"
                )
            }
        )
    return intent.model_copy(
        update={
            "x": center_x,
            "y": center_y,
            "confidence": max(intent.confidence, 0.92),
            "reasoning": reasoning,
        }
    )


def _guess_target_app(description: str) -> str | None:
    text = (description or "").strip()
    if not text:
        return None
    for pattern, target in _APP_PATTERNS:
        if pattern.search(text):
            return target
    match = re.search(r"[「『\"']([^」』\"']+)[」』\"']", text)
    if match:
        return match.group(1).strip()
    return None


def _extract_click_label(description: str) -> str | None:
    text = (description or "").strip()
    if not text:
        return None
    for pattern in _TEXT_EXTRACT_PATTERNS[:3]:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    for pattern in _TEXT_EXTRACT_PATTERNS[3:]:
        match = pattern.search(text)
        if match:
            token = match.group(0).strip()
            if token.lower() == "voicemall":
                return "Voicemail"
            return token
    return None


def _looks_like_launcher_tap(description: str) -> bool:
    text = (description or "").strip()
    if not text:
        return False
    if _IN_APP_STEP_RE.search(text):
        return False
    target = _guess_target_app(text)
    if not target:
        return False
    lower = text.lower()
    if _LAUNCHER_CONTEXT_RE.search(text):
        return True
    if any(kw in lower for kw in ("dock", "图标", "icon", "主屏", "桌面", "launcher")):
        return True
    if re.search(r"点击|点选|点按|tap|click", text, re.I) and not _IN_APP_STEP_RE.search(text):
        return True
    return False


def _looks_like_overflow_menu(description: str) -> bool:
    return bool(_OVERFLOW_STEP_RE.search(description or ""))


async def refine_tap_intent(
    intent: ActionIntent,
    *,
    step_description: str,
    serial: str | None,
    screen_height: int = 0,
    screen_width: int = 0,
) -> ActionIntent:
    if intent.action != "tap" or not serial:
        return intent

    # 1) 主屏应用图标（仅桌面/打开类步骤）
    if _looks_like_launcher_tap(step_description):
        target = _guess_target_app(step_description)
        if target:
            hit = await find_launcher_icon(serial, target)
            if hit:
                _bbox, center, label = hit
                return _apply_ui_hit(
                    intent,
                    center.x,
                    center.y,
                    label=label,
                    reasoning=f"uiautomator 定位「{label}」({center.x},{center.y})",
                    screen_width=screen_width,
                    screen_height=screen_height,
                )

    # 2) 右上角溢出菜单（⋮）
    if _looks_like_overflow_menu(step_description):
        hit = await find_overflow_menu(
            serial,
            screen_width=screen_width or 1080,
            screen_height=screen_height or 2400,
        )
        if hit:
            _bbox, center, label = hit
            return _apply_ui_hit(
                intent,
                center.x,
                center.y,
                label=label,
                reasoning=f"uiautomator 溢出菜单「{label}」({center.x},{center.y})",
                screen_width=screen_width,
                screen_height=screen_height,
            )

    # 3) 应用内按文本/content-desc 定位（Tab、按钮等）
    label = _extract_click_label(step_description)
    if label:
        hit = await find_clickable_by_text(
            serial,
            label,
            hint_x=intent.x,
            hint_y=intent.y,
            screen_width=screen_width,
            screen_height=screen_height,
        )
        if hit:
            _bbox, center, matched = hit
            return _apply_ui_hit(
                intent,
                center.x,
                center.y,
                label=matched,
                reasoning=f"uiautomator 文本「{matched}」({center.x},{center.y})",
                screen_width=screen_width,
                screen_height=screen_height,
            )

    # 4) 模型坐标落在底部手势条附近：降置信度，避免误点
    if screen_height > 0 and intent.y is not None and intent.y > screen_height * 0.92:
        return intent.model_copy(
            update={
                "confidence": min(intent.confidence, 0.25),
                "reasoning": (intent.reasoning or "") + "；坐标靠近屏幕底边，uiautomator 未命中",
            }
        )

    return intent
