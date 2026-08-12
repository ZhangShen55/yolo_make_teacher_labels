from app.detector import (
    TeacherDetectClient,
    has_teacher_presence,
    image_to_storage_path,
    select_teacher_candidate,
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


def test_select_teacher_candidate_ignores_100_and_prefers_top_edge_supported_bbox():
    result_item = {
        "ResultList": [
            {
                "ObjectType": 100,
                "ObjectCount": 1,
                "ObjectPostList": [{"LeftTopX": 0, "LeftTopY": 10, "RightBtmX": 100, "RightBtmY": 100}],
            },
            {
                "ObjectType": 202,
                "ObjectCount": 1,
                "ObjectPostList": [{"LeftTopX": 20, "LeftTopY": 700, "RightBtmX": 200, "RightBtmY": 1000}],
            },
            {
                "ObjectType": 201,
                "ObjectCount": 1,
                "ObjectPostList": [{"LeftTopX": 900, "LeftTopY": 500, "RightBtmX": 1100, "RightBtmY": 900}],
            },
            {
                "ObjectType": 205,
                "ObjectCount": 1,
                "ObjectPostList": [{"LeftTopX": 900, "LeftTopY": 500, "RightBtmX": 1100, "RightBtmY": 900}],
            },
            {
                "ObjectType": 204,
                "ObjectCount": 1,
                "ObjectPostList": [{"LeftTopX": 850, "LeftTopY": 450, "RightBtmX": 1150, "RightBtmY": 920}],
            },
        ]
    }

    candidate = select_teacher_candidate(result_item, width=1920, height=1080)

    assert candidate is not None
    assert candidate.box_xyxy == [900, 500, 1100, 900]
    assert candidate.labels == ["stand", "teach"]
    assert candidate.object_types == [201, 205]


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

        def json(self):
            return {"StatusObject": {"StatusString": "success"}}

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

    import asyncio

    asyncio.run(TeacherDetectClient("http://127.0.0.1:8881/ImageDetect/teacher/v1.0.0").detect_image(str(image_path), "img"))

    assert captured["trust_env"] is False
