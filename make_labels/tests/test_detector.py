import asyncio

import pytest

from app.detector import (
    DetectContractError,
    DetectResponseError,
    TeacherDetectClient,
    has_teacher_presence,
    image_to_storage_path,
    select_teacher_candidate,
    validate_detect_response,
)


def test_has_teacher_presence_uses_object_type_100_count():
    result_item = {
        "ResultList": [
            {"ObjectType": 100, "ObjectCount": 0, "ObjectPostList": []},
            {"ObjectType": 201, "ObjectCount": 1, "ObjectPostList": []},
        ]
    }
    assert has_teacher_presence(result_item, object_type=100, min_count=1) is False

    result_item["ResultList"][0]["ObjectCount"] = 1
    assert has_teacher_presence(result_item, object_type=100, min_count=1) is True


def test_has_teacher_presence_keeps_count_box_mismatch_for_candidate_review():
    result_item = {
        "ResultList": [
            {
                "ObjectType": 100,
                "ObjectCount": 0,
                "ObjectPostList": [
                    {"LeftTopX": 10, "LeftTopY": 20, "RightBtmX": 110, "RightBtmY": 220}
                ],
            }
        ]
    }

    assert has_teacher_presence(result_item, object_type=100, min_count=1) is True


def test_select_teacher_candidate_uses_v6_subject_box_and_count_based_behaviors():
    result_item = {
        "ResultList": [
            {
                "ObjectType": 100,
                "ObjectCount": 1,
                "ObjectPostList": [
                    {
                        "LeftTopX": 600,
                        "LeftTopY": 160,
                        "RightBtmX": 980,
                        "RightBtmY": 920,
                        "Confidence": 0.91,
                    }
                ],
            },
            {
                "ObjectType": 201,
                "ObjectCount": 0,
                "ObjectPostList": None,
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
    assert candidate.box_xyxy == [600, 160, 980, 920]
    assert candidate.labels == ["stand", "bbwriting", "teach"]
    assert candidate.object_types == [202, 203, 204]
    assert candidate.confidence == 0.91
    assert candidate.needs_review is False


def test_select_teacher_candidate_maps_v6_sitting_and_marks_conflict_for_review():
    result_item = {
        "ResultList": [
            {
                "ObjectType": 100,
                "ObjectCount": 1,
                "ObjectPostList": [
                    {"LeftTopX": 10, "LeftTopY": 20, "RightBtmX": 110, "RightBtmY": 220}
                ],
            },
            {"ObjectType": 201, "ObjectCount": 1, "ObjectPostList": None},
            {"ObjectType": 202, "ObjectCount": 1, "ObjectPostList": None},
        ]
    }

    candidate = select_teacher_candidate(result_item, width=300, height=300)

    assert candidate is not None
    assert candidate.labels == ["sit", "stand"]
    assert candidate.needs_review is True


@pytest.mark.parametrize(
    "subject_count, subject_boxes",
    [
        (
            0,
            [{"LeftTopX": 10, "LeftTopY": 20, "RightBtmX": 110, "RightBtmY": 220}],
        ),
        (
            2,
            [{"LeftTopX": 10, "LeftTopY": 20, "RightBtmX": 110, "RightBtmY": 220}],
        ),
    ],
)
def test_select_teacher_candidate_marks_subject_count_box_mismatch_for_review(
    subject_count, subject_boxes
):
    result_item = {
        "ResultList": [
            {
                "ObjectType": 100,
                "ObjectCount": subject_count,
                "ObjectPostList": subject_boxes,
            },
            {"ObjectType": 202, "ObjectCount": 1, "ObjectPostList": None},
        ]
    }

    candidate = select_teacher_candidate(result_item, width=300, height=300)

    assert candidate is not None
    assert candidate.needs_review is True
    assert candidate.detector_metadata["subject_item"]["ObjectCount"] == subject_count


def test_select_teacher_candidate_marks_zero_count_with_behavior_boxes_for_review():
    result_item = {
        "ResultList": [
            {
                "ObjectType": 100,
                "ObjectCount": 1,
                "ObjectPostList": [
                    {"LeftTopX": 10, "LeftTopY": 20, "RightBtmX": 110, "RightBtmY": 220}
                ],
            },
            {
                "ObjectType": 203,
                "ObjectCount": 0,
                "ObjectPostList": [
                    {"LeftTopX": 10, "LeftTopY": 20, "RightBtmX": 110, "RightBtmY": 220}
                ],
            },
        ]
    }

    candidate = select_teacher_candidate(result_item, width=300, height=300)

    assert candidate is not None
    assert candidate.labels == []
    assert candidate.needs_review is True


def test_select_teacher_candidate_prefers_confidence_then_area_then_original_index():
    result_item = {
        "ResultList": [
            {
                "ObjectType": 100,
                "ObjectCount": 3,
                "ObjectPostList": [
                    {
                        "LeftTopX": 10,
                        "LeftTopY": 10,
                        "RightBtmX": 110,
                        "RightBtmY": 210,
                        "Confidence": 0.7,
                    },
                    {
                        "LeftTopX": 120,
                        "LeftTopY": 10,
                        "RightBtmX": 320,
                        "RightBtmY": 310,
                        "Confidence": 0.9,
                    },
                    {
                        "LeftTopX": 330,
                        "LeftTopY": 10,
                        "RightBtmX": 530,
                        "RightBtmY": 310,
                        "Confidence": 0.9,
                    },
                ],
            },
            {"ObjectType": 202, "ObjectCount": 1, "ObjectPostList": None},
        ]
    }

    candidate = select_teacher_candidate(result_item, width=600, height=400)

    assert candidate is not None
    assert candidate.box_xyxy == [120, 10, 320, 310]
    assert candidate.confidence == 0.9
    assert candidate.needs_review is True
    assert len(candidate.detector_metadata["subject_boxes"]) == 3


def test_select_teacher_candidate_rejects_legacy_object_type_205():
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
        select_teacher_candidate(result_item, width=300, height=300)


def test_select_teacher_candidate_rejects_legacy_205_even_when_count_is_zero():
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

    with pytest.raises(DetectContractError, match="205"):
        select_teacher_candidate(result_item, width=300, height=300)


def test_validate_detect_response_checks_root_and_single_image_status():
    payload = {
        "StatusObject": {"StatusCode": 0, "ImageIdList": ["img"]},
        "DataList": [
            {
                "StatusObject": {"StatusCode": 0, "ImageId": "img"},
                "ResultList": [],
            }
        ],
    }

    assert validate_detect_response(payload, "img") == payload["DataList"][0]

    payload["DataList"][0]["StatusObject"]["StatusCode"] = 500
    with pytest.raises(DetectResponseError, match="single-image"):
        validate_detect_response(payload, "img")


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"StatusObject": {"StatusCode": 500}, "DataList": []}, "root"),
        ({"StatusObject": {"StatusCode": 0}, "DataList": []}, "missing"),
        (
            {
                "StatusObject": {"StatusCode": 0},
                "DataList": [
                    {"StatusObject": {"StatusCode": 0, "ImageId": "img"}},
                    {"StatusObject": {"StatusCode": 0, "ImageId": "img"}},
                ],
            },
            "duplicate",
        ),
    ],
)
def test_validate_detect_response_rejects_invalid_batch_shapes(payload, message):
    with pytest.raises(DetectResponseError, match=message):
        validate_detect_response(payload, "img")


