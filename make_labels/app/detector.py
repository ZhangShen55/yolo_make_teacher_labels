from __future__ import annotations

import asyncio
import base64
import random
import re
from pathlib import Path
from typing import Any

import httpx

from .models import TeacherCandidate


OBJECT_TYPE_TO_LABEL = {
    201: "sit",
    202: "stand",
    203: "bbwriting",
    204: "teach",
}
LABEL_ORDER = ["sit", "stand", "bbwriting", "teach"]
DATA_URL_PATTERN = re.compile(r"data:[^;,\s]+;base64,[A-Za-z0-9+/=\r\n]+")


class DetectResponseError(RuntimeError):
    """ImageDetect returned an invalid or failed response."""


class DetectContractError(DetectResponseError):
    """The service response does not match the configured v6 contract."""


def sanitized_response_body(text: str, limit: int = 500) -> str:
    return DATA_URL_PATTERN.sub("[base64 redacted]", text).replace("\n", " ")[:limit]


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


def ordered_labels(labels: list[str]) -> list[str]:
    seen = set(labels)
    return [label for label in LABEL_ORDER if label in seen]


def has_teacher_presence(result_item: dict[str, Any], object_type: int = 100, min_count: int = 1) -> bool:
    for item in result_item.get("ResultList") or []:
        if int(item.get("ObjectType", -1)) == object_type:
            return (
                int(item.get("ObjectCount") or 0) >= min_count
                or bool(item.get("ObjectPostList") or [])
            )
    return False


def select_teacher_candidate(result_item: dict[str, Any], width: int, height: int) -> TeacherCandidate | None:
    subject_boxes: list[dict[str, Any]] = []
    subject_items: list[dict[str, Any]] = []
    behavior_items: list[dict[str, Any]] = []
    behavior_types: list[int] = []
    needs_review = False

    for item in result_item.get("ResultList") or []:
        object_type = int(item.get("ObjectType", -1))
        object_count = int(item.get("ObjectCount") or 0)
        if object_type == 205:
            raise DetectContractError("unexpected legacy ObjectType 205 in v6 teacher response")
        if object_type == 100:
            raw_boxes = item.get("ObjectPostList") or []
            subject_items.append(dict(item))
            if raw_boxes and object_count != len(raw_boxes):
                needs_review = True
            for index, raw_box in enumerate(raw_boxes):
                box = normalize_box(raw_box, width, height)
                if box is None:
                    continue
                raw_confidence = raw_box.get("Confidence")
                confidence = float(raw_confidence) if isinstance(raw_confidence, (int, float)) else None
                subject_boxes.append(
                    {
                        "index": index,
                        "box_xyxy": box,
                        "confidence": confidence,
                        "raw": dict(raw_box),
                    }
                )
            continue
        if object_type in OBJECT_TYPE_TO_LABEL:
            behavior_items.append(dict(item))
            raw_boxes = item.get("ObjectPostList") or []
            if raw_boxes and object_count != len(raw_boxes):
                needs_review = True
            if object_count > 0:
                behavior_types.append(object_type)
            if item.get("SuspectedSitting") is True or item.get("PostureFallback") is True:
                needs_review = True
            for raw_box in item.get("ObjectPostList") or []:
                if raw_box.get("SuspectedSitting") is True or raw_box.get("PostureFallback") is True:
                    needs_review = True

    if not subject_boxes:
        return None
    selected = min(
        subject_boxes,
        key=lambda item: (
            -(item["confidence"] if item["confidence"] is not None else float("-inf")),
            -box_area(item["box_xyxy"]),
            item["index"],
        ),
    )
    object_types = sorted(set(behavior_types))
    labels = ordered_labels([OBJECT_TYPE_TO_LABEL[item] for item in object_types])
    if "sit" in labels and "stand" in labels:
        needs_review = True
    if len(subject_boxes) > 1:
        needs_review = True
    return TeacherCandidate(
        box_xyxy=selected["box_xyxy"],
        labels=labels,
        object_types=object_types,
        confidence=selected["confidence"],
        needs_review=needs_review,
        detector_metadata={
            "contract_version": "teacher-v6",
            "subject_item": subject_items[0] if len(subject_items) == 1 else None,
            "subject_items": subject_items,
            "subject_boxes": subject_boxes,
            "selected_subject_index": selected["index"],
            "behavior_items": behavior_items,
        },
    )


