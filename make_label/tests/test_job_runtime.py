import asyncio

from make_label.job_manager import format_exception_message
from make_label.models import JobStatus
from make_label.pipeline import LabelPipeline


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
