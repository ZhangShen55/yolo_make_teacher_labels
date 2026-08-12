from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DISPLAY_LABELS = {
    "sit": "坐着",
    "stand": "站立",
    "bbwriting": "板书",
    "teach": "讲授",
}
LABEL_ORDER = ["sit", "stand", "bbwriting", "teach"]
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


def build_display_text(labels: list[str]) -> str:
    selected = set(labels)
    return " | ".join(DISPLAY_LABELS[label] for label in LABEL_ORDER if label in selected)


def fit_label_font(draw: ImageDraw.ImageDraw, text: str, max_width: int) -> ImageFont.ImageFont:
    font_path = find_font_path()
    if not font_path:
        return ImageFont.load_default()
    for size in range(28, 11, -1):
        font = ImageFont.truetype(font_path, size=size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
    return ImageFont.truetype(font_path, size=12)


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
    x1, y1, x2, y2 = box_xyxy
    text = build_display_text(labels)
    initial_draw = ImageDraw.Draw(image)
    font = fit_label_font(initial_draw, text, max_width=max(16, image.width - 8))
    text_bbox = initial_draw.textbbox((0, 0), text, font=font, stroke_width=1)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    gap = 6
    required_space = text_height + gap
    top_padding = max(0, required_space - y1)

    if top_padding:
        canvas = Image.new("RGB", (image.width, image.height + top_padding), "white")
        canvas.paste(image, (0, top_padding))
        image = canvas

    shifted_box = [x1, y1 + top_padding, x2, y2 + top_padding]
    draw = ImageDraw.Draw(image)
    draw_red_box(draw, image.size, shifted_box)
    text_x = max(2, min(image.width - text_width - 2, (x1 + x2 - text_width) / 2))
    text_y = shifted_box[1] - gap - text_height - text_bbox[1]
    draw.text(
        (text_x, text_y),
        text,
        fill=(0, 0, 255),
        font=font,
        stroke_width=1,
        stroke_fill=(0, 0, 255),
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return out_path
