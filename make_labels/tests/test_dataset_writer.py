from pathlib import Path

from PIL import Image

from app.dataset_writer import DatasetWriter, yolo_text_for_box


def test_yolo_text_for_multilabel_box_uses_fixed_class_order():
    text = yolo_text_for_box([960, 270, 1440, 810], width=1920, height=1080, labels=["teach", "stand"])

    assert text == "1 0.625000 0.500000 0.250000 0.500000\n3 0.625000 0.500000 0.250000 0.500000\n"


def test_dataset_writer_creates_incremental_batches(tmp_path):
    writer = DatasetWriter(output_root=tmp_path, batch_size=2, batch_prefix="batch_")
    source = tmp_path / "source.jpg"
    Image.new("RGB", (20, 20), "white").save(source)

    first = writer.write_sample(source, [1, 2, 10, 18], ["stand"], {"course_id": 1})
    second = writer.write_sample(source, [2, 2, 12, 18], ["stand", "teach"], {"course_id": 2})
    third = writer.write_sample(source, [3, 2, 13, 18], ["sit"], {"course_id": 3})

    assert first.image_path.parent == tmp_path / "batch_000001/images"
    assert second.image_path.parent == tmp_path / "batch_000001/images"
    assert third.image_path.parent == tmp_path / "batch_000002/images"
    assert (tmp_path / "batch_000001/classes.txt").read_text(encoding="utf-8") == "sit\nstand\nbbwriting\nteach\n"
    assert first.label_path.exists()
    assert third.label_path.exists()