def test_validate_detect_response_rejects_non_object_json():
    with pytest.raises(DetectResponseError, match="JSON object"):
        validate_detect_response([], "img")


def test_validate_detect_response_rejects_unknown_batch_image_id():
    payload = {
        "StatusObject": {"StatusCode": 0},
        "DataList": [
            {"StatusObject": {"StatusCode": 0, "ImageId": "img"}, "ResultList": []},
            {"StatusObject": {"StatusCode": 0, "ImageId": "unknown"}, "ResultList": []},
        ],
    }

    with pytest.raises(DetectResponseError, match="unexpected"):
        validate_detect_response(payload, "img", expected_image_ids={"img"})


def test_validate_detect_response_accepts_complete_expected_batch():
    payload = {
        "StatusObject": {"StatusCode": 0},
        "DataList": [
            {"StatusObject": {"StatusCode": 0, "ImageId": "img-1"}, "ResultList": []},
            {"StatusObject": {"StatusCode": 0, "ImageId": "img-2"}, "ResultList": []},
        ],
    }

    assert validate_detect_response(
        payload, "img-1", expected_image_ids={"img-1", "img-2"}
    ) == payload["DataList"][0]


def test_validate_detect_response_rejects_mismatched_root_image_id_list():
    payload = {
        "StatusObject": {"StatusCode": 0, "ImageIdList": ["other"]},
        "DataList": [
            {"StatusObject": {"StatusCode": 0, "ImageId": "img"}, "ResultList": []},
        ],
    }

    with pytest.raises(DetectResponseError, match="root ImageIdList"):
        validate_detect_response(payload, "img", expected_image_ids={"img"})