def first_data_item(payload: dict[str, Any], image_id: str | None = None) -> dict[str, Any] | None:
    for item in payload.get("DataList") or []:
        status = item.get("StatusObject") or {}
        if image_id is None or status.get("ImageId") == image_id:
            return item
    return None


def validate_detect_response(
    payload: dict[str, Any],
    image_id: str,
    expected_image_ids: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DetectResponseError("teacher detect response must be a JSON object")
    root_status = payload.get("StatusObject")
    if not isinstance(root_status, dict) or root_status.get("StatusCode") != 0:
        raise DetectResponseError("root StatusObject.StatusCode is not successful")

    expected_ids = expected_image_ids or {image_id}
    root_image_ids = root_status.get("ImageIdList")
    if root_image_ids is not None and set(root_image_ids) != expected_ids:
        raise DetectResponseError("root ImageIdList does not match requested image IDs")
    items_by_id: dict[str, list[dict[str, Any]]] = {}
    for item in payload.get("DataList") or []:
        status = item.get("StatusObject") if isinstance(item, dict) else None
        item_id = status.get("ImageId") if isinstance(status, dict) else None
        if not isinstance(item_id, str):
            raise DetectResponseError("DataList item is missing StatusObject.ImageId")
        items_by_id.setdefault(item_id, []).append(item)

    unexpected_ids = set(items_by_id) - expected_ids
    if unexpected_ids:
        raise DetectResponseError(f"unexpected DataList ImageId values: {sorted(unexpected_ids)}")
    missing_ids = expected_ids - set(items_by_id)
    if missing_ids:
        raise DetectResponseError(f"missing DataList results for ImageId values: {sorted(missing_ids)}")
    duplicate_ids = sorted(item_id for item_id, items in items_by_id.items() if len(items) > 1)
    if duplicate_ids:
        raise DetectResponseError(f"duplicate DataList results for ImageId values: {duplicate_ids}")

    item = items_by_id[image_id][0]
    item_status = item.get("StatusObject") or {}
    if item_status.get("StatusCode") != 0:
        raise DetectResponseError(f"single-image StatusObject.StatusCode failed for ImageId={image_id}")
    return item


class TeacherDetectClient:
    def __init__(self, url: str, timeout_seconds: int = 30):
        self.url = url
        self.timeout_seconds = timeout_seconds

    async def detect_image(self, image_path: str, image_id: str) -> dict[str, Any]:
        payload = {
            "batch_id": image_id,
            "stream_type": "teacher",
            "ReturnHeadPose": False,
            "ImageList": [{"StoragePath": image_to_storage_path(image_path), "ImageId": image_id}],
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
            for attempt in range(3):
                try:
                    response = await client.post(self.url, json=payload)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt == 2:
                        raise DetectResponseError(f"teacher detect failed after 3 attempts: {exc}") from exc
                    await asyncio.sleep(self._retry_delay(attempt, None))
                    continue

                if 200 <= response.status_code < 300:
                    try:
                        response_payload = response.json()
                    except (TypeError, ValueError) as exc:
                        raise DetectResponseError("teacher detect returned invalid JSON") from exc
                    validate_detect_response(response_payload, image_id)
                    return response_payload

                body = sanitized_response_body(response.text)
                if response.status_code not in {429, 500, 503}:
                    raise DetectResponseError(
                        f"teacher detect failed: HTTP {response.status_code}: {body}"
                    )
                if attempt == 2:
                    raise DetectResponseError(
                        f"teacher detect failed after 3 attempts: HTTP {response.status_code}: {body}"
                    )
                await asyncio.sleep(self._retry_delay(attempt, response.headers.get("Retry-After")))

        raise DetectResponseError("teacher detect failed after 3 attempts")

    @staticmethod
    def _retry_delay(attempt: int, retry_after: str | None) -> float:
        if retry_after is not None:
            try:
                return max(0.0, min(30.0, float(retry_after)))
            except ValueError:
                pass
        return float(2**attempt) + random.uniform(0.0, 0.5)
