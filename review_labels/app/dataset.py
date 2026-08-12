from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image

from .annotations import load_annotation_map, read_jsonl
from .yolo import CLASS_ID_TO_LABEL, group_rows_by_box, parse_yolo_text


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def is_visible_file(path: Path) -> bool:
    return path.is_file() and not path.name.startswith(".")


def is_image_file(path: Path) -> bool:
    return is_visible_file(path) and path.suffix.lower() in IMAGE_SUFFIXES


def is_label_file(path: Path) -> bool:
    return is_visible_file(path) and path.suffix.lower() == ".txt"


class DatasetStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.images_dir = self.root / "images"
        self.labels_dir = self.root / "labels"
        self.raw_vlm_dir = self.root / "raw_vlm"
        self.annotations_path = self.root / "annotations.jsonl"
        self.classes_path = self.root / "classes.txt"
        self.backups_dir = self.root / "backups"
        self.rejected_dir = self.root / "rejected"
        self.rejected_images_dir = self.rejected_dir / "images"
        self.rejected_labels_dir = self.rejected_dir / "labels"
        self.rejected_raw_vlm_dir = self.rejected_dir / "raw_vlm"
        self.rejected_annotations_path = self.rejected_dir / "annotations.jsonl"
        self.reject_log_path = self.rejected_dir / "reject-log.jsonl"
        self._annotation_map: dict[str, dict] = {}
        self._details: dict[str, dict[str, Any]] = {}
        self._rows: list[dict[str, Any]] = []
        self._image_paths: dict[str, Path] = {}
        self._rejected_count = 0
        self._index_signature: tuple[int, int, int, int] | None = None
        self.validate()
        self.rebuild_index()

    def validate(self) -> None:
        if not self.root.exists():
            raise FileNotFoundError(f"Dataset does not exist: {self.root}")
        for path in [self.images_dir, self.labels_dir]:
            if not path.exists():
                raise FileNotFoundError(f"Required dataset folder missing: {path}")
        missing_labels = [image_path.name for image_path in self.image_files() if not self.label_path(image_path.stem).exists()]
        if missing_labels:
            preview = ", ".join(missing_labels[:10])
            suffix = "" if len(missing_labels) <= 10 else f", ... total {len(missing_labels)}"
            raise ValueError(f"Missing label files for images: {preview}{suffix}")

    def _path_mtime_ns(self, path: Path) -> int:
        try:
            return path.stat().st_mtime_ns
        except FileNotFoundError:
            return 0

    def _current_signature(self) -> tuple[int, int, int, int]:
        return (
            self._path_mtime_ns(self.images_dir),
            self._path_mtime_ns(self.labels_dir),
            self._path_mtime_ns(self.annotations_path),
            self._path_mtime_ns(self.rejected_images_dir),
        )

    def _maybe_refresh_index(self) -> None:
        signature = self._current_signature()
        if signature != self._index_signature:
            self.rebuild_index()

    def validation_report(self) -> dict:
        images = self.image_files()
        return {
            "dataset_root": str(self.root),
            "has_images_folder": self.images_dir.exists(),
            "has_labels_folder": self.labels_dir.exists(),
            "image_count": len(images),
            "label_count": len([path for path in self.labels_dir.iterdir() if is_label_file(path)]) if self.labels_dir.exists() else 0,
            "missing_labels": [],
        }

    def ensure_operational_dirs(self) -> None:
        for path in [
            self.backups_dir,
            self.rejected_images_dir,
            self.rejected_labels_dir,
            self.rejected_raw_vlm_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def image_files(self) -> list[Path]:
        return sorted(path for path in self.images_dir.iterdir() if is_image_file(path))

    def image_path(self, image_id: str) -> Path:
        cached = self._image_paths.get(image_id)
        if cached and cached.exists():
            return cached
        for suffix in [".jpg", ".jpeg", ".png", ".bmp", ".webp"]:
            path = self.images_dir / f"{image_id}{suffix}"
            if path.exists():
                return path
        raise FileNotFoundError(f"Image not found: {image_id}")

    def label_path(self, image_id: str) -> Path:
        return self.labels_dir / f"{image_id}.txt"

    def raw_vlm_path(self, image_id: str) -> Path:
        return self.raw_vlm_dir / f"{image_id}.json"

    def image_size(self, image_id: str) -> tuple[int, int]:
        detail = self._details.get(image_id)
        if detail:
            return int(detail["width"]), int(detail["height"])
        return self._read_image_size(image_id)

    def _read_image_size(self, image_id: str) -> tuple[int, int]:
        with Image.open(self.image_path(image_id)) as image:
            return image.size

    def _image_size_from_annotation(self, annotation: dict) -> tuple[int, int] | None:
        width = annotation.get("width")
        height = annotation.get("height")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return width, height
        return None

    def _detail_from_disk(self, image_path: Path, annotations: dict[str, dict]) -> dict[str, Any]:
        image_id = image_path.stem
        annotation = annotations.get(image_id, {})
        size = self._image_size_from_annotation(annotation)
        width, height = size if size else self._read_image_size(image_id)
        label_path = self.label_path(image_id)
        rows = parse_yolo_text(label_path.read_text(encoding="utf-8") if label_path.exists() else "")
        return {
            "image_id": image_id,
            "file_name": image_path.name,
            "width": width,
            "height": height,
            "boxes": group_rows_by_box(rows, width, height),
            "reason": annotation.get("reason", ""),
            "needs_review": bool(annotation.get("needs_review", False)),
            "image_url": f"/api/images/{image_id}/file",
        }

    def _row_from_detail(self, detail: dict[str, Any], annotations: dict[str, dict]) -> dict[str, Any]:
        labels = []
        for box in detail["boxes"]:
            for label in box["labels"]:
                if label not in labels:
                    labels.append(label)
        image_id = detail["image_id"]
        return {
            "image_id": image_id,
            "file_name": detail["file_name"],
            "labels": labels,
            "needs_review": bool(annotations.get(image_id, {}).get("needs_review", False)),
            "has_label": bool(detail["boxes"]),
        }

    def rebuild_index(self) -> None:
        annotations = load_annotation_map(self.annotations_path)
        image_paths = {path.stem: path for path in self.image_files() if self.label_path(path.stem).exists()}
        details = {
            image_id: self._detail_from_disk(path, annotations)
            for image_id, path in image_paths.items()
        }
        rows = [self._row_from_detail(details[image_id], annotations) for image_id in image_paths]
        self._annotation_map = annotations
        self._image_paths = image_paths
        self._details = details
        self._rows = rows
        self._rejected_count = len([path for path in self.rejected_images_dir.iterdir() if is_image_file(path)]) if self.rejected_images_dir.exists() else 0
        self._index_signature = self._current_signature()

    def refresh_image(self, image_id: str) -> None:
        self._annotation_map = load_annotation_map(self.annotations_path)
        image_path = self.image_path(image_id)
        detail = self._detail_from_disk(image_path, self._annotation_map)
        row = self._row_from_detail(detail, self._annotation_map)
        self._image_paths[image_id] = image_path
        self._details[image_id] = detail
        self._rows = [existing for existing in self._rows if existing["image_id"] != image_id]
        self._rows.append(row)
        self._rows.sort(key=lambda existing: existing["file_name"])
        self._index_signature = self._current_signature()

    def remove_image_from_index(self, image_id: str) -> None:
        self._annotation_map.pop(image_id, None)
        self._image_paths.pop(image_id, None)
        self._details.pop(image_id, None)
        self._rows = [row for row in self._rows if row["image_id"] != image_id]
        self._rejected_count = (
            len([path for path in self.rejected_images_dir.iterdir() if is_image_file(path)])
            if self.rejected_images_dir.exists()
            else self._rejected_count
        )
        self._index_signature = self._current_signature()

    def annotation_map(self) -> dict[str, dict]:
        self._maybe_refresh_index()
        return deepcopy(self._annotation_map)

    def get_detail(self, image_id: str) -> dict[str, Any]:
        self._maybe_refresh_index()
        detail = self._details.get(image_id)
        if not detail:
            raise FileNotFoundError(f"Image not found: {image_id}")
        return deepcopy(detail)

    def iter_rows(self) -> list[dict[str, Any]]:
        self._maybe_refresh_index()
        return deepcopy(self._rows)

    def filter_rows(self, q: str | None = None, label: str | None = None, needs_review: bool | None = None) -> list[dict]:
        rows = self.iter_rows()
        if q:
            rows = [row for row in rows if q.lower() in row["file_name"].lower()]
        if label:
            rows = [row for row in rows if label in row["labels"]]
        if needs_review is not None:
            rows = [row for row in rows if row["needs_review"] is needs_review]
        return rows

    def paginate(self, rows: list[dict], page: int = 1, page_size: int = 10) -> dict:
        page = max(1, int(page))
        page_size = min(50, max(1, int(page_size)))
        start = (page - 1) * page_size
        return {"page": page, "page_size": page_size, "total": len(rows), "items": rows[start:start + page_size]}

    def summary(self) -> dict:
        self._maybe_refresh_index()
        label_counts = {label: 0 for label in CLASS_ID_TO_LABEL.values()}
        for row in self._rows:
            for label in row["labels"]:
                label_counts[label] += 1
        return {
            "dataset_root": str(self.root),
            "total": len(self._rows) + self._rejected_count,
            "active": len(self._rows),
            "rejected": self._rejected_count,
            "label_counts": label_counts,
        }

    def rejected_annotation_rows(self) -> list[dict]:
        return read_jsonl(self.rejected_annotations_path)
