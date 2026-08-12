from scripts.teacher_vlm_labeler import (
    LABEL_TO_CLASS_ID,
    normalize_xyxy_to_yolo,
    parse_vlm_labels,
    select_teacher_candidate,
)


def test_select_teacher_candidate_keeps_supported_types_and_prefers_top_edge():
    result_item = {
        "ResultList": [
            {
                "ObjectType": 100,
                "ObjectPostList": [
                    {"LeftTopX": 0, "LeftTopY": 10, "RightBtmX": 100, "RightBtmY": 200}
                ],
            },
            {
                "ObjectType": 202,
                "ObjectPostList": [
                    {"LeftTopX": 20, "LeftTopY": 700, "RightBtmX": 200, "RightBtmY": 1000}
                ],
            },
            {
                "ObjectType": 201,
                "ObjectPostList": [
                    {"LeftTopX": 900, "LeftTopY": 500, "RightBtmX": 1100, "RightBtmY": 900}
                ],
            },
            {
                "ObjectType": 204,
                "ObjectPostList": [
                    {"LeftTopX": 850, "LeftTopY": 450, "RightBtmX": 1150, "RightBtmY": 920}
                ],
            },
        ]
    }

    candidate = select_teacher_candidate(result_item, width=1920, height=1080)

    assert candidate is not None
    assert candidate.box_xyxy == [900, 500, 1100, 900]
    assert candidate.source_api_labels == ["站立"]


def test_select_teacher_candidate_breaks_same_top_edge_by_larger_area():
    result_item = {
        "ResultList": [
            {
                "ObjectType": 201,
                "ObjectPostList": [
                    {"LeftTopX": 100, "LeftTopY": 500, "RightBtmX": 200, "RightBtmY": 700},
                    {"LeftTopX": 300, "LeftTopY": 500, "RightBtmX": 700, "RightBtmY": 900},
                ],
            }
        ]
    }

    candidate = select_teacher_candidate(result_item, width=1920, height=1080)

    assert candidate is not None
    assert candidate.box_xyxy == [300, 500, 700, 900]


def test_parse_vlm_labels_enforces_sit_stand_mutex_and_multilabel_actions():
    response_text = """
    ```json
    {"labels": ["sit", "stand", "bbwriting", "teach"], "reason": "conflict"}
    ```
    """

    parsed = parse_vlm_labels(response_text, source_api_labels=["坐着"])

    assert parsed["labels"] == ["sit", "bbwriting", "teach"]
    assert parsed["needs_review"] is True


def test_parse_vlm_labels_accepts_boolean_shape_and_adds_review_when_no_pose():
    response_text = '{"sit": false, "stand": false, "bbwriting": false, "teach": true}'

    parsed = parse_vlm_labels(response_text, source_api_labels=["站立"])

    assert parsed["labels"] == ["stand", "teach"]
    assert parsed["needs_review"] is True


def test_normalize_xyxy_to_yolo():
    normalized = normalize_xyxy_to_yolo([960, 270, 1440, 810], width=1920, height=1080)

    assert normalized == [0.625, 0.5, 0.25, 0.5]
    assert LABEL_TO_CLASS_ID == {"sit": 0, "stand": 1, "bbwriting": 2, "teach": 3}
