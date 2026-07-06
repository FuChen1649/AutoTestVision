"""从 u2 代码行 + UI XML 解析标注坐标，并换算到截图像素。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from app.agent_monkey_service.launcher_locator import parse_ui_bounds
from app.agent_test_service.coordinate_mapper import (
    decode_image_size,
    device_point_to_image_pixels,
    device_rect_to_image_pixels,
)
from app.agent_test_service.image_annotation import annotate_before_image
from app.agent_test_service.schemas import ActionIntent


def parse_action_intent_from_code(
    code_line: str,
    fallback_x: int | None = None,
    fallback_y: int | None = None,
) -> ActionIntent | None:
    text = (code_line or "").strip()
    if not text:
        return None

    swipe = re.search(
        r"d\.swipe\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)",
        text,
    )
    if swipe:
        return ActionIntent(
            action="swipe",
            x=int(float(swipe.group(1))),
            y=int(float(swipe.group(2))),
            x2=int(float(swipe.group(3))),
            y2=int(float(swipe.group(4))),
            confidence=1.0,
            reasoning=text,
        )

    long_click = re.search(r"d\.long_click\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", text)
    if long_click:
        return ActionIntent(
            action="long_press",
            x=int(float(long_click.group(1))),
            y=int(float(long_click.group(2))),
            confidence=1.0,
            reasoning=text,
        )

    click = re.search(r"d\.click\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", text)
    if click:
        return ActionIntent(
            action="tap",
            x=int(float(click.group(1))),
            y=int(float(click.group(2))),
            confidence=1.0,
            reasoning=text,
        )

    if fallback_x is not None and fallback_y is not None:
        return ActionIntent(
            action="tap",
            x=fallback_x,
            y=fallback_y,
            confidence=0.6,
            reasoning=f"fallback from reference: {text}",
        )
    return None


@dataclass
class _CodeSelector:
    resource_id: str | None = None
    text: str | None = None
    description: str | None = None
    text_contains: str | None = None


def _parse_u2_selector(code_line: str) -> _CodeSelector | None:
    text = (code_line or "").strip()
    if not text or not text.startswith("d("):
        return None
    selector = _CodeSelector()
    for match in re.finditer(r'resourceId\s*=\s*["\']([^"\']+)["\']', text):
        selector.resource_id = match.group(1)
    for match in re.finditer(r'\btext\s*=\s*["\']([^"\']+)["\']', text):
        selector.text = match.group(1)
    for match in re.finditer(r'\bdescription\s*=\s*["\']([^"\']+)["\']', text):
        selector.description = match.group(1)
    for match in re.finditer(r'textContains\s*=\s*["\']([^"\']+)["\']', text):
        selector.text_contains = match.group(1)
    if any((selector.resource_id, selector.text, selector.description, selector.text_contains)):
        return selector
    return None


def _node_matches_selector(node: ET.Element, selector: _CodeSelector) -> bool:
    if selector.resource_id:
        rid = (node.attrib.get("resource-id") or "").strip()
        target = selector.resource_id.strip()
        if not rid or not (rid == target or rid.endswith(f"/{target}") or target in rid):
            return False
    if selector.text:
        if (node.attrib.get("text") or "").strip() != selector.text:
            return False
    if selector.description:
        desc = (node.attrib.get("content-desc") or "").strip()
        if desc != selector.description:
            return False
    if selector.text_contains:
        label = (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip()
        if selector.text_contains not in label:
            return False
    return True


def _find_selector_bounds_in_xml(
    ui_xml: str,
    selector: _CodeSelector,
) -> tuple[int, int, int, int] | None:
    if not ui_xml.strip():
        return None
    try:
        root = ET.fromstring(ui_xml)
    except ET.ParseError:
        return None

    best: tuple[int, int, int, int, int] | None = None
    for node in root.iter("node"):
        if not _node_matches_selector(node, selector):
            continue
        bbox = parse_ui_bounds(node.attrib.get("bounds", ""))
        if not bbox or bbox.w < 4 or bbox.h < 4:
            continue
        area = bbox.w * bbox.h
        clickable_bonus = 10 if node.attrib.get("clickable") == "true" else 0
        score = clickable_bonus - area // 1000
        if best is None or score > best[4]:
            x1 = bbox.x + bbox.w
            y1 = bbox.y + bbox.h
            best = (bbox.x, bbox.y, x1, y1, score)
    if best:
        return best[0], best[1], best[2], best[3]
    return None


def _map_intent_device_to_image(
    intent: ActionIntent,
    image_width: int,
    image_height: int,
    device_width: int,
    device_height: int,
) -> ActionIntent:
    mapped = intent.model_copy(deep=True)
    if mapped.x is not None and mapped.y is not None:
        mapped.x, mapped.y = device_point_to_image_pixels(
            mapped.x,
            mapped.y,
            image_width,
            image_height,
            device_width,
            device_height,
        )
    if mapped.x2 is not None and mapped.y2 is not None:
        mapped.x2, mapped.y2 = device_point_to_image_pixels(
            mapped.x2,
            mapped.y2,
            image_width,
            image_height,
            device_width,
            device_height,
        )
    return mapped


def resolve_code_annotation(
    code_line: str,
    *,
    ui_xml: str | None,
    image_data_url: str,
    device_width: int,
    device_height: int,
    fallback_x: int | None = None,
    fallback_y: int | None = None,
) -> tuple[ActionIntent | None, tuple[int, int, int, int] | None]:
    """解析 Code 步骤的截图像素标注坐标与可选元素矩形。"""
    try:
        image_width, image_height = decode_image_size(image_data_url)
    except Exception:
        image_width, image_height = device_width, device_height

    device_bounds: tuple[int, int, int, int] | None = None
    selector = _parse_u2_selector(code_line)
    if selector and ui_xml:
        device_bounds = _find_selector_bounds_in_xml(ui_xml, selector)

    intent = parse_action_intent_from_code(code_line, fallback_x=fallback_x, fallback_y=fallback_y)
    if intent is None and device_bounds:
        x0, y0, x1, y1 = device_bounds
        intent = ActionIntent(
            action="tap",
            x=(x0 + x1) // 2,
            y=(y0 + y1) // 2,
            confidence=0.9,
            reasoning=code_line,
        )
    elif intent is None:
        return None, None

    uses_device_space = bool(
        re.search(r"d\.(click|swipe|long_click)\(", code_line)
    ) or device_bounds is not None
    if uses_device_space:
        mapped_intent = _map_intent_device_to_image(
            intent,
            image_width,
            image_height,
            device_width,
            device_height,
        )
    else:
        mapped_intent = intent
    image_bounds = None
    if device_bounds:
        image_bounds = device_rect_to_image_pixels(
            *device_bounds,
            image_width,
            image_height,
            device_width,
            device_height,
        )
    return mapped_intent, image_bounds


def annotate_code_before_image(
    image_data_url: str,
    code_line: str,
    *,
    ui_xml: str | None,
    device_width: int,
    device_height: int,
    fallback_x: int | None = None,
    fallback_y: int | None = None,
) -> str | None:
    intent, image_bounds = resolve_code_annotation(
        code_line,
        ui_xml=ui_xml,
        image_data_url=image_data_url,
        device_width=device_width,
        device_height=device_height,
        fallback_x=fallback_x,
        fallback_y=fallback_y,
    )
    if not intent:
        return None
    return annotate_before_image(image_data_url, intent, highlight_rect=image_bounds)
