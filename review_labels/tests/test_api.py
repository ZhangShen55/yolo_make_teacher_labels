import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app


def make_dataset(tmp_path: Path, count: int = 12) -> Path:
    root = tmp_path / "dataset"
    (root / "images").mkdir(parents=True)
    (root / "labels").mkdir()
    (root / "raw_vlm").mkdir()
    annotations = []
    for idx in range(1, count + 1):
        image_id = f"frame_{idx:06d}"
        Image.new("RGB", (1920, 1080), "white").save(root / f"images/{image_id}.jpg")
        (root / f"labels/{image_id}.txt").write_text(
            "1 0.520833 0.671296 0.127083 0.314815\n3 0.520833 0.671296 0.127083 0.314815\n",
            encoding="utf-8",
        )
        annotations.append(
            {
                "image": f"{image_id}.jpg",
                "width": 1920,
                "height": 1080,
                "box_xyxy": [878, 555, 1122, 895],
                "box_norm_xywh": [0.520833, 0.671296, 0.127083, 0.314815],
                "labels": ["stand", "teach"],
                "needs_review": False,
            }
        )
    (root / "classes.txt").write_text("sit\nstand\nbbwriting\nteach\n", encoding="utf-8")
    (root / "annotations.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in annotations) + "\n",
        encoding="utf-8",
    )
    return root


def test_summary_and_batch_pagination(tmp_path):
    root = make_dataset(tmp_path, count=12)
    client = TestClient(create_app(root))

    summary = client.get("/api/dataset/summary").json()
    assert summary["active"] == 12
    assert summary["label_counts"] == {
        "sit": 0,
        "stand": 12,
        "bbwriting": 0,
        "teach": 12,
        "usephone": 0,
        "mic": 0,
    }

    page1 = client.get("/api/images/batch?page=1&page_size=10").json()
    page2 = client.get("/api/images/batch?page=2&page_size=10").json()
    assert len(page1["items"]) == 10
    assert len(page2["items"]) == 2
    assert page1["items"][0]["boxes"][0]["labels"] == ["stand", "teach"]


def test_patch_annotation_and_reject_endpoint(tmp_path):
    root = make_dataset(tmp_path, count=1)
    client = TestClient(create_app(root))

    response = client.patch(
        "/api/images/frame_000001/annotation",
        json={
            "boxes": [{"box_id": "0", "box_xyxy": [900, 500, 1100, 900], "labels": ["sit", "teach"]}],
            "needs_review": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["boxes"][0]["labels"] == ["sit", "teach"]
    assert (root / "labels/frame_000001.txt").read_text(encoding="utf-8").startswith("0 ")

    reject_response = client.post("/api/images/frame_000001/reject", json={"reason": "bad_frame"})
    assert reject_response.status_code == 200
    assert reject_response.json()["active"] == 0
    assert (root / "rejected/images/frame_000001.jpg").exists()


def test_patch_annotation_accepts_fractional_bbox_pixels(tmp_path):
    root = make_dataset(tmp_path, count=1)
    client = TestClient(create_app(root))

    response = client.patch(
        "/api/images/frame_000001/annotation",
        json={
            "boxes": [{"box_id": "0", "box_xyxy": [900.4, 500.2, 1100.7, 900.8], "labels": ["stand"]}],
            "needs_review": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["boxes"][0]["box_xyxy"] == [900, 500, 1101, 901]
    assert (root / "labels/frame_000001.txt").read_text(encoding="utf-8").startswith("1 ")


def test_new_behavior_labels_are_read_filtered_counted_and_saved(tmp_path):
    root = make_dataset(tmp_path, count=1)
    (root / "classes.txt").unlink()
    (root / "labels/frame_000001.txt").write_text(
        "1 0.520833 0.671296 0.127083 0.314815\n"
        "4 0.520833 0.671296 0.127083 0.314815\n"
        "5 0.520833 0.671296 0.127083 0.314815\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(root))

    summary = client.get("/api/dataset/summary").json()
    assert summary["label_counts"] == {
        "sit": 0,
        "stand": 1,
        "bbwriting": 0,
        "teach": 0,
        "usephone": 1,
        "mic": 1,
    }
    detail = client.get("/api/images/frame_000001").json()
    assert detail["boxes"][0]["labels"] == ["stand", "usephone", "mic"]
    assert [item["image_id"] for item in client.get("/api/images?label=usephone").json()["items"]] == [
        "frame_000001"
    ]

    response = client.patch(
        "/api/images/frame_000001/annotation",
        json={
            "boxes": [
                {
                    "box_id": "0",
                    "box_xyxy": [900, 500, 1100, 900],
                    "labels": ["mic", "stand", "usephone"],
                }
            ],
            "needs_review": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["labels"] == ["stand", "usephone", "mic"]
    assert (root / "labels/frame_000001.txt").read_text(encoding="utf-8") == (
        "1 0.520833 0.648148 0.104167 0.370370\n"
        "4 0.520833 0.648148 0.104167 0.370370\n"
        "5 0.520833 0.648148 0.104167 0.370370\n"
    )
