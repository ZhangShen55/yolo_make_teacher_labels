from __future__ import annotations

import json
import random
import shutil
import string
from pathlib import Path
from typing import Any

from PIL import Image

from .models import SampleWriteResult


LABEL_TO_CLASS_ID = {"sit": 0, "stand": 1, "bbwriting": 2, "teach": 3}
LABEL_ORDER = ["sit", "stand", "bbwriting", "teach"]


def ordered_labels(labels: list[str]) -> list[str]:
    seen = set(labels)
    result = [label for label in LABEL_ORDER if label in seen]
    if ("sit" in result) == ("stand" in result):
        raise ValueError("Exactly one of sit or stand is required")
    return result


def normalize_xyxy_to_yolo(box_xyxy: list[int], width: int, height: int) -> list[float]:
    x1, y1, x2, y2 = [int(round(value)) for value in box_xyxy]
    return [
        round(((x1 + x2) / 2) / width, 6),
        round(((y1 + y2) / 2) / height, 6),
        round((x2 - x1) / width, 6),
        round((y2 - y1) / height, 6),
    ]


def yolo_text_for_box(box_xyxy: list[int], width: int, height: int, labels: list[str]) -> str:
    norm = normalize_xyxy_to_yolo(box_xyxy, width, height)
    lines = []
    for label in ordered_labels(labels):
        class_id = LABEL_TO_CLASS_ID[label]
        lines.append(f"{class_id} " + " ".join(f"{value:.6f}" for value in norm))
    return "\n".join(lines) + "\n"


def random_suffix(length: int = 4) -> str:
    return "".join(random.choice(string.ascii_lowercase) for _ in range(length))


class DatasetWriter:
    def __init__(self, output_root: str | Path, batch_size: int = 1000, batch_prefix: str = "batch_"):
        self.output_root = Path(output_root).expanduser().resolve()
        self.batch_size = batch_size
        self.batch_prefix = batch_prefix
        self.output_root.mkdir(parents=True, exist_ok=True)

    def batch_dir(self, batch_index: int) -> Path:
        return self.output_root / f"{self.batch_prefix}{batch_index:06d}"

    def current_batch_dir(self) -> Path:
        index = 1
        while True:
            batch = self.batch_dir(index)
            images_dir = batch / "images"
            count = len(list(images_dir.glob("*"))) if images_dir.exists() else 0
            if count < self.batch_size:
                return batch
            index += 1

    def next_image_index(self, batch_dir: Path) -> int:
        images_dir = batch_dir / "images"
        if not images_dir.exists():
            return 1
        max_index = 0
        for path in images_dir.iterdir():
            prefix = path.stem.split("-", 1)[0]
            if prefix.isdigit():
                max_index = max(max_index, int(prefix))
        return max_index + 1

    def ensure_batch_dirs(self, batch_dir: Path) -> None:
        for name in ["images", "labels", "raw", "preview", "failed"]:
            (batch_dir / name).mkdir(parents=True, exist_ok=True)
        classes = batch_dir / "classes.txt"
        if not classes.exists():
            classes.write_text("sit\nstand\nbbwriting\nteach\n", encoding="utf-8")

    def write_sample(
        self,
        source_image: str | Path,
        box_xyxy: list[int],
        labels: list[str],
        metadata: dict[str, Any],
    ) -> SampleWriteResult:
        source_image = Path(source_image)
        batch = self.current_batch_dir()
        self.ensure_batch_dirs(batch)
        index = self.next_image_index(batch)
        image_id = f"{index:08d}-{random_suffix()}"
        image_path = batch / "images" / f"{image_id}{source_image.suffix.lower() or '.jpg'}"
        label_path = batch / "labels" / f"{image_id}.txt"
        annotation_path = batch / "annotations.jsonl"

        shutil.copy2(source_image, image_path)
        with Image.open(image_path) as image:
            width, height = image.size
        label_path.write_text(yolo_text_for_box(box_xyxy, width, height, labels), encoding="utf-8")
        record = dict(metadata)
        record.update(
            {
                "image": image_path.name,
                "image_id": image_id,
                "width": width,
                "height": height,
                "box_xyxy": [int(round(value)) for value in box_xyxy],
                "box_norm_xywh": normalize_xyxy_to_yolo(box_xyxy, width, height),
                "labels": ordered_labels(labels),
            }
        )
        with annotation_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

        return SampleWriteResult(
            image_id=image_id,
            image_path=image_path,
            label_path=label_path,
            annotation_path=annotation_path,
            batch_dir=batch,
        )
