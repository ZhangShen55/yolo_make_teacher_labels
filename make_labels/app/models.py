from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CourseRecord:
    course_id: int
    subject_name: str = ""
    begin_time: str = ""


@dataclass(frozen=True)
class VideoEndpoint:
    course_id: int
    url: str
    view_num: int | None = None


@dataclass(frozen=True)
class OrganizationItem:
    id: int
    orga_name: str
    orga_level: int | None = None
    parent_id: int | None = None
    path: str = ""


@dataclass(frozen=True)
class TeacherCandidate:
    box_xyxy: list[int]
    labels: list[str]
    object_types: list[int]
    confidence: float | None = None
    needs_review: bool = False
    detector_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TeacherStreamChoice:
    teacher_index: int | None
    confidence: float
    reason: str


@dataclass(frozen=True)
class TeacherStreamConfirmResult:
    stream_type: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class SubjectIdentityResult:
    subject: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class VlmLabelResult:
    labels: list[str]
    needs_review: bool = False
    reason: str = ""
    raw_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SampleWriteResult:
    image_id: str
    image_path: Path
    label_path: Path
    annotation_path: Path
    batch_dir: Path


@dataclass
class JobStatus:
    running: bool = False
    stop_requested: bool = False
    current_page: int = 0
    processed_courses: int = 0
    skipped_courses: int = 0
    teacher_stream_courses: int = 0
    captured_images: int = 0
    filtered_images: int = 0
    labeled_images: int = 0
    current_batch: str = ""
    requested_start_page: int | None = None
    requested_max_pages: int | None = None
    requested_cour_begin_time: str | None = None
    requested_cour_end_time: str | None = None
    requested_orga_ids: list[int] | None = None
    current_course_id: int | None = None
    current_course_subject: str = ""
    current_stage: str = ""
    current_endpoint_index: int | None = None
    current_video_url: str = ""
    last_progress_at: str = ""
    last_progress_message: str = ""
    recent_errors: list[str] = field(default_factory=list)

    def set_progress(
        self,
        stage: str,
        message: str,
        *,
        course_id: int | None = None,
        course_subject: str | None = None,
        endpoint_index: int | None = None,
        video_url: str | None = None,
    ) -> None:
        self.current_stage = stage
        self.last_progress_message = message
        self.last_progress_at = datetime.now().isoformat(timespec="seconds")
        if course_id is not None:
            self.current_course_id = course_id
        if course_subject is not None:
            self.current_course_subject = course_subject
        if endpoint_index is not None:
            self.current_endpoint_index = endpoint_index
        if video_url is not None:
            self.current_video_url = video_url

    def as_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "stop_requested": self.stop_requested,
            "current_page": self.current_page,
            "processed_courses": self.processed_courses,
            "skipped_courses": self.skipped_courses,
            "teacher_stream_courses": self.teacher_stream_courses,
            "captured_images": self.captured_images,
            "filtered_images": self.filtered_images,
            "labeled_images": self.labeled_images,
            "current_batch": self.current_batch,
            "requested_start_page": self.requested_start_page,
            "requested_max_pages": self.requested_max_pages,
            "requested_cour_begin_time": self.requested_cour_begin_time,
            "requested_cour_end_time": self.requested_cour_end_time,
            "requested_orga_ids": self.requested_orga_ids,
            "current_course_id": self.current_course_id,
            "current_course_subject": self.current_course_subject,
            "current_stage": self.current_stage,
            "current_endpoint_index": self.current_endpoint_index,
            "current_video_url": self.current_video_url,
            "last_progress_at": self.last_progress_at,
            "last_progress_message": self.last_progress_message,
            "recent_errors": self.recent_errors[-20:],
        }

    def add_error(self, message: str) -> None:
        self.recent_errors.append(message)
        if len(self.recent_errors) > 200:
            self.recent_errors = self.recent_errors[-200:]
