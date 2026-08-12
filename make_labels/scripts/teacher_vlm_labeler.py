#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import random
import re
import shutil
import time
from typing import Any

import requests
from PIL import Image

from app.detector import (
    DetectContractError,
    DetectResponseError,
    sanitized_response_body,
    select_teacher_candidate,
    validate_detect_response,
)
from app.imaging import build_display_text, render_labeled_preview


LABEL_TO_CLASS_ID = {"sit": 0, "stand": 1, "bbwriting": 2, "teach": 3}
LABEL_ORDER = ["sit", "stand", "bbwriting", "teach"]


def normalize_xyxy_to_yolo(box_xyxy: list[int], width: int, height: int) -> list[float]:
    x1, y1, x2, y2 = box_xyxy
    return [
        round(((x1 + x2) / 2) / width, 6),
        round(((y1 + y2) / 2) / height, 6),
        round((x2 - x1) / width, 6),
        round((y2 - y1) / height, 6),
    ]


def strip_json_fence(text: str) -> str:
    stripped = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    object_match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if object_match:
        return object_match.group(0)
    return stripped


def ordered_labels(labels: list[str]) -> list[str]:
    seen = set()
    valid = []
    for label in labels:
        if label in LABEL_TO_CLASS_ID and label not in seen:
            seen.add(label)
            valid.append(label)
    return [label for label in LABEL_ORDER if label in valid]


def fallback_pose_from_source(source_api_labels: list[str]) -> str:
    if "sit" in source_api_labels or "坐着" in source_api_labels:
        return "sit"
    if "stand" in source_api_labels or "站立" in source_api_labels:
        return "stand"
    return "stand"


def parse_vlm_labels(response_text: str, source_api_labels: list[str]) -> dict[str, Any]:
    needs_review = False
    reason = ""
    try:
        payload = json.loads(strip_json_fence(response_text))
    except json.JSONDecodeError:
        payload = {}
        needs_review = True
        reason = response_text.strip()[:300]

    labels: list[str]
    if isinstance(payload.get("labels"), list):
        labels = [str(item).strip() for item in payload["labels"]]
    else:
        labels = [
            label
            for label in LABEL_ORDER
            if payload.get(label) is True or str(payload.get(label)).lower() == "true"
        ]

    labels = ordered_labels(labels)
    if isinstance(payload.get("needs_review"), bool):
        needs_review = needs_review or payload["needs_review"]
    if isinstance(payload.get("reason"), str):
        reason = payload["reason"]

    has_sit = "sit" in labels
    has_stand = "stand" in labels
    if has_sit and has_stand:
        labels = [label for label in labels if label not in {"sit", "stand"}]
        labels.insert(0, fallback_pose_from_source(source_api_labels))
        needs_review = True
    elif not has_sit and not has_stand:
        labels.insert(0, fallback_pose_from_source(source_api_labels))
        needs_review = True

    return {
        "labels": ordered_labels(labels),
        "needs_review": needs_review,
        "reason": reason,
        "raw_json": payload,
    }


def image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def post_json_with_retries(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 90) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if response.status_code == 200:
                return response.json()
            last_error = RuntimeError(
                f"HTTP {response.status_code}: {sanitized_response_body(response.text)}"
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"POST failed after retries: {last_error}")


def post_detect_json_with_retries(
    url: str,
    payload: dict[str, Any],
    timeout: int = 90,
) -> dict[str, Any]:
    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt == 2:
                raise DetectResponseError(f"teacher detect failed after 3 attempts: {exc}") from exc
            time.sleep(float(2**attempt) + random.uniform(0.0, 0.5))
            continue

        if 200 <= response.status_code < 300:
            try:
                return response.json()
            except (TypeError, ValueError) as exc:
                raise DetectResponseError("teacher detect returned invalid JSON") from exc

        body = sanitized_response_body(response.text)
        if response.status_code not in {429, 500, 503}:
            raise DetectResponseError(
                f"teacher detect failed: HTTP {response.status_code}: {body}"
            )
        if attempt == 2:
            raise DetectResponseError(
                f"teacher detect failed after 3 attempts: HTTP {response.status_code}: {body}"
            )

        retry_after = response.headers.get("Retry-After")
        try:
            delay = max(0.0, min(30.0, float(retry_after))) if retry_after is not None else None
        except ValueError:
            delay = None
        time.sleep(delay if delay is not None else float(2**attempt) + random.uniform(0.0, 0.5))

    raise DetectResponseError("teacher detect failed after 3 attempts")


def detect_teacher_batch(paths: list[Path], detect_url: str) -> dict[Path, dict[str, Any]]:
    image_ids = {
        path: f"offline-{index:04d}-{path.name}"
        for index, path in enumerate(paths)
    }
    payload = {
        "batch_id": f"offline-{paths[0].stem}" if paths else "offline-empty",
        "stream_type": "teacher",
        "ReturnHeadPose": False,
        "ImageList": [
            {"StoragePath": image_to_data_url(path), "ImageId": image_ids[path]}
            for path in paths
        ]
    }
    data = post_detect_json_with_retries(detect_url, payload, timeout=90)
    result_by_id = {}
    expected_image_ids = set(image_ids.values())
    for path in paths:
        result_item = validate_detect_response(
            data,
            image_ids[path],
            expected_image_ids=expected_image_ids,
        )
        result_by_id[path] = {
            "result_item": result_item,
            "root_status": data.get("StatusObject"),
            "image_status": result_item.get("StatusObject"),
        }
    return result_by_id


