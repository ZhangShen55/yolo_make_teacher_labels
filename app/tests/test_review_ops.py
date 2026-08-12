import json
from pathlib import Path

from PIL import Image

from label_review.dataset import DatasetStore
from label_review.review_ops import reject_image, save_annotation


def make_dataset(tmp_path: Path) -> Path:
    root = tmp_path / "dataset"
    (root / "images").mkdir(parents=True)
    (root / "labels").mkdir()
    (root / "raw_vlm").mkdir()
    Image.new("RGB", (1920, 1080), "white").save(root / "images/frame_000001.jpg")
    (root / "labels/frame_000001.txt").write_text(
        "1 0.520833 0.671296 0.127083 0.314815\n3 0.520833 0.671296 0.127083 0.314815\n",
        encoding="utf-8",
    )
    (root / "raw_vlm/frame_000001.json").write_text('{"ok": true}\n', encoding="utf-8")
    (root / "classes.txt").write_text("sit\nstand\nbbwriting\nteach\n", encoding="utf-8")
    annotation = {
        "image": "frame_000001.jpg",
        "width": 1920,
        "height": 1080,
        "box_xyxy": [878, 555, 1122, 895],
        "box_norm_xywh": [0.520833, 0.671296, 0.127083, 0.314815],
        "labels": ["stand", "teach"],
        "needs_review": False,
        "reason": "seed",
    }
    (root / "annotations.jsonl").write_text(json.dumps(annotation, ensure_ascii=False) + "\n", encoding="utf-8")
    return root


def test_save_annotation_updates_yolo_and_jsonl(tmp_path):
    root = make_dataset(tmp_path)
    store = DatasetStore(root)

    saved = save_annotation(
        store,
        "frame_000001",
        [{"box_id": "0", "box_xyxy": [900, 500, 1100, 900], "labels": ["stand", "bbwriting"]}],
        needs_review=True,
    )

    assert saved["labels"] == ["stand", "bbwriting"]
    assert saved["needs_review"] is True
    assert (root / "labels/frame_000001.txt").read_text(encoding="utf-8") == (
        "1 0.520833 0.648148 0.104167 0.370370\n"
        "2 0.520833 0.648148 0.104167 0.370370\n"
    )
    rows = [json.loads(line) for line in (root / "annotations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["box_xyxy"] == [900, 500, 1100, 900]
    assert (root / "backups").exists()


def test_reject_image_moves_files_and_removes_active_annotation(tmp_path):
    root = make_dataset(tmp_path)
    store = DatasetStore(root)

    summary = reject_image(store, "frame_000001", reason="bad_frame")

    assert summary["active"] == 0
    assert (root / "rejected/images/frame_000001.jpg").exists()
    assert (root / "rejected/labels/frame_000001.txt").exists()
    assert (root / "rejected/raw_vlm/frame_000001.json").exists()
    assert not (root / "images/frame_000001.jpg").exists()
    assert (root / "annotations.jsonl").read_text(encoding="utf-8") == ""
    rejected_rows = (root / "rejected/annotations.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rejected_rows) == 1
    log = json.loads((root / "rejected/reject-log.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert log["image_id"] == "frame_000001"
    assert log["reason"] == "bad_frame"
