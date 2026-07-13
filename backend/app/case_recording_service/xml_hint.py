from __future__ import annotations

import re
from dataclasses import dataclass


_BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


@dataclass(frozen=True)
class UiNode:
    bounds: tuple[int, int, int, int]
    text: str
    content_desc: str
    resource_id: str
    class_name: str

    @property
    def area(self) -> int:
        left, top, right, bottom = self.bounds
        return max(0, right - left) * max(0, bottom - top)

    def contains(self, x: int, y: int) -> bool:
        left, top, right, bottom = self.bounds
        return left <= x <= right and top <= y <= bottom

    def label(self) -> str:
        for value in (self.text.strip(), self.content_desc.strip(), self.resource_id.strip()):
            if value:
                return value
        short_class = self.class_name.rsplit(".", 1)[-1] if self.class_name else "控件"
        return short_class


def _parse_nodes(xml: str) -> list[UiNode]:
    nodes: list[UiNode] = []
    if not xml:
        return nodes
    for tag in re.finditer(r"<node\b[^>]*>", xml):
        fragment = tag.group(0)
        bounds_match = _BOUNDS_RE.search(fragment)
        if not bounds_match:
            continue
        attrs = {key: value for key, value in _ATTR_RE.findall(fragment)}
        left, top, right, bottom = (int(bounds_match.group(i)) for i in range(1, 5))
        nodes.append(
            UiNode(
                bounds=(left, top, right, bottom),
                text=attrs.get("text", ""),
                content_desc=attrs.get("content-desc", ""),
                resource_id=attrs.get("resource-id", ""),
                class_name=attrs.get("class", ""),
            )
        )
    return nodes


def element_hint_from_xml(xml: str, x: int | None, y: int | None) -> str | None:
    if x is None or y is None or not xml:
        return None
    candidates = [node for node in _parse_nodes(xml) if node.contains(x, y)]
    if not candidates:
        return None
    best = min(candidates, key=lambda node: node.area)
    label = best.label()
    if not label:
        return None
    return label
