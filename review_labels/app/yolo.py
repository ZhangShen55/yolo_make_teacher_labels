from __future__ import annotations

from dataclasses import dataclass


LABEL_TO_CLASS_ID = {"sit": 0, "stand": 1, "bbwriting": 2, "teach": 3}
CLASS_ID_TO_LABEL = {value: key for key, value in LABEL_TO_CLASS_ID.items()}
LABEL_ORDER = ["sit", "stand", "bbwriting", "teach"]


@dataclass(frozen=True)
class YoloRow:
    class_id: int
    box_norm_xywh: list[float]


def validate_labels(labels: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for label in LABEL_ORDER:
        if label in labels and label not in seen:
            seen.add(label)
            ordered.append(label)

    if set(labels) - set(LABEL_TO_CLASS_ID):
        raise ValueError(f"Unsupported labels: {sorted(set(labels) - set(LABEL_TO_CLASS_ID))}")
    if not ordered:
        raise ValueError("At least one label is required")
    if ("sit" in ordered) == ("stand" in ordered):
        raise ValueError("Exactly one of sit or stand is required")
    return ordered


def clamp_box(box_xyxy: list[int], width: int, height: int, min_size: int = 4) -> list[int]:
    x1, y1, x2, y2 = [int(round(v)) for v in box_xyxy]
    x1, x2 = sorted((max(0, min(width - 1, x1)), max(0, min(width - 1, x2))))
    y1, y2 = sorted((max(0, min(height - 1, y1)), max(0, min(height - 1, y2))))
    if x2 - x1 < min_size:
        x2 = min(width - 1, x1 + min_size)
        x1 = max(0, x2 - min_size)
    if y2 - y1 < min_size:
        y2 = min(height - 1, y1 + min_size)
        y1 = max(0, y2 - min_size)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("Invalid bbox")
    return [x1, y1, x2, y2]


def pixel_to_yolo(box_xyxy: list[int], width: int, height: int) -> list[float]:
    x1, y1, x2, y2 = clamp_box(box_xyxy, width, height)
    return [
        round(((x1 + x2) / 2) / width, 6),
        round(((y1 + y2) / 2) / height, 6),
        round((x2 - x1) / width, 6),
        round((y2 - y1) / height, 6),
    ]


def yolo_to_pixel(box_norm_xywh: list[float], width: int, height: int) -> list[int]:
    x_center, y_center, box_width, box_height = box_norm_xywh
    x1 = round((x_center - box_width / 2) * width)
    y1 = round((y_center - box_height / 2) * height)
    x2 = round((x_center + box_width / 2) * width)
    y2 = round((y_center + box_height / 2) * height)
    return clamp_box([x1, y1, x2, y2], width, height)


def parse_yolo_text(text: str) -> list[YoloRow]:
    rows = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid YOLO row at line {line_number}: {raw_line}")
        class_id = int(parts[0])
        if class_id not in CLASS_ID_TO_LABEL:
            raise ValueError(f"Unsupported class id: {class_id}")
        values = [round(float(value), 6) for value in parts[1:]]
        rows.append(YoloRow(class_id=class_id, box_norm_xywh=values))
    return rows


def yolo_rows_to_text(rows: list[YoloRow]) -> str:
    if not rows:
        return ""
    lines = [
        f"{row.class_id} " + " ".join(f"{value:.6f}" for value in row.box_norm_xywh)
        for row in rows
    ]
    return "\n".join(lines) + "\n"


def group_rows_by_box(rows: list[YoloRow], width: int, height: int) -> list[dict]:
    groups: dict[tuple[float, float, float, float], list[str]] = {}
    for row in rows:
        key = tuple(row.box_norm_xywh)
        groups.setdefault(key, []).append(CLASS_ID_TO_LABEL[row.class_id])

    result = []
    for index, (key, labels) in enumerate(groups.items()):
        norm = [round(value, 6) for value in key]
        result.append(
            {
                "box_id": str(index),
                "box_xyxy": yolo_to_pixel(norm, width, height),
                "box_norm_xywh": norm,
                "labels": validate_labels(labels),
            }
        )
    return result


def boxes_to_yolo_rows(boxes: list[dict], width: int, height: int) -> list[YoloRow]:
    rows = []
    for box in boxes:
        labels = validate_labels(list(box.get("labels") or []))
        norm = pixel_to_yolo(list(box["box_xyxy"]), width, height)
        for label in labels:
            rows.append(YoloRow(class_id=LABEL_TO_CLASS_ID[label], box_norm_xywh=norm))
    return rows
