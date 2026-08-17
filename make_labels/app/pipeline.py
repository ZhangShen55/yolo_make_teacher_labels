from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from PIL import Image

from .config import Settings
from .dataset_writer import DatasetWriter
from .detector import (
    DetectContractError,
    TeacherDetectClient,
    first_data_item,
    has_teacher_presence,
    select_teacher_candidate,
)
from .imaging import render_box_preview, render_labeled_preview
from .job_manager import format_exception_message
from .logging_utils import redact_url
from .models import CourseRecord, JobStatus, VideoEndpoint
from .platform_client import AuthExpiredError, PlatformClient
from .video_capture import extract_frame, ffprobe_duration, frame_offsets, should_probe_video
from .vlm_labeler import (
    ArkVlmClient,
    build_label_prompt,
    build_subject_identity_confirm_prompt,
    build_subject_identity_prompt,
    build_teacher_stream_confirm_prompt,
    build_teacher_stream_prompt,
    parse_subject_identity_response,
    parse_teacher_stream_choice,
    parse_teacher_stream_confirm_response,
    parse_vlm_label_response,
)


logger = logging.getLogger(__name__)


class LabelPipeline:
    def __init__(self, settings: Settings, status: JobStatus):
        self.settings = settings
        self.status = status
        self.run_id = uuid4().hex
        self.platform = PlatformClient(settings.platform)
        self.detector = TeacherDetectClient(
            settings.algorithm_8881.teacher_detect_url,
            timeout_seconds=settings.algorithm_8881.timeout_seconds,
        )
        self.vlm = ArkVlmClient(
            settings.vlm.api_url,
            api_key=settings.vlm.api_key,
            model=settings.vlm.model,
            timeout_seconds=settings.vlm.timeout_seconds,
        )
        self.writer = DatasetWriter(
            output_root=settings.dataset.output_root,
            batch_size=settings.dataset.batch_size,
            batch_prefix=settings.dataset.batch_prefix,
        )

    def safe_url(self, url: str) -> str:
        return redact_url(url, enabled=not self.settings.runtime.log_sensitive_urls)

    def course_tmp_dir(self, course_id: int) -> Path:
        return self.settings.runtime.tmp_dir / self.run_id / str(course_id)

    async def run(
        self,
        start_page: int | None = None,
        max_pages: int | None = None,
        course_filters: dict[str, Any] | None = None,
    ) -> None:
        try:
            page = start_page or self.settings.platform.start_page
            page_limit = max_pages if max_pages is not None else self.settings.platform.max_pages
            pages_seen = 0
            filters = course_filters or {}
            logger.info("任务开始 start_page=%s max_pages=%s filters=%s", page, page_limit or "unlimited", filters)
            while not self.status.stop_requested:
                if page_limit and pages_seen >= page_limit:
                    break
                self.status.current_page = page
                self.status.set_progress("fetch_course_page", f"正在获取课程列表第 {page} 页")
                try:
                    courses = await self.platform.fetch_course_records(page, filters=filters)
                except AuthExpiredError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self.status.add_error(f"课程列表第{page}页失败：{exc}")
                    break
                if not courses:
                    logger.info("课程列表第 %s 页为空，任务结束", page)
                    break
                logger.info("课程列表第 %s 页获取到 %s 节课", page, len(courses))
                for course in courses:
                    if self.status.stop_requested:
                        break
                    await self.process_course(course)
                    self.status.processed_courses += 1
                page += 1
                pages_seen += 1
            self.status.set_progress("idle", "任务已结束")
            logger.info("任务结束 processed=%s skipped=%s labeled=%s", self.status.processed_courses, self.status.skipped_courses, self.status.labeled_images)
        finally:
            await self.vlm.close()

    async def process_course(self, course: CourseRecord | int) -> None:
        if isinstance(course, int):
            course = CourseRecord(course_id=course)
        course_id = course.course_id
        self.status.set_progress(
            "fetch_video_endpoints",
            f"正在获取课程 {course_id} 三端视频",
            course_id=course_id,
            course_subject=course.subject_name,
            endpoint_index=None,
            video_url="",
        )
        logger.info("开始处理课程 course_id=%s subject=%s begin_time=%s", course_id, course.subject_name, course.begin_time)
        try:
            endpoints = await self.platform.fetch_video_endpoints(course_id)
            if endpoints is None:
                self.status.skipped_courses += 1
                logger.info("课程 %s 跳过：不是三端视频", course_id)
                return
            logger.info("课程 %s 获取到 %s 路视频", course_id, len(endpoints))
            teacher_endpoint = await self.select_teacher_endpoint(course_id, endpoints)
            if teacher_endpoint is None:
                self.status.skipped_courses += 1
                logger.info("课程 %s 跳过：无法确认教师端", course_id)
                return
            self.status.teacher_stream_courses += 1
            logger.info("课程 %s 确认教师端 url=%s", course_id, self.safe_url(teacher_endpoint.url))
            await self.capture_and_label_teacher_stream(course_id, teacher_endpoint)
        except Exception as exc:  # noqa: BLE001
            self.status.add_error(f"课程{course_id}处理失败：{format_exception_message(exc)}")
            logger.exception("课程 %s 处理失败", course_id)

    async def select_teacher_endpoint(self, course_id: int, endpoints: list[VideoEndpoint]) -> VideoEndpoint | None:
        probe_paths = []
        probe_second = self.settings.video.teacher_select_probe_second
        course_tmp = self.course_tmp_dir(course_id)
        timeout_seconds = self.settings.video.command_timeout_seconds
        for index, endpoint in enumerate(endpoints, start=1):
            safe_url = self.safe_url(endpoint.url)
            self.status.set_progress(
                "probe_video_duration",
                f"正在探测课程 {course_id} 第 {index} 路视频时长",
                course_id=course_id,
                endpoint_index=index,
                video_url=safe_url,
            )
            logger.info("课程 %s 第 %s 路探测视频时长 url=%s", course_id, index, safe_url)
            duration = await asyncio.to_thread(ffprobe_duration, endpoint.url, timeout_seconds=timeout_seconds)
            if not should_probe_video(duration, probe_second):
                logger.info("课程 %s 第 %s 路视频不足 %s 秒，跳过课程，duration=%.2f", course_id, index, probe_second, duration)
                return None
            frame_path = course_tmp / f"probe_{index}.jpg"
            self.status.set_progress(
                "extract_probe_frame",
                f"正在抽取课程 {course_id} 第 {index} 路 probe 帧",
                course_id=course_id,
                endpoint_index=index,
                video_url=safe_url,
            )
            logger.info("课程 %s 第 %s 路抽取 probe offset=%s out=%s", course_id, index, probe_second, frame_path)
            await asyncio.to_thread(extract_frame, endpoint.url, probe_second, frame_path, timeout_seconds=timeout_seconds)
            probe_paths.append(frame_path)

        self.status.set_progress("vlm_teacher_stream_choice", f"正在用 VLM 判断课程 {course_id} 教师端", course_id=course_id)
        response_text = await self.vlm.ask_images(probe_paths, build_teacher_stream_prompt(len(probe_paths)))
        choice = parse_teacher_stream_choice(response_text, candidate_count=len(probe_paths))
        self.write_raw(course_id, "teacher_stream_choice.json", {"response": response_text, "choice": choice.__dict__})
        logger.info("课程 %s 教师端首轮判断 index=%s confidence=%.3f reason=%s", course_id, choice.teacher_index, choice.confidence, choice.reason)
        if choice.teacher_index is None:
            return None
        selected_probe = probe_paths[choice.teacher_index - 1]
        self.status.set_progress("vlm_teacher_stream_confirm", f"正在二次确认课程 {course_id} 教师端", course_id=course_id, endpoint_index=choice.teacher_index)
        confirm_text = await self.vlm.ask_images([selected_probe], build_teacher_stream_confirm_prompt())
        confirm = parse_teacher_stream_confirm_response(confirm_text)
        self.write_raw(course_id, "teacher_stream_confirm.json", {"response": confirm_text, "confirm": confirm.__dict__})
        logger.info("课程 %s 教师端二次确认 type=%s confidence=%.3f reason=%s", course_id, confirm.stream_type, confirm.confidence, confirm.reason)
        if confirm.stream_type != "teacher_stream":
            return None
        return endpoints[choice.teacher_index - 1]

    async def capture_and_label_teacher_stream(self, course_id: int, endpoint: VideoEndpoint) -> None:
        timeout_seconds = self.settings.video.command_timeout_seconds
        duration = await asyncio.to_thread(ffprobe_duration, endpoint.url, timeout_seconds=timeout_seconds)
        offsets = frame_offsets(
            duration,
            self.settings.video.capture_start_second,
            self.settings.video.capture_interval_second,
            self.settings.video.max_frames_per_course,
            jitter_seconds=self.settings.video.capture_jitter_seconds,
        )
        if not offsets:
            return
        logger.info("课程 %s 教师端抽帧 offsets=%s", course_id, offsets)

        queue: asyncio.Queue[tuple[int, Path] | None] = asyncio.Queue()
        worker_count = max(1, min(self.settings.algorithm_8881.detect_workers, len(offsets)))

        async def producer() -> None:
            for offset in offsets:
                if self.status.stop_requested:
                    break
                frame_path = self.course_tmp_dir(course_id) / f"frame_{offset}.jpg"
                self.status.set_progress(
                    "extract_frame",
                    f"正在抽取课程 {course_id} offset={offset}",
                    course_id=course_id,
                    video_url=self.safe_url(endpoint.url),
                )
                logger.info("课程 %s 抽取正式帧 offset=%s out=%s", course_id, offset, frame_path)
                await asyncio.to_thread(extract_frame, endpoint.url, offset, frame_path, timeout_seconds=timeout_seconds)
                self.status.captured_images += 1
                await queue.put((offset, frame_path))
            for _ in range(worker_count):
                await queue.put(None)

        async def worker() -> None:
            while True:
                item = await queue.get()
                try:
                    if item is None:
                        return
                    offset, frame_path = item
                    await self.label_frame(course_id, endpoint, offset, frame_path)
                finally:
                    queue.task_done()

        await asyncio.gather(producer(), *(worker() for _ in range(worker_count)))

    async def label_frame(self, course_id: int, endpoint: VideoEndpoint, offset_second: int, frame_path: Path) -> None:
        image_id = f"{course_id}_{offset_second}"
        try:
            frame_available = frame_path.is_file() and frame_path.stat().st_size > 0
        except OSError:
            frame_available = False
        if not frame_available:
            self.status.filtered_images += 1
            self.status.add_error(f"图片 {image_id} 抽帧文件不存在或为空：{frame_path}")
            logger.warning("图片 %s 过滤：抽帧文件不存在或为空 path=%s", image_id, frame_path)
            return
        self.status.set_progress("teacher_detect", f"正在调用教师行为检测 {image_id}", course_id=course_id, video_url=self.safe_url(endpoint.url))
        try:
            detect_payload = await self.detector.detect_image(str(frame_path), image_id=image_id)
        except FileNotFoundError:
            self.status.filtered_images += 1
            self.status.add_error(f"图片 {image_id} 抽帧文件在检测读取前丢失：{frame_path}")
            logger.warning("图片 %s 过滤：抽帧文件在检测读取前丢失 path=%s", image_id, frame_path)
            return
        self.write_raw(course_id, f"{image_id}_detect.json", detect_payload)
        result_item = first_data_item(detect_payload, image_id=image_id)
        if result_item is None:
            self.status.filtered_images += 1
            logger.info("图片 %s 过滤：教师行为检测无结果", image_id)
            frame_path.unlink(missing_ok=True)
            return
        if not has_teacher_presence(
            result_item,
            object_type=self.settings.algorithm_8881.presence_object_type,
            min_count=self.settings.algorithm_8881.min_presence_count,
        ):
            self.status.filtered_images += 1
            logger.info("图片 %s 过滤：ObjectType=%s 人数不足", image_id, self.settings.algorithm_8881.presence_object_type)
            frame_path.unlink(missing_ok=True)
            return

        with Image.open(frame_path) as image:
            width, height = image.size
        try:
            candidate = select_teacher_candidate(result_item, width=width, height=height)
        except DetectContractError as exc:
            self.status.filtered_images += 1
            self.status.add_error(f"图片 {image_id} 检测契约不匹配：{exc}")
            self.discard_frame(frame_path, course_id, "detector_contract_error")
            return
        if candidate is None:
            self.status.filtered_images += 1
            self.status.add_error(f"图片 {image_id} 检测到老师数量但缺少有效主体框")
            self.discard_frame(frame_path, course_id, "detector_subject_box_missing")
            return

        subject_preview_path = self.course_tmp_dir(course_id) / f"{image_id}_subject.jpg"
        render_box_preview(frame_path, subject_preview_path, candidate.box_xyxy)
        self.status.set_progress("vlm_subject_identity", f"正在判断红框主体身份 {image_id}", course_id=course_id)
        subject_text = await self.vlm.ask_images([subject_preview_path], build_subject_identity_prompt())
        subject = parse_subject_identity_response(subject_text)
        self.write_raw(course_id, f"{image_id}_subject_round1.json", {"response": subject_text, "subject": subject.__dict__})
        logger.info("图片 %s 主体判断 round1 subject=%s confidence=%.3f reason=%s", image_id, subject.subject, subject.confidence, subject.reason)
        if subject.subject == "unknown":
            self.discard_frame(frame_path, course_id, "subject_unknown")
            self.status.filtered_images += 1
            logger.info("图片 %s 过滤：主体 unknown", image_id)
            return
        if subject.subject == "student":
            self.status.set_progress("vlm_subject_confirm", f"正在二次判断红框主体身份 {image_id}", course_id=course_id)
            confirm_text = await self.vlm.ask_images([subject_preview_path], build_subject_identity_confirm_prompt())
            confirm = parse_subject_identity_response(confirm_text)
            self.write_raw(course_id, f"{image_id}_subject_round2.json", {"response": confirm_text, "subject": confirm.__dict__})
            logger.info("图片 %s 主体判断 round2 subject=%s confidence=%.3f reason=%s", image_id, confirm.subject, confirm.confidence, confirm.reason)
            if confirm.subject == "unknown":
                self.discard_frame(frame_path, course_id, "subject_unknown")
                self.status.filtered_images += 1
                logger.info("图片 %s 过滤：二次主体 unknown", image_id)
                return
            if confirm.subject == "student":
                self.discard_frame(frame_path, course_id, "subject_student")
                self.status.filtered_images += 1
                logger.info("图片 %s 过滤：主体 student", image_id)
                return

        preview_path = self.course_tmp_dir(course_id) / f"{image_id}_preview.jpg"
        render_labeled_preview(frame_path, preview_path, candidate.box_xyxy, candidate.labels)
        self.status.set_progress("vlm_label", f"正在 VLM 标注 {image_id}", course_id=course_id)
        vlm_text = await self.vlm.ask_images([preview_path], build_label_prompt())
        vlm_result = parse_vlm_label_response(vlm_text, fallback_labels=candidate.labels)
        self.write_raw(course_id, f"{image_id}_vlm.json", {"response": vlm_text, "parsed": vlm_result.__dict__})
        labels_conflict = set(candidate.labels) != set(vlm_result.labels)
        needs_review = candidate.needs_review or vlm_result.needs_review or labels_conflict
        detector_metadata = {
            **candidate.detector_metadata,
            "root_status": detect_payload.get("StatusObject"),
            "image_status": result_item.get("StatusObject"),
        }
        write_result = self.writer.write_sample(
            frame_path,
            candidate.box_xyxy,
            vlm_result.labels,
            {
                "course_id": course_id,
                "video_url": endpoint.url,
                "offset_second": offset_second,
                "source_detector_labels": candidate.labels,
                "source_detector_object_types": candidate.object_types,
                "source_detector_confidence": candidate.confidence,
                "source_detector_metadata": detector_metadata,
                "source_8881_labels": candidate.labels,
                "source_8881_object_types": candidate.object_types,
                "vlm_reason": vlm_result.reason,
                "needs_review": needs_review,
            },
        )
        self.status.current_batch = write_result.batch_dir.name
        self.status.labeled_images += 1
        logger.info("图片 %s 写入成功 labels=%s batch=%s", image_id, vlm_result.labels, write_result.batch_dir.name)

    def write_raw(self, course_id: int, name: str, payload: dict[str, Any]) -> None:
        raw_dir = self.settings.runtime.log_dir / "raw" / str(course_id)
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / name).write_text(json.dumps(payload, ensure_ascii=False, default=str, indent=2), encoding="utf-8")

    def discard_frame(self, frame_path: Path, course_id: int, reason: str) -> None:
        failed_dir = self.settings.runtime.failed_dir / reason / str(course_id)
        failed_dir.mkdir(parents=True, exist_ok=True)
        destination = failed_dir / frame_path.name
        if frame_path.exists():
            shutil.move(str(frame_path), str(destination))
