from app.yolo import (
    CLASS_ID_TO_LABEL,
    LABEL_TO_CLASS_ID,
    boxes_to_yolo_rows,
    group_rows_by_box,
    parse_yolo_text,
    pixel_to_yolo,
    validate_labels,
    yolo_to_pixel,
    yolo_rows_to_text,
)


def test_yolo_coordinate_roundtrip():
    box = [878, 555, 1122, 895]

    norm = pixel_to_yolo(box, width=1920, height=1080)
    restored = yolo_to_pixel(norm, width=1920, height=1080)

    assert norm == [0.520833, 0.671296, 0.127083, 0.314815]
    assert restored == box


def test_parse_and_write_multilabel_yolo_rows():
    text = (
        "1 0.520833 0.671296 0.127083 0.314815\n"
        "3 0.520833 0.671296 0.127083 0.314815\n"
        "4 0.520833 0.671296 0.127083 0.314815\n"
        "5 0.520833 0.671296 0.127083 0.314815\n"
    )

    rows = parse_yolo_text(text)
    groups = group_rows_by_box(rows, width=1920, height=1080)

    assert LABEL_TO_CLASS_ID == {
        "sit": 0,
        "stand": 1,
        "bbwriting": 2,
        "teach": 3,
        "usephone": 4,
        "mic": 5,
    }
    assert CLASS_ID_TO_LABEL[3] == "teach"
    assert CLASS_ID_TO_LABEL[4] == "usephone"
    assert CLASS_ID_TO_LABEL[5] == "mic"
    assert groups == [
        {
            "box_id": "0",
            "box_xyxy": [878, 555, 1122, 895],
            "box_norm_xywh": [0.520833, 0.671296, 0.127083, 0.314815],
            "labels": ["stand", "teach", "usephone", "mic"],
        }
    ]
    assert yolo_rows_to_text(rows) == text


def test_new_behavior_labels_are_written_in_canonical_order():
    rows = boxes_to_yolo_rows(
        [{"box_xyxy": [878, 555, 1122, 895], "labels": ["mic", "stand", "usephone"]}],
        width=1920,
        height=1080,
    )

    assert [row.class_id for row in rows] == [1, 4, 5]


def test_validate_labels_enforces_pose_mutex():
    assert validate_labels(["teach", "stand"]) == ["stand", "teach"]
    assert validate_labels(["mic", "stand", "usephone", "mic"]) == ["stand", "usephone", "mic"]

    for labels in ([], ["sit", "stand"], ["teach"], ["phone", "stand"]):
        try:
            validate_labels(labels)
        except ValueError:
            pass
        else:
            raise AssertionError(f"labels should be invalid: {labels}")