def build_output_names(paths: list[Path]) -> dict[Path, Path]:
    stem_counts: dict[str, int] = {}
    for path in paths:
        stem_counts[path.stem] = stem_counts.get(path.stem, 0) + 1
    return {
        path: (
            Path(f"{path.stem}-{path.suffix.lower().lstrip('.')}{path.suffix.lower()}")
            if stem_counts[path.stem] > 1
            else Path(path.name)
        )
        for path in paths
    }


def select_candidate_for_offline(
    result_item: dict[str, Any],
    width: int,
    height: int,
) -> tuple[Any | None, str]:
    try:
        return select_teacher_candidate(result_item, width=width, height=height), ""
    except DetectContractError as exc:
        return None, str(exc)


def build_vlm_prompt(source_api_labels: list[str]) -> str:
    source = build_display_text(source_api_labels) or "无"
    return f"""
你是课堂图片数据标注员。请只判断红色框内的老师主体，不要判断其他学生或背景。

目标是输出 4 个英文标签中的一个或多个：
- sit：坐
- stand：站
- bbwriting：写板书
- teach：讲授演示

红框上方的中文初检候选标签是：{source}。候选标签可能错误或遗漏，必须以图片视觉内容为准进行保留、删除或补充。

标注规则：
1. sit 与 stand 互斥，必须且只能选择其中一个。
2. bbwriting 只在老师明显正在黑板/白板/屏幕上写板书时选择。
3. teach 表示老师明显在讲授、讲解、演示或面向课堂表达。普通肢体动作但不是板书时，如果像是在课堂讲解，只标 teach，不标 bbwriting。
4. bbwriting 与 teach 可以同时出现，但只有在老师明显一边写板书一边讲授/讲解时才同时标注。
5. 如果老师明显只是在板书，没有明显讲授/演示，只标 bbwriting，不标 teach。
6. 如果不确定，请选择最可能标签，并把 needs_review 设为 true。

只输出合法 JSON，不要输出 Markdown，不要解释：
{{"labels":["stand","teach"],"needs_review":false,"reason":"一句很短的中文理由"}}
""".strip()


def extract_responses_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks: list[str] = []
    for output_item in payload.get("output") or []:
        for content in output_item.get("content") or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    if chunks:
        return "\n".join(chunks)
    return json.dumps(payload, ensure_ascii=False)


def call_vlm(
    preview_path: Path,
    source_api_labels: list[str],
    ark_url: str,
    model: str,
    api_key: str,
) -> tuple[dict[str, Any], str]:
    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_image", "image_url": image_to_data_url(preview_path)},
                    {"type": "input_text", "text": build_vlm_prompt(source_api_labels)},
                ],
            }
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response_json = post_json_with_retries(ark_url, payload, headers=headers, timeout=120)
    return response_json, extract_responses_text(response_json)


