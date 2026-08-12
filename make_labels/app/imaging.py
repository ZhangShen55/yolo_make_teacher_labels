from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DISPLAY_LABELS = {
    "sit": "坐着",
    "stand": "站立",
    "bbwriting": "板书",
    "teach": "授课",
}
FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]


def find_font_path() -> str | None:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def draw_red_box(draw: ImageDraw.ImageDraw, image_size: tuple[int, int], box_xyxy: list[int]) -> None:
    x1, y1, x2, y2 = box_xyxy
    line_width = max(4, min(image_size) // 180)
    for offset in range(line_width):
        draw.rectangle([x1 - offset, y1 - offset, x2 + offset, y2 + offset], outline=(255, 0, 0))


def render_box_preview(src_path: Path, out_path: Path, box_xyxy: list[int]) -> Path:
    image = Image.open(src_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw_red_box(draw, image.size, box_xyxy)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return out_path


def render_labeled_preview(src_path: Path, out_path: Path, box_xyxy: list[int], labels: list[str]) -> Path:
    image = Image.open(src_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw_red_box(draw, image.size, box_xyxy)
    x1, y1, x2, y2 = box_xyxy

    text = "+".join(DISPLAY_LABELS.get(label, label) for label in labels)
    target_width = max(16, (x2 - x1) / 2)
    font_path = find_font_path()
    font_size = max(12, int(target_width / max(1, len(text))))
    if font_path:
        font = ImageFont.truetype(font_path, size=font_size)
    else:
        font = ImageFont.load_default()
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (bbox[2] - bbox[0]) / 2, cy - (bbox[3] - bbox[1]) / 2), text, fill=(0, 0, 255), font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return out_path
