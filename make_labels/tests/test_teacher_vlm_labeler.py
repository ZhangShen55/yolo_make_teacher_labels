import requests
import pytest

from app.detector import DetectContractError, DetectResponseError
from scripts.teacher_vlm_labeler import (
    LABEL_TO_CLASS_ID,
    build_output_names,
    detect_teacher_batch,
    normalize_xyxy_to_yolo,
    parse_vlm_labels,
    post_detect_json_with_retries,
    select_candidate_for_offline,
    select_teacher_candidate,
)


def test_select_teacher_candidate_uses_shared_v6_subject_and_behavior_contract():
    result_item = {
        "ResultList": [
            {
                "ObjectType": 100,
                "ObjectCount": 1,
                "ObjectPostList": [
                    {
                        "LeftTopX": 900,
                        "LeftTopY": 500,
                        "RightBtmX": 1100,
                        "RightBtmY": 900,
                        "Confidence": 0.88,
                    }
                ],
            },
            {
                "ObjectType": 202,
                "ObjectCount": 1,
                "ObjectPostList": None,
            },
            {
                "ObjectType": 203,
                "ObjectCount": 1,
                "ObjectPostList": None,
            },
            {
                "ObjectType": 204,
                "ObjectCount": 1,
                "ObjectPostList": None,
            },
        ]
    }

    candidate = select_teacher_candidate(result_item, width=1920, height=1080)

    assert candidate is not None
    assert candidate.box_xyxy == [900, 500, 1100, 900]
    assert candidate.labels == ["stand", "bbwriting", "teach"]
    assert candidate.object_types == [202, 203, 204]


def test_select_teacher_candidate_rejects_legacy_205_in_offline_script():
    result_item = {
        "ResultList": [
            {
                "ObjectType": 100,
                "ObjectCount": 1,
                "ObjectPostList": [
                    {"LeftTopX": 10, "LeftTopY": 10, "RightBtmX": 100, "RightBtmY": 200}
                ],
            },
            {"ObjectType": 205, "ObjectCount": 1, "ObjectPostList": None},
        ]
    }

    with pytest.raises(DetectContractError, match="205"):
        select_teacher_candidate(result_item, width=1920, height=1080)


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


def test_post_detect_json_retries_retryable_status_and_honors_retry_after(monkeypatch):
    calls = []
    sleeps = []

    class FakeResponse:
        def __init__(self, status_code, payload=None, headers=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.headers = headers or {}
            self.text = "busy"

        def json(self):
            return self._payload

    responses = [
        FakeResponse(503, headers={"Retry-After": "40"}),
        FakeResponse(200, {"StatusObject": {"StatusCode": 0}}),
    ]

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return responses.pop(0)

    monkeypatch.setattr("scripts.teacher_vlm_labeler.requests.post", fake_post)
    monkeypatch.setattr("scripts.teacher_vlm_labeler.time.sleep", sleeps.append)

    result = post_detect_json_with_retries("http://127.0.0.1:8871", {"ImageList": []})

    assert result == {"StatusObject": {"StatusCode": 0}}
    assert len(calls) == 2
    assert sleeps == [30.0]


def test_post_detect_json_retries_connection_errors_three_total_attempts(monkeypatch):
    calls = []
    sleeps = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("scripts.teacher_vlm_labeler.requests.post", fake_post)
    monkeypatch.setattr("scripts.teacher_vlm_labeler.time.sleep", sleeps.append)
    monkeypatch.setattr("scripts.teacher_vlm_labeler.random.uniform", lambda _start, _end: 0.0)

    with pytest.raises(DetectResponseError, match="3 attempts"):
        post_detect_json_with_retries("http://127.0.0.1:8871", {"ImageList": []})

    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize("status_code", [400, 401, 404, 422])
def test_post_detect_json_does_not_retry_other_4xx(monkeypatch, status_code):
    calls = []

    class FakeResponse:
        headers = {}
        text = "invalid request"

        def __init__(self):
            self.status_code = status_code

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr("scripts.teacher_vlm_labeler.requests.post", fake_post)

    with pytest.raises(DetectResponseError, match=f"HTTP {status_code}"):
        post_detect_json_with_retries("http://127.0.0.1:8871", {"ImageList": []})

    assert len(calls) == 1


def test_post_detect_json_redacts_base64_from_http_error(monkeypatch):
    class FakeResponse:
        status_code = 422
        headers = {}
        text = 'invalid StoragePath=data:image/jpeg;base64,' + ('A' * 300)

    monkeypatch.setattr(
        "scripts.teacher_vlm_labeler.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(DetectResponseError) as exc_info:
        post_detect_json_with_retries("http://127.0.0.1:8871", {"ImageList": []})

    assert "A" * 80 not in str(exc_info.value)
    assert "[base64 redacted]" in str(exc_info.value)


def test_detect_teacher_batch_uses_unique_ids_for_same_stem(monkeypatch, tmp_path):
    jpg = tmp_path / "frame.jpg"
    png = tmp_path / "frame.png"
    jpg.write_bytes(b"jpg")
    png.write_bytes(b"png")
    captured = {}

    def fake_post(_url, payload, timeout):
        captured["payload"] = payload
        return {
            "StatusObject": {"StatusCode": 0},
            "DataList": [
                {
                    "StatusObject": {"StatusCode": 0, "ImageId": item["ImageId"]},
                    "ResultList": [],
                }
                for item in payload["ImageList"]
            ],
        }

    monkeypatch.setattr("scripts.teacher_vlm_labeler.post_detect_json_with_retries", fake_post)

    results = detect_teacher_batch([jpg, png], "http://127.0.0.1:8871")

    image_ids = [item["ImageId"] for item in captured["payload"]["ImageList"]]
    assert len(set(image_ids)) == 2
    assert set(results) == {jpg, png}


def test_build_output_names_avoids_same_stem_label_collisions(tmp_path):
    jpg = tmp_path / "frame.jpg"
    png = tmp_path / "frame.png"

    names = build_output_names([jpg, png])

    assert names[jpg].stem != names[png].stem
    assert names[jpg].suffix == ".jpg"
    assert names[png].suffix == ".png"


def test_select_candidate_for_offline_contains_legacy_205_to_one_image():
    result_item = {
        "ResultList": [
            {
                "ObjectType": 100,
                "ObjectCount": 1,
                "ObjectPostList": [
                    {"LeftTopX": 10, "LeftTopY": 10, "RightBtmX": 100, "RightBtmY": 200}
                ],
            },
            {"ObjectType": 205, "ObjectCount": 0, "ObjectPostList": None},
        ]
    }

    candidate, error = select_candidate_for_offline(result_item, width=300, height=300)

    assert candidate is None
    assert "205" in error
