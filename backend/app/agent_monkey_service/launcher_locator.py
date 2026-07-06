"""主屏幕应用图标定位：优先用 uiautomator 层级（精确），视觉模型作备选。"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

from app.agent_monkey_service.schemas import BBox, Center
from app.agent_monkey_service.screenshot_utils import center_from_bbox
from app.services.adb import adb_service

logger = logging.getLogger(__name__)

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

_ALIAS_GROUPS: list[tuple[str, ...]] = [
    ("电话", "phone", "dialer", "拨号"),
    ("信息", "messages", "message", "短信"),
    ("微信", "wechat"),
    ("相机", "camera"),
    ("设置", "settings"),
    ("浏览器", "chrome", "browser"),
    ("相册", "photos", "图库"),
    ("邮件", "gmail", "mail"),
    ("日历", "calendar"),
    ("时钟", "clock"),
    ("联系人", "contacts"),
    ("应用商店", "play store", "playstore"),
    ("voicemail", "voicemall", "语音邮件", "语音信箱"),
    ("recents", "recent", "最近", "通话记录"),
    ("favorites", "favorite", "收藏"),
    ("keypad", "拨号键盘", "拨号"),
]

_OVERFLOW_DESC_HINTS = (
    "more options",
    "更多选项",
    "options",
    "overflow",
    "open navigation drawer",
)
_OVERFLOW_DESC_RE = re.compile(
    r"三个.*点|点状|竖.*点|ellipsis|overflow|更多选项|菜单",
    re.I,
)


def _title_matches_target(label: str, target: str) -> bool:
    left = (label or "").strip().lower()
    right = (target or "").strip().lower()
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    for group in _ALIAS_GROUPS:
        if any(g in right for g in group):
            if any(g in left for g in group):
                return True
    return False


def _fuzzy_close(left: str, right: str, *, min_ratio: float = 0.78) -> bool:
    a = (left or "").strip().lower()
    b = (right or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    if abs(len(a) - len(b)) > 3:
        return False
    return SequenceMatcher(None, a, b).ratio() >= min_ratio


def parse_ui_bounds(bounds: str) -> BBox | None:
    match = _BOUNDS_RE.match((bounds or "").strip())
    if not match:
        return None
    x0, y0, x1, y1 = (int(match.group(i)) for i in range(1, 5))
    if x1 <= x0 or y1 <= y0:
        return None
    return BBox(x=x0, y=y0, w=x1 - x0, h=y1 - y0)


def find_launcher_icon_in_xml(xml: str, target_app_name: str) -> tuple[BBox, Center, str] | None:
    """在 launcher UI dump 中按 text/content-desc 匹配目标应用图标。"""
    target = (target_app_name or "").strip()
    if not target or not xml.strip():
        return None

    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        logger.warning("[launcher] UI XML 解析失败")
        return None

    best: tuple[BBox, Center, str, int] | None = None
    for node in root.iter("node"):
        if node.attrib.get("clickable") != "true":
            continue
        text = (node.attrib.get("text") or "").strip()
        desc = (node.attrib.get("content-desc") or "").strip()
        label = text or desc
        if not label:
            continue
        if not (_title_matches_target(text, target) or _title_matches_target(desc, target)):
            continue
        bbox = parse_ui_bounds(node.attrib.get("bounds", ""))
        if not bbox or bbox.w < 20 or bbox.h < 20:
            continue
        center = center_from_bbox(bbox)
        # 优先完全匹配 text，其次更靠上的热区（Dock 图标）
        score = 0
        if text and _title_matches_target(text, target):
            score += 10
        if desc and _title_matches_target(desc, target):
            score += 5
        if text.lower() == target.lower():
            score += 20
        if best is None or score > best[3]:
            best = (bbox, center, label, score)

    if best:
        bbox, center, label, _ = best
        return bbox, center, label
    return None


async def find_clickable_by_text(
    serial: str | None,
    label: str,
    *,
    hint_x: int | None = None,
    hint_y: int | None = None,
    screen_width: int = 0,
    screen_height: int = 0,
) -> tuple[BBox, Center, str] | None:
    """按 text/content-desc 在 UI 层级中定位可点击控件（应用内 Tab、按钮等）。"""
    target = (label or "").strip()
    if not target or not serial:
        return None
    try:
        xml = await adb_service.dump_ui_hierarchy_async(serial)
        found = _find_clickable_in_xml(
            xml,
            target,
            hint_x=hint_x,
            hint_y=hint_y,
            screen_width=screen_width,
            screen_height=screen_height,
        )
        if found:
            bbox, center, matched = found
            logger.info(
                "[launcher] UI 文本定位「%s」→ %s center=(%s,%s)",
                target,
                matched,
                center.x,
                center.y,
            )
        return found
    except Exception as exc:
        logger.warning("[launcher] UI 文本定位失败: %s", exc)
        return None


def _find_clickable_in_xml(
    xml: str,
    target: str,
    *,
    hint_x: int | None = None,
    hint_y: int | None = None,
    screen_width: int = 0,
    screen_height: int = 0,
) -> tuple[BBox, Center, str] | None:
    if not xml.strip() or not target.strip():
        return None
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None

    target_lower = target.lower()
    best: tuple[BBox, Center, str, float] | None = None
    for node in root.iter("node"):
        if node.attrib.get("clickable") != "true":
            continue
        text = (node.attrib.get("text") or "").strip()
        desc = (node.attrib.get("content-desc") or "").strip()
        label = text or desc
        if not label:
            continue
        label_lower = label.lower()
        score = 0.0
        if label_lower == target_lower:
            score = 100.0
        elif target_lower in label_lower or label_lower in target_lower:
            score = 60.0
        elif _title_matches_target(label, target):
            score = 50.0
        elif _fuzzy_close(label, target):
            score = 45.0
        else:
            continue
        bbox = parse_ui_bounds(node.attrib.get("bounds", ""))
        if not bbox or bbox.w < 8 or bbox.h < 8:
            continue
        center = center_from_bbox(bbox)
        if hint_x is not None and hint_y is not None and screen_width > 0 and screen_height > 0:
            dx = abs(center.x - hint_x) / screen_width
            dy = abs(center.y - hint_y) / screen_height
            distance_penalty = (dx + dy) * 40.0
            score -= distance_penalty
        if best is None or score > best[3]:
            best = (bbox, center, label, score)
    if best and best[3] >= 20.0:
        bbox, center, label, _ = best
        return bbox, center, label
    return None


def _find_overflow_in_xml(xml: str, screen_width: int = 1080, screen_height: int = 2400) -> tuple[BBox, Center, str] | None:
    if not xml.strip():
        return None
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None

    best: tuple[BBox, Center, str, int] | None = None
    for node in root.iter("node"):
        if node.attrib.get("clickable") != "true":
            continue
        text = (node.attrib.get("text") or "").strip()
        desc = (node.attrib.get("content-desc") or "").strip()
        label = text or desc
        desc_lower = desc.lower()
        score = 0
        if any(hint in desc_lower for hint in _OVERFLOW_DESC_HINTS):
            score = 90
        elif label and _OVERFLOW_DESC_RE.search(label):
            score = 70
        else:
            cls = (node.attrib.get("class") or "").lower()
            if "imagebutton" in cls or "action" in cls:
                score = 30
            else:
                continue
        bbox = parse_ui_bounds(node.attrib.get("bounds", ""))
        if not bbox or bbox.w < 8 or bbox.h < 8:
            continue
        center = center_from_bbox(bbox)
        if screen_width > 0 and center.x < screen_width * 0.65:
            continue
        if screen_height > 0 and center.y > screen_height * 0.25:
            continue
        score += min(20, center.x // max(screen_width // 20, 1))
        if best is None or score > best[3]:
            best = (bbox, center, label or desc or "overflow", score)
    if best:
        bbox, center, label, _ = best
        return bbox, center, label
    return None


async def find_overflow_menu(
    serial: str | None,
    *,
    screen_width: int = 1080,
    screen_height: int = 2400,
) -> tuple[BBox, Center, str] | None:
    if not serial:
        return None
    try:
        xml = await adb_service.dump_ui_hierarchy_async(serial)
        found = _find_overflow_in_xml(xml, screen_width, screen_height)
        if found:
            _bbox, center, label = found
            logger.info(
                "[launcher] 溢出菜单定位 → %s center=(%s,%s)",
                label,
                center.x,
                center.y,
            )
        return found
    except Exception as exc:
        logger.warning("[launcher] 溢出菜单定位失败: %s", exc)
        return None


async def find_launcher_icon(
    serial: str | None,
    target_app_name: str,
) -> tuple[BBox, Center, str] | None:
    """真机主屏：dump UI 层级并定位目标应用图标。"""
    try:
        xml = await adb_service.dump_ui_hierarchy_async(serial)
        found = find_launcher_icon_in_xml(xml, target_app_name)
        if found:
            bbox, center, label = found
            logger.info(
                "[launcher] UI 定位「%s」→ label=%s bbox=%s center=(%s,%s)",
                target_app_name,
                label,
                bbox.model_dump(),
                center.x,
                center.y,
            )
        return found
    except Exception as exc:
        logger.warning("[launcher] UI 定位失败: %s", exc)
        return None
