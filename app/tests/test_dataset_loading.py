import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from label_review.dataset import DatasetStore
from main import create_app


def make_dataset(root: Path, count: int = 2) -> Path:
    (root / "images").mkdir(parents=True)
    (root / "labels").mkdir()
    annotations = []
    for idx in range(1, count + 1):
        image_id = f"frame_{idx:06d}"
        Image.new("RGB", (1920, 1080), "white").save(root / f"images/{image_id}.jpg")
        (root / f"labels/{image_id}.txt").write_text(
            "1 0.520833 0.671296 0.127083 0.314815\n",
            encoding="utf-8",
        )
        annotations.append(
            {
                "image": f"{image_id}.jpg",
                "width": 1920,
                "height": 1080,
                "box_xyxy": [878, 555, 1122, 895],
                "labels": ["stand"],
                "needs_review": False,
            }
        )
    (root / "annotations.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in annotations) + "\n",
        encoding="utf-8",
    )
    return root


def test_dataset_requires_images_and_labels_folders(tmp_path):
    root = tmp_path / "dataset"
    root.mkdir()

    with pytest.raises(FileNotFoundError, match="images"):
        DatasetStore(root)

    (root / "images").mkdir()
    with pytest.raises(FileNotFoundError, match="labels"):
        DatasetStore(root)


def test_dataset_requires_label_file_for_each_image(tmp_path):
    root = make_dataset(tmp_path / "dataset", count=2)
    (root / "labels/frame_000002.txt").unlink()

    with pytest.raises(ValueError, match="Missing label files"):
        DatasetStore(root)


def test_dataset_ignores_macos_appledouble_files(tmp_path):
    root = make_dataset(tmp_path / "dataset", count=1)
    (root / "images/._frame_000001.jpg").write_bytes(b"not an image")
    (root / "labels/._frame_000001.txt").write_text("", encoding="utf-8")

    store = DatasetStore(root)

    assert store.summary()["active"] == 1
    assert [row["file_name"] for row in store.iter_rows()] == ["frame_000001.jpg"]


def test_load_dataset_endpoint_switches_current_dataset(tmp_path):
    first = make_dataset(tmp_path / "first", count=1)
    second = make_dataset(tmp_path / "second", count=2)
    client = TestClient(create_app(first))

    response = client.post("/api/dataset/load", json={"dataset_root": str(second)})

    assert response.status_code == 200
    assert response.json()["summary"]["active"] == 2
    assert client.get("/api/dataset/summary").json()["active"] == 2


def test_load_dataset_endpoint_rejects_missing_label_files(tmp_path):
    valid = make_dataset(tmp_path / "valid", count=1)
    invalid = make_dataset(tmp_path / "invalid", count=1)
    (invalid / "labels/frame_000001.txt").unlink()
    client = TestClient(create_app(valid))

    response = client.post("/api/dataset/load", json={"dataset_root": str(invalid)})

    assert response.status_code == 400
    assert "Missing label files" in response.json()["detail"]
    assert client.get("/api/dataset/summary").json()["active"] == 1


def test_summary_list_and_detail_use_loaded_index(tmp_path, monkeypatch):
    root = make_dataset(tmp_path / "dataset", count=3)
    store = DatasetStore(root)

    def fail_if_image_size_is_read(image_id: str):
        raise AssertionError(f"unexpected image size read for {image_id}")

    monkeypatch.setattr(store, "image_size", fail_if_image_size_is_read)

    assert store.summary()["active"] == 3
    assert len(store.filter_rows(label="stand")) == 3
    detail = store.get_detail("frame_000001")
    assert detail["width"] == 1920
    assert detail["height"] == 1080
    assert detail["boxes"][0]["labels"] == ["stand"]
