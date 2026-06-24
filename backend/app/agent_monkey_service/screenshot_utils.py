from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

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


def annotate_screen_with_numbers(
    image_bytes: bytes,
    labels: list[tuple[BBox | None, Center | None, str]],
) -> bytes:
    """在操作位置绘制半透明编号标注。"""
    with Image.open(BytesIO(image_bytes)) as image:
        rgba = image.convert("RGBA")
        overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except OSError:
            font = ImageFont.load_default()

        for bbox, center, label in labels:
            if bbox and bbox.w > 0 and bbox.h > 0:
                draw.rectangle(
                    (bbox.x, bbox.y, bbox.x + bbox.w, bbox.y + bbox.h),
                    outline=(34, 197, 94, 90),
                    width=2,
                )
            if not center:
                continue
            x, y = center.x, center.y
            text = str(label).strip().split()[0]
            tw, th = draw.textbbox((0, 0), text, font=font)[2:]
            pad = 4
            rx0 = x - tw / 2 - pad
            ry0 = y - th / 2 - pad
            rx1 = x + tw / 2 + pad
            ry1 = y + th / 2 + pad
            draw.rounded_rectangle((rx0, ry0, rx1, ry1), radius=10, fill=(239, 68, 68, 110), outline=(255, 255, 255, 160), width=1)
            draw.text((x - tw / 2, y - th / 2 - 1), text, fill=(255, 255, 255, 220), font=font)

        rgba = Image.alpha_composite(rgba, overlay)
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


def bbox_overlap_ratio(a: BBox, b: BBox) -> float:
    """返回两框交集面积占较小框面积的比例，用于去重。"""
    x1 = max(a.x, b.x)
    y1 = max(a.y, b.y)
    x2 = min(a.x + a.w, b.x + b.w)
    y2 = min(a.y + a.h, b.y + b.h)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    smaller = min(a.w * a.h, b.w * b.h)
    if smaller <= 0:
        return 0.0
    return inter / smaller


def titles_similar(a: str, b: str) -> bool:
    left = (a or "").strip().lower()
    right = (b or "").strip().lower()
    if not left or not right:
        return False
    if left == right:
        return True
    if left in right or right in left:
        return True
    return False


def bytes_to_data_url(image_bytes: bytes) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"
