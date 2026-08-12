import asyncio
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.job_manager import format_exception_message
from app.models import JobStatus, VideoEndpoint
from app.pipeline import LabelPipeline


class FakePlatform:
    def __init__(self):
        self.pages = []

    async def fetch_course_records(self, page, filters=None):
        self.pages.append(page)
        return []


def test_format_exception_message_handles_empty_exception_text():
    assert format_exception_message(asyncio.CancelledError()) == "CancelledError"
    assert format_exception_message(ValueError("bad")) == "ValueError: bad"


def test_job_status_exposes_current_progress_fields():
    status = JobStatus()

    status.set_progress(
        "extract_probe_frame",
        "正在抽取 probe_2.jpg",
        course_id=1648595,
        course_subject="机器学习",
        endpoint_index=2,
        video_url="https://example.com/video.mp4?auth_key=***",
    )

    payload = status.as_dict()
    assert payload["current_stage"] == "extract_probe_frame"
    assert payload["current_course_id"] == 1648595
    assert payload["current_course_subject"] == "机器学习"
    assert payload["current_endpoint_index"] == 2
    assert payload["current_video_url"] == "https://example.com/video.mp4?auth_key=***"
    assert payload["last_progress_message"] == "正在抽取 probe_2.jpg"
    assert payload["last_progress_at"]


def test_pipeline_run_uses_start_page_override_without_touching_config():
    pipeline = object.__new__(LabelPipeline)
    pipeline.status = JobStatus()
    pipeline.settings = type(
        "Settings",
        (),
        {"platform": type("Platform", (), {"start_page": 1, "max_pages": 0})()},
    )()
    pipeline.platform = FakePlatform()

    asyncio.run(pipeline.run(start_page=5, max_pages=1))

    assert pipeline.platform.pages == [5]
    assert pipeline.status.current_page == 5


def test_label_frame_writes_v6_subject_box_and_detector_metadata(tmp_path):
    frame_path = tmp_path / "frame.jpg"
    Image.new("RGB", (640, 360), "white").save(frame_path)
    detect_payload = {
        "StatusObject": {"StatusCode": 0, "ImageIdList": ["7_15"]},
        "DataList": [
            {
                "StatusObject": {"StatusCode": 0, "ImageId": "7_15"},
                "ResultList": [
                    {
                        "ObjectType": 100,
                        "ObjectCount": 1,
                        "ObjectPostList": [
                            {
                                "LeftTopX": 100,
                                "LeftTopY": 40,
                                "RightBtmX": 300,
                                "RightBtmY": 340,
                                "Confidence": 0.93,
                            }
                        ],
                    },
                    {
                        "ObjectType": 202,
                        "ObjectCount": 1,
                        "ObjectPostList": None,
                    },
                    {"ObjectType": 204, "ObjectCount": 1, "ObjectPostList": None},
                ],
            }
        ],
    }

    class FakeDetector:
        async def detect_image(self, image_path, image_id):
            return detect_payload

    class FakeVlm:
        def __init__(self):
            self.calls = 0

        async def ask_images(self, image_paths, prompt):
            self.calls += 1
            if self.calls == 1:
                return '{"subject":"teacher","confidence":0.99,"reason":"讲台主体"}'
            return '{"labels":["stand"],"needs_review":false,"reason":"没有明显讲授"}'

    class FakeWriter:
        def __init__(self):
            self.call = None

        def write_sample(self, source_image, box_xyxy, labels, metadata):
            self.call = {
                "source_image": source_image,
                "box_xyxy": box_xyxy,
                "labels": labels,
                "metadata": metadata,
            }
            return SimpleNamespace(batch_dir=Path("batch_000001"))

    pipeline = object.__new__(LabelPipeline)
    pipeline.status = JobStatus()
    pipeline.detector = FakeDetector()
    pipeline.vlm = FakeVlm()
    pipeline.writer = FakeWriter()
    pipeline.settings = SimpleNamespace(
        algorithm_8881=SimpleNamespace(presence_object_type=100, min_presence_count=1),
        runtime=SimpleNamespace(
            tmp_dir=tmp_path / "tmp",
            log_dir=tmp_path / "logs",
            failed_dir=tmp_path / "failed",
            log_sensitive_urls=False,
        ),
    )

    asyncio.run(
        pipeline.label_frame(
            7,
            VideoEndpoint(course_id=7, url="https://example.com/video.mp4"),
            15,
            frame_path,
        )
    )

    assert pipeline.writer.call["box_xyxy"] == [100, 40, 300, 340]
    assert pipeline.writer.call["labels"] == ["stand"]
    metadata = pipeline.writer.call["metadata"]
    assert metadata["source_detector_labels"] == ["stand", "teach"]
    assert metadata["source_detector_object_types"] == [202, 204]
    assert metadata["source_detector_metadata"]["contract_version"] == "teacher-v6"
    assert metadata["source_detector_metadata"]["root_status"] == detect_payload["StatusObject"]
    assert metadata["source_detector_metadata"]["image_status"] == detect_payload["DataList"][0]["StatusObject"]
    assert metadata["needs_review"] is True


def test_label_frame_moves_missing_subject_box_to_failed(tmp_path):
    frame_path = tmp_path / "frame.jpg"
    Image.new("RGB", (640, 360), "white").save(frame_path)

    class FakeDetector:
        async def detect_image(self, image_path, image_id):
            return {
                "StatusObject": {"StatusCode": 0},
                "DataList": [
                    {
                        "StatusObject": {"StatusCode": 0, "ImageId": image_id},
                        "ResultList": [
                            {"ObjectType": 100, "ObjectCount": 1, "ObjectPostList": None},
                            {"ObjectType": 202, "ObjectCount": 1, "ObjectPostList": None},
                        ],
                    }
                ],
            }

    pipeline = object.__new__(LabelPipeline)
    pipeline.status = JobStatus()
    pipeline.detector = FakeDetector()
    pipeline.settings = SimpleNamespace(
        algorithm_8881=SimpleNamespace(presence_object_type=100, min_presence_count=1),
        runtime=SimpleNamespace(
            tmp_dir=tmp_path / "tmp",
            log_dir=tmp_path / "logs",
            failed_dir=tmp_path / "failed",
            log_sensitive_urls=False,
        ),
    )

    asyncio.run(
        pipeline.label_frame(
            7,
            VideoEndpoint(course_id=7, url="https://example.com/video.mp4"),
            15,
            frame_path,
        )
    )

    assert not frame_path.exists()
    assert (tmp_path / "failed" / "detector_subject_box_missing" / "7" / "frame.jpg").exists()
    assert any("主体框" in error for error in pipeline.status.recent_errors)