def test_image_to_storage_path_sends_base64_data_url(tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg-bytes")

    storage_path = image_to_storage_path(image_path)

    assert storage_path.startswith("data:image/jpeg;base64,")
    assert "/tmp/" not in storage_path


def test_teacher_detect_client_disables_environment_proxy(monkeypatch, tmp_path):
    captured = {}

    class FakeResponse:
        status_code = 200
        headers = {}
        text = ""

        def json(self):
            return {
                "StatusObject": {"StatusCode": 0},
                "DataList": [
                    {
                        "StatusObject": {"StatusCode": 0, "ImageId": "img"},
                        "ResultList": [],
                    }
                ],
            }

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            return FakeResponse()

    monkeypatch.setattr("app.detector.httpx.AsyncClient", FakeAsyncClient)
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg-bytes")

    asyncio.run(TeacherDetectClient("http://127.0.0.1:8881/ImageDetect/teacher/v1.0.0").detect_image(str(image_path), "img"))

    assert captured["trust_env"] is False


def test_teacher_detect_client_retries_503_then_returns_validated_payload(monkeypatch, tmp_path):
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
        FakeResponse(
            200,
            {
                "StatusObject": {"StatusCode": 0},
                "DataList": [
                    {
                        "StatusObject": {"StatusCode": 0, "ImageId": "img"},
                        "ResultList": [],
                    }
                ],
            },
        ),
    ]

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            calls.append((url, json))
            return responses.pop(0)

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("app.detector.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("app.detector.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("app.detector.random.uniform", lambda _start, _end: 0.25)
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg-bytes")

    payload = asyncio.run(
        TeacherDetectClient("http://127.0.0.1:8871/ImageDetect/teacher/v1.0.0").detect_image(
            str(image_path), "img"
        )
    )

    assert payload["DataList"][0]["StatusObject"]["ImageId"] == "img"
    assert len(calls) == 2
    assert sleeps == [30.0]
    assert calls[0][1]["stream_type"] == "teacher"


def test_teacher_detect_client_stops_after_three_retryable_failures(monkeypatch, tmp_path):
    calls = []
    sleeps = []

    class FakeResponse:
        status_code = 500
        headers = {}
        text = "internal error"

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            calls.append(url)
            return FakeResponse()

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("app.detector.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("app.detector.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("app.detector.random.uniform", lambda _start, _end: 0.0)
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg-bytes")

    with pytest.raises(DetectResponseError, match="3 attempts"):
        asyncio.run(TeacherDetectClient("http://127.0.0.1:8871").detect_image(str(image_path), "img"))

    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]


def test_teacher_detect_client_does_not_retry_422_or_business_failure(monkeypatch, tmp_path):
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.headers = {}
            self.text = "invalid"

        def json(self):
            return self._payload

    responses = [
        FakeResponse(422),
        FakeResponse(200, {"StatusObject": {"StatusCode": 500}, "DataList": []}),
    ]

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            calls.append(url)
            return responses.pop(0)

    monkeypatch.setattr("app.detector.httpx.AsyncClient", FakeAsyncClient)
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg-bytes")
    client = TeacherDetectClient("http://127.0.0.1:8871")

    with pytest.raises(DetectResponseError, match="HTTP 422"):
        asyncio.run(client.detect_image(str(image_path), "img"))
    assert len(calls) == 1

    with pytest.raises(DetectResponseError, match="root"):
        asyncio.run(client.detect_image(str(image_path), "img"))
    assert len(calls) == 2


def test_teacher_detect_client_redacts_base64_from_http_error(monkeypatch, tmp_path):
    class FakeResponse:
        status_code = 422
        headers = {}
        text = 'invalid StoragePath=data:image/jpeg;base64,' + ('A' * 300)

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            return FakeResponse()

    monkeypatch.setattr("app.detector.httpx.AsyncClient", FakeAsyncClient)
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg-bytes")

    with pytest.raises(DetectResponseError) as exc_info:
        asyncio.run(TeacherDetectClient("http://127.0.0.1:8871").detect_image(str(image_path), "img"))

    assert "A" * 80 not in str(exc_info.value)
    assert "[base64 redacted]" in str(exc_info.value)
