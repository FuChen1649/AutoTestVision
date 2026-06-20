from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image, ImageDraw

from app.agent_monkey_service.schemas import BBox, Center


def annotate_bbox_on_image(image_bytes: bytes, bbox: BBox | None, center: Center | None, title: str) -> bytes:
    with Image.open(BytesIO(image_bytes)) as image:
        rgba = image.convert("RGBA")
        draw = ImageDraw.Draw(rgba)
        if bbox and bbox.w > 0 and bbox.h > 0:
            draw.rectangle(
                (bbox.x, bbox.y, bbox.x + bbox.w, bbox.y + bbox.h),
                outline=(34, 197, 94, 255),
                width=4,
            )
        if center:
            x, y = center.x, center.y
            draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=(59, 130, 246, 220))
            draw.text((x + 14, y - 8), title[:24], fill=(59, 130, 246, 255))
        buffer = BytesIO()
        rgba.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue()


def normalized_bbox_to_pixels(
    bbox_norm: dict,
    screen_width: int,
    screen_height: int,
) -> BBox:
    x = int(bbox_norm.get("x", 0))
    y = int(bbox_norm.get("y", 0))
    w = int(bbox_norm.get("w", bbox_norm.get("width", 0)))
    h = int(bbox_norm.get("h", bbox_norm.get("height", 0)))
    if max(x, y, w, h) <= 1000 and screen_width > 0 and screen_height > 0:
        px = round(x / 1000 * screen_width)
        py = round(y / 1000 * screen_height)
        pw = max(1, round(w / 1000 * screen_width))
        ph = max(1, round(h / 1000 * screen_height))
        return BBox(x=px, y=py, w=pw, h=ph)
    return BBox(x=x, y=y, w=max(w, 1), h=max(h, 1))


def center_from_bbox(bbox: BBox) -> Center:
    return Center(x=bbox.x + bbox.w // 2, y=bbox.y + bbox.h // 2)


def bytes_to_data_url(image_bytes: bytes) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"
