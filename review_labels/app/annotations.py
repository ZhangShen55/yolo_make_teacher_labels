from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def image_id_from_record(record: dict) -> str:
    image = record.get("image") or record.get("file_name") or record.get("image_id")
    if not image:
        raise ValueError(f"Annotation missing image field: {record}")
    return Path(str(image)).stem


def load_annotation_map(path: Path) -> dict[str, dict]:
    return {image_id_from_record(row): row for row in read_jsonl(path)}


def upsert_annotation(path: Path, image_id: str, record: dict) -> None:
    rows = read_jsonl(path)
    replaced = False
    for index, row in enumerate(rows):
        if image_id_from_record(row) == image_id:
            rows[index] = record
            replaced = True
            break
    if not replaced:
        rows.append(record)
    write_jsonl(path, rows)


def remove_annotation(path: Path, image_id: str) -> dict | None:
    rows = read_jsonl(path)
    kept = []
    removed = None
    for row in rows:
        if image_id_from_record(row) == image_id:
            removed = row
        else:
            kept.append(row)
    write_jsonl(path, kept)
    return removed


def append_jsonl(path: Path, record: dict) -> None:
    rows = read_jsonl(path)
    rows.append(record)
    write_jsonl(path, rows)
