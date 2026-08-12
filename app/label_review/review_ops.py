from __future__ import annotations

from datetime import datetime
import json
import shutil
from pathlib import Path
from typing import Any

from .annotations import append_jsonl, atomic_write_text, remove_annotation, upsert_annotation
from .dataset import DatasetStore
from .yolo import boxes_to_yolo_rows, group_rows_by_box, parse_yolo_text, yolo_rows_to_text


def ensure_backup(store: DatasetStore) -> None:
    if store.backups_dir.exists() and any(store.backups_dir.iterdir()):
        return
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = store.backups_dir / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    if store.annotations_path.exists():
        shutil.copy2(store.annotations_path, backup_dir / "annotations.jsonl")
    if store.labels_dir.exists():
        shutil.copytree(store.labels_dir, backup_dir / "labels", dirs_exist_ok=True)


def annotation_from_boxes(store: DatasetStore, image_id: str, boxes: list[dict], needs_review: bool) -> dict[str, Any]:
    image_path = store.image_path(image_id)
    width, height = store.image_size(image_id)
    rows = boxes_to_yolo_rows(boxes, width, height)
    grouped = group_rows_by_box(rows, width, height)
    labels = []
    for box in grouped:
        for label in box["labels"]:
            if label not in labels:
                labels.append(label)
    first_box = grouped[0] if grouped else {"box_xyxy": None, "box_norm_xywh": None}
    previous = store.annotation_map().get(image_id, {})
    record = dict(previous)
    record.update(
        {
            "image": image_path.name,
            "image_path": str(image_path),
            "width": width,
            "height": height,
            "box_xyxy": first_box["box_xyxy"],
            "box_norm_xywh": first_box["box_norm_xywh"],
            "boxes": grouped,
            "labels": labels,
            "needs_review": needs_review,
        }
    )
    return record


def save_annotation(store: DatasetStore, image_id: str, boxes: list[dict], needs_review: bool = False) -> dict:
    ensure_backup(store)
    width, height = store.image_size(image_id)
    rows = boxes_to_yolo_rows(boxes, width, height)
    atomic_write_text(store.label_path(image_id), yolo_rows_to_text(rows))
    record = annotation_from_boxes(store, image_id, boxes, needs_review)
    upsert_annotation(store.annotations_path, image_id, record)
    store.refresh_image(image_id)
    return store.get_detail(image_id) | {"labels": record["labels"]}


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 10_000):
        candidate = path.with_name(f"{stem}.{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not create unique destination for {path}")


def move_if_exists(source: Path, destination: Path) -> Path | None:
    if not source.exists():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    final_destination = unique_destination(destination)
    shutil.move(str(source), str(final_destination))
    return final_destination


def reject_image(store: DatasetStore, image_id: str, reason: str = "") -> dict:
    ensure_backup(store)
    store.ensure_operational_dirs()
    image_path = store.image_path(image_id)
    label_path = store.label_path(image_id)
    raw_vlm_path = store.raw_vlm_path(image_id)
    annotation = remove_annotation(store.annotations_path, image_id)
    if annotation is None:
        annotation = {"image": image_path.name}
    annotation = dict(annotation)
    annotation["rejected_reason"] = reason
    annotation["rejected_at"] = datetime.now().isoformat(timespec="seconds")

    image_dest = move_if_exists(image_path, store.rejected_images_dir / image_path.name)
    label_dest = move_if_exists(label_path, store.rejected_labels_dir / label_path.name)
    raw_dest = move_if_exists(raw_vlm_path, store.rejected_raw_vlm_dir / raw_vlm_path.name)
    annotation["rejected_paths"] = {
        "image": str(image_dest) if image_dest else None,
        "label": str(label_dest) if label_dest else None,
        "raw_vlm": str(raw_dest) if raw_dest else None,
    }
    append_jsonl(store.rejected_annotations_path, annotation)
    append_jsonl(
        store.reject_log_path,
        {
            "image_id": image_id,
            "reason": reason,
            "timestamp": annotation["rejected_at"],
            "paths": annotation["rejected_paths"],
        },
    )
    store.remove_image_from_index(image_id)
    return store.summary()