def write_yolo_labels(path: Path, labels: list[str], normalized_box: list[float] | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if normalized_box is None:
        path.write_text("", encoding="utf-8")
        return
    lines = [
        f"{LABEL_TO_CLASS_ID[label]} " + " ".join(f"{value:.6f}" for value in normalized_box)
        for label in labels
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def process_images(args: argparse.Namespace) -> None:
    src_dir = Path(args.src_dir)
    dataset_dir = Path(args.dataset_dir)
    review_dir = Path(args.review_dir)
    preview_dir = Path(args.preview_dir)
    images_dir = dataset_dir / "images"
    yolo_dir = dataset_dir / "labels"
    raw_vlm_dir = dataset_dir / "raw_vlm"
    raw_detector_dir = dataset_dir / "raw_detector"
    annotations_path = dataset_dir / "annotations.jsonl"
    classes_path = dataset_dir / "classes.txt"

    if args.clear_output:
        for directory in [dataset_dir, review_dir, preview_dir]:
            if directory.exists():
                shutil.rmtree(directory)

    for directory in [
        dataset_dir,
        review_dir,
        preview_dir,
        images_dir,
        yolo_dir,
        raw_vlm_dir,
        raw_detector_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
    classes_path.write_text("\n".join(LABEL_ORDER) + "\n", encoding="utf-8")

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing API key env var: {args.api_key_env}")

    image_paths = sorted(
        path for path in src_dir.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    )
    if args.limit:
        image_paths = image_paths[: args.limit]
    output_names = build_output_names(image_paths)

    annotations: list[dict[str, Any]] = []
    start = time.time()
    processed = 0
    needs_review_count = 0
    label_counts = {label: 0 for label in LABEL_ORDER}

    for index in range(0, len(image_paths), args.detect_batch_size):
        batch = image_paths[index:index + args.detect_batch_size]
        results = detect_teacher_batch(batch, args.detect_url)

        for image_path in batch:
            output_name = output_names[image_path]
            with Image.open(image_path) as image:
                width, height = image.size
            dataset_image_path = images_dir / output_name
            shutil.copy2(image_path, dataset_image_path)

            detect_result = results.get(image_path) or {}
            result_item = detect_result.get("result_item")
            candidate, detector_error = select_candidate_for_offline(
                result_item or {}, width=width, height=height
            )
            box_xyxy = candidate.box_xyxy if candidate else None
            source_api_labels = candidate.labels if candidate else []
            source_api_object_types = candidate.object_types if candidate else []
            normalized_box = normalize_xyxy_to_yolo(box_xyxy, width, height) if box_xyxy else None

            preview_path = preview_dir / output_name
            review_path = review_dir / output_name

            if box_xyxy is None:
                reason = (
                    f"检测契约不匹配：{detector_error}"
                    if detector_error
                    else "未检测到候选老师框"
                )
                parsed = {"labels": [], "needs_review": True, "reason": reason, "raw_json": {}}
                raw_response = {}
                raw_text = ""
            else:
                render_labeled_preview(image_path, preview_path, box_xyxy, source_api_labels)
                raw_response, raw_text = call_vlm(preview_path, source_api_labels, args.ark_url, args.model, api_key)
                parsed = parse_vlm_labels(raw_text, source_api_labels)
                parsed["needs_review"] = (
                    parsed["needs_review"]
                    or candidate.needs_review
                    or set(source_api_labels) != set(parsed["labels"])
                )

            raw_detector_path = raw_detector_dir / f"{output_name.stem}.json"
            raw_detector_path.write_text(
                json.dumps(
                    {
                        "root_status": detect_result.get("root_status"),
                        "image_status": detect_result.get("image_status"),
                        "result_item": result_item,
                        "contract_error": detector_error or None,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            raw_vlm_path = raw_vlm_dir / f"{output_name.stem}.json"
            raw_vlm_path.write_text(
                json.dumps(
                    {"response": raw_response, "text": raw_text, "parsed": parsed},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            labels = parsed["labels"]
            for label in labels:
                label_counts[label] += 1
            needs_review_count += 1 if parsed["needs_review"] else 0
            write_yolo_labels(yolo_dir / f"{output_name.stem}.txt", labels, normalized_box)
            if box_xyxy is not None:
                render_labeled_preview(image_path, review_path, box_xyxy, labels)
            else:
                shutil.copy2(image_path, review_path)

            annotation = {
                "image": output_name.name,
                "source_image": str(image_path),
                "image_path": str(dataset_image_path),
                "review_image_path": str(review_path),
                "preview_image_path": str(preview_path),
                "width": width,
                "height": height,
                "box_xyxy": box_xyxy,
                "box_norm_xywh": normalized_box,
                "labels": labels,
                "source_api_labels": source_api_labels,
                "source_api_object_types": source_api_object_types,
                "source_detector_confidence": candidate.confidence if candidate else None,
                "source_detector_metadata": {
                    **(candidate.detector_metadata if candidate else {}),
                    "root_status": detect_result.get("root_status"),
                    "image_status": detect_result.get("image_status"),
                },
                "needs_review": parsed["needs_review"],
                "reason": parsed["reason"],
                "raw_vlm_path": str(raw_vlm_path),
                "raw_detector_path": str(raw_detector_path),
            }
            annotations.append(annotation)
            processed += 1

        annotations_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in annotations) + "\n",
            encoding="utf-8",
        )
        print(
            f"processed {processed}/{len(image_paths)} images, needs_review={needs_review_count}, labels={label_counts}",
            flush=True,
        )

    elapsed = time.time() - start
    print(
        json.dumps(
            {
                "processed": processed,
                "needs_review": needs_review_count,
                "label_counts": label_counts,
                "dataset_dir": str(dataset_dir),
                "review_dir": str(review_dir),
                "preview_dir": str(preview_dir),
                "elapsed_seconds": round(elapsed, 2),
            },
            ensure_ascii=False,
        )
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Label teacher behavior images with ImageDetect boxes and Doubao VLM.")
    parser.add_argument("--src-dir", default="测试数据/teacher")
    parser.add_argument("--dataset-dir", default="测试数据/teacher-vlm-labels")
    parser.add_argument("--review-dir", default="测试数据/teacher-out")
    parser.add_argument("--preview-dir", default="测试数据/teacher-vlm-preview")
    parser.add_argument("--detect-url", default="http://127.0.0.1:8871/ImageDetect/teacher/v1.0.0")
    parser.add_argument("--ark-url", default="https://ark.cn-beijing.volces.com/api/v3/responses")
    parser.add_argument("--model", default="doubao-seed-2-0-mini-260428")
    parser.add_argument("--api-key-env", default="ARK_API_KEY")
    parser.add_argument("--detect-batch-size", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--clear-output", action="store_true")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    process_images(args)


if __name__ == "__main__":
    main()
