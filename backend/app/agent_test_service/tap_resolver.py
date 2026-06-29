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
    text = (description or "").lower()
    if _guess_target_app(description):
        return True
    return any(
        kw in text
        for kw in (
            "主屏",
            "桌面",
            "home",
            "launcher",
            "dock",
            "左下",
            "右下",
            "底部",
            "图标",
            "icon",
            "应用",
        )
    )


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

    # 1) 主屏应用图标
    if _looks_like_launcher_tap(step_description):
        target = _guess_target_app(step_description)
        if target:
            hit = await find_launcher_icon(serial, target)
            if hit:
                _bbox, center, label = hit
                return intent.model_copy(
                    update={
                        "x": center.x,
                        "y": center.y,
                        "confidence": max(intent.confidence, 0.92),
                        "reasoning": f"uiautomator 定位「{label}」({center.x},{center.y})",
                    }
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
            return intent.model_copy(
                update={
                    "x": center.x,
                    "y": center.y,
                    "confidence": max(intent.confidence, 0.92),
                    "reasoning": f"uiautomator 溢出菜单「{label}」({center.x},{center.y})",
                }
            )

    # 3) 应用内按文本/content-desc 定位（Tab、按钮等）
    label = _extract_click_label(step_description)
    if label:
        hit = await find_clickable_by_text(serial, label)
        if hit:
            _bbox, center, matched = hit
            return intent.model_copy(
                update={
                    "x": center.x,
                    "y": center.y,
                    "confidence": max(intent.confidence, 0.92),
                    "reasoning": f"uiautomator 文本「{matched}」({center.x},{center.y})",
                }
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
