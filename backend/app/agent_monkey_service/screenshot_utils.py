from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from typing import Any

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
    labels: list[tuple[BBox | None, Center | None, str, str | None]],
) -> bytes:
    """在操作位置绘制半透明编号标注。第四项为动作状态（pending/executed/...）。"""
    with Image.open(BytesIO(image_bytes)) as image:
        rgba = image.convert("RGBA")
        overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        height = rgba.size[1]
        font_size = max(22, height // 90)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except OSError:
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", font_size)
            except OSError:
                font = ImageFont.load_default()

        status_fill = {
            "pending": (239, 68, 68, 200),
            "executed": (34, 197, 94, 200),
            "no_effect": (148, 163, 184, 190),
            "failed": (185, 28, 28, 210),
            "skipped": (100, 116, 139, 190),
        }

        for bbox, center, label, status in labels:
            outline = (34, 197, 94, 180) if status == "executed" else (239, 68, 68, 160)
            if bbox and bbox.w > 0 and bbox.h > 0:
                draw.rectangle(
                    (bbox.x, bbox.y, bbox.x + bbox.w, bbox.y + bbox.h),
                    outline=outline,
                    width=max(3, height // 400),
                )
            if not center:
                continue
            x, y = center.x, center.y
            text = str(label).strip().split()[0]
            tw, th = draw.textbbox((0, 0), text, font=font)[2:]
            pad = max(6, font_size // 3)
            rx0 = x - tw / 2 - pad
            ry0 = y - th / 2 - pad
            rx1 = x + tw / 2 + pad
            ry1 = y + th / 2 + pad
            fill = status_fill.get(status or "pending", status_fill["pending"])
            draw.rounded_rectangle(
                (rx0, ry0, rx1, ry1),
                radius=max(10, font_size // 2),
                fill=fill,
                outline=(255, 255, 255, 220),
                width=2,
            )
            draw.text((x - tw / 2, y - th / 2 - 1), text, fill=(255, 255, 255, 240), font=font)

        rgba = Image.alpha_composite(rgba, overlay)
        buffer = BytesIO()
        rgba.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue()


def parse_candidate_bbox(
    bbox_raw: Any,
    screen_width: int,
    screen_height: int,
) -> BBox | None:
    """把模型返回的多种 bbox 格式统一为像素 BBox。

    支持：
    - {x,y,w,h} / {x,y,width,height}（0-1000 或像素）
    - {xmin,ymin,xmax,ymax} / {left,top,right,bottom}
    - [x1,y1,x2,y2] 智谱/GLM 常用的左上角+右下角（0-1000）
    - [x,y,w,h]
    """
    if bbox_raw is None:
        return None

    if isinstance(bbox_raw, (list, tuple)) and len(bbox_raw) >= 4:
        a, b, c, d = (float(v) for v in bbox_raw[:4])
        # 嵌套 [[x1,y1,x2,y2]]
        if isinstance(bbox_raw[0], (list, tuple)) and len(bbox_raw[0]) >= 4:
            a, b, c, d = (float(v) for v in bbox_raw[0][:4])
        # 任一坐标超过 1000 视为像素坐标 [x1,y1,x2,y2]
        if max(a, b, c, d) > 1000:
            x0, y0, x1, y1 = int(a), int(b), int(c), int(d)
            if x1 > x0 and y1 > y0:
                return clamp_bbox_to_screen(
                    BBox(x=x0, y=y0, w=x1 - x0, h=y1 - y0),
                    screen_width,
                    screen_height,
                )
        scale = _bbox_norm_scale(a, b, c, d)
        ax1 = _axis_to_norm_1000(a * scale, screen_width)
        ay1 = _axis_to_norm_1000(b * scale, screen_height)
        ax2 = _axis_to_norm_1000(c * scale, screen_width)
        ay2 = _axis_to_norm_1000(d * scale, screen_height)
        if ax2 > ax1 and ay2 > ay1:
            return normalized_bbox_to_pixels(
                {"x": ax1, "y": ay1, "w": ax2 - ax1, "h": ay2 - ay1},
                screen_width,
                screen_height,
            )
        return normalized_bbox_to_pixels(
            {
                "x": ax1,
                "y": ay1,
                "w": _axis_to_norm_1000(c, screen_width),
                "h": _axis_to_norm_1000(d, screen_height),
            },
            screen_width,
            screen_height,
        )

    if isinstance(bbox_raw, dict):
        vals = [
            float(bbox_raw.get(k, 0))
            for k in ("x", "y", "w", "h", "width", "height", "xmin", "ymin", "xmax", "ymax")
            if k in bbox_raw
        ]
        scale = _bbox_norm_scale(*vals) if vals else 1.0
        if scale != 1.0:
            scaled = dict(bbox_raw)
            for key in ("x", "y", "w", "h", "width", "height", "xmin", "ymin", "xmax", "ymax", "left", "top", "right", "bottom"):
                if key in scaled and isinstance(scaled[key], (int, float)):
                    scaled[key] = float(scaled[key]) * scale
            bbox_raw = scaled
        if any(k in bbox_raw for k in ("xmin", "ymin", "xmax", "ymax", "left", "top", "right", "bottom")):
            x0 = int(bbox_raw.get("xmin", bbox_raw.get("left", 0)))
            y0 = int(bbox_raw.get("ymin", bbox_raw.get("top", 0)))
            x1 = int(bbox_raw.get("xmax", bbox_raw.get("right", x0)))
            y1 = int(bbox_raw.get("ymax", bbox_raw.get("bottom", y0)))
            return normalized_bbox_to_pixels(
                {"x": x0, "y": y0, "w": max(1, x1 - x0), "h": max(1, y1 - y0)},
                screen_width,
                screen_height,
            )
        return normalized_bbox_to_pixels(bbox_raw, screen_width, screen_height)

    return None


def _bbox_norm_scale(*values: float) -> float:
    """若四角坐标均在 0-100，按百分比尺度换算到 0-1000。"""
    nums = [float(v) for v in values]
    if not nums:
        return 1.0
    hi = max(nums)
    lo = min(nums)
    if 0 <= lo and hi <= 100 and hi > 1:
        return 10.0
    return 1.0


def _axis_to_norm_1000(value: float, axis_pixels: int) -> int:
    """把单轴坐标统一为 0-1000 归一化值（智谱 GLM-V：x 相对宽、y 相对高）。"""
    v = float(value)
    if axis_pixels > 0 and v > 1000:
        return max(0, min(1000, round(v / axis_pixels * 1000)))
    if 0 < v <= 1.0:
        return max(0, min(1000, round(v * 1000)))
    return max(0, min(1000, round(v)))


def normalized_bbox_to_pixels(
    bbox_norm: dict,
    screen_width: int,
    screen_height: int,
) -> BBox:
    x = _axis_to_norm_1000(bbox_norm.get("x", 0), screen_width)
    y = _axis_to_norm_1000(bbox_norm.get("y", 0), screen_height)
    w = _axis_to_norm_1000(
        bbox_norm.get("w", bbox_norm.get("width", 0)),
        screen_width,
    )
    h = _axis_to_norm_1000(
        bbox_norm.get("h", bbox_norm.get("height", 0)),
        screen_height,
    )
    if w <= 0 or h <= 0:
        return BBox(x=0, y=0, w=1, h=1)
    px = round(x / 1000 * screen_width)
    py = round(y / 1000 * screen_height)
    pw = max(1, round(w / 1000 * screen_width))
    ph = max(1, round(h / 1000 * screen_height))
    return clamp_bbox_to_screen(BBox(x=px, y=py, w=pw, h=ph), screen_width, screen_height)


def clamp_bbox_to_screen(bbox: BBox, screen_width: int, screen_height: int) -> BBox:
    x = max(0, min(bbox.x, screen_width - 1))
    y = max(0, min(bbox.y, screen_height - 1))
    w = max(1, min(bbox.w, screen_width - x))
    h = max(1, min(bbox.h, screen_height - y))
    return BBox(x=x, y=y, w=w, h=h)


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


# --- 感知指纹（dHash）---------------------------------------------------------
# 像素级 sha256 对真机不可用（状态栏时钟/动画/广告都会变），改用差异哈希：
# 裁掉顶部状态栏与底部导航栏后缩放比较相邻像素，得到 64bit 指纹，用汉明距离判同。

_DHASH_SIZE = 8


def compute_dhash(
    image_bytes: bytes,
    *,
    hash_size: int = _DHASH_SIZE,
    crop_top_ratio: float = 0.04,
    crop_bottom_ratio: float = 0.03,
) -> str:
    """对截图计算 dHash（差异哈希），返回 16 位十六进制字符串。"""
    with Image.open(BytesIO(image_bytes)) as image:
        gray = image.convert("L")
        width, height = gray.size
        top = int(height * max(0.0, crop_top_ratio))
        bottom = height - int(height * max(0.0, crop_bottom_ratio))
        if bottom - top > 8 and width > 8:
            gray = gray.crop((0, top, width, bottom))
        small = gray.resize((hash_size + 1, hash_size), Image.LANCZOS)
        pixels = list(small.getdata())

    row_stride = hash_size + 1
    bits = 0
    for row in range(hash_size):
        base = row * row_stride
        for col in range(hash_size):
            left = pixels[base + col]
            right = pixels[base + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:0{hash_size * hash_size // 4}x}"


def hamming_distance(a: str | None, b: str | None) -> int:
    """两个十六进制指纹的汉明距离；无法比较时返回较大值（视为不同）。"""
    if not a or not b or len(a) != len(b):
        return 64
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return 64


def perceptual_similar(a: str | None, b: str | None, *, threshold: int = 8) -> bool:
    """汉明距离不超过阈值则认为是同一页面（默认 8/64 ≈ 12%）。"""
    return hamming_distance(a, b) <= threshold
