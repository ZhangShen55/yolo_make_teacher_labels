from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx

from .models import TeacherCandidate


OBJECT_TYPE_TO_LABEL = {
    201: "stand",
    202: "sit",
    203: "bbwriting",
    205: "teach",
}
LABEL_ORDER = ["sit", "stand", "bbwriting", "teach"]


def image_to_storage_path(image_path: str | Path) -> str:
    path = Path(image_path)
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def normalize_box(raw_box: dict[str, Any], width: int, height: int) -> list[int] | None:
    x1 = int(round(raw_box.get("LeftTopX", 0)))
    y1 = int(round(raw_box.get("LeftTopY", 0)))
    x2 = int(round(raw_box.get("RightBtmX", 0)))
    y2 = int(round(raw_box.get("RightBtmY", 0)))
    x1, x2 = sorted((max(0, min(width - 1, x1)), max(0, min(width - 1, x2))))
    y1, y2 = sorted((max(0, min(height - 1, y1)), max(0, min(height - 1, y2))))
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def box_area(box: list[int]) -> int:
    x1, y1, x2, y2 = box
    return (x2 - x1) * (y2 - y1)


def box_iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    return inter / (box_area(a) + box_area(b) - inter)


def ordered_labels(labels: list[str]) -> list[str]:
    seen = set(labels)
    return [label for label in LABEL_ORDER if label in seen]


def has_teacher_presence(result_item: dict[str, Any], object_type: int = 100, min_count: int = 1) -> bool:
    for item in result_item.get("ResultList") or []:
        if int(item.get("ObjectType", -1)) == object_type:
            return int(item.get("ObjectCount") or 0) >= min_count
    return False


def select_teacher_candidate(result_item: dict[str, Any], width: int, height: int) -> TeacherCandidate | None:
    groups: list[dict[str, Any]] = []
    for item in result_item.get("ResultList") or []:
        object_type = int(item.get("ObjectType", -1))
        if object_type not in OBJECT_TYPE_TO_LABEL:
            continue
        for raw_box in item.get("ObjectPostList") or []:
            box = normalize_box(raw_box, width, height)
            if box is None:
                continue
            match = None
            for group in groups:
                if box_iou(box, group["box"]) >= 0.85:
                    match = group
                    break
            if match is None:
                groups.append({"box": box, "boxes": [box], "object_types": {object_type}})
            else:
                match["boxes"].append(box)
                match["object_types"].add(object_type)
                match["box"] = max(match["boxes"], key=box_area)

    if not groups:
        return None
    selected = min(groups, key=lambda group: (group["box"][1], -box_area(group["box"])))
    object_types = sorted(selected["object_types"])
    return TeacherCandidate(
        box_xyxy=selected["box"],
        labels=ordered_labels([OBJECT_TYPE_TO_LABEL[item] for item in object_types]),
        object_types=object_types,
    )


def first_data_item(payload: dict[str, Any], image_id: str | None = None) -> dict[str, Any] | None:
    for item in payload.get("DataList") or []:
        status = item.get("StatusObject") or {}
        if image_id is None or status.get("ImageId") == image_id:
            return item
    return None


class TeacherDetectClient:
    def __init__(self, url: str, timeout_seconds: int = 30):
        self.url = url
        self.timeout_seconds = timeout_seconds

    async def detect_image(self, image_path: str, image_id: str) -> dict[str, Any]:
        payload = {"ImageList": [{"StoragePath": image_to_storage_path(image_path), "ImageId": image_id}]}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
            response = await client.post(self.url, json=payload)
        if response.status_code >= 400:
            body = response.text[:500].replace("\n", " ")
            raise RuntimeError(f"8881 teacher detect failed: HTTP {response.status_code}: {body}")
        return response.json()
