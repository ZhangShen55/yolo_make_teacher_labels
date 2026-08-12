#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont


LABEL_TO_CLASS_ID = {"sit": 0, "stand": 1, "bbwriting": 2, "teach": 3}
LABEL_ORDER = ["sit", "stand", "bbwriting", "teach"]
SUPPORTED_API_LABELS = {
    201: "站立",
    202: "坐着",
    203: "板书",
    205: "授课",
}
API_LABEL_TO_VLM_LABEL = {
    "站立": "stand",
    "坐着": "sit",
    "板书": "bbwriting",
    "授课": "teach",
}
DISPLAY_LABELS = {
    "sit": "sit 坐",
    "stand": "stand 站",
    "bbwriting": "bbwriting 写板书",
    "teach": "teach 讲授演示",
}
FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]
RED = (255, 0, 0)
BLUE = (0, 0, 255)


@dataclass
class TeacherCandidate:
    box_xyxy: list[int]
    source_api_labels: list[str]
    source_api_object_types: list[int]


def normalize_box(raw_box: dict[str, Any], width: int, height: int) -> list[int] | None:
    x1 = int(round(raw_box.get("LeftTopX", 0)))
    y1 = int(round(raw_box.get("LeftTopY", 0)))
    x2 = int(round(raw_box.get("RightBtmX", 0)))
    y2 = int(round(raw_box.get("RightBtmY", 0)))
    x1, x2 = sorted((max(0, min(width - 1, x1)), max(0, min(width - 1, x2))))
    y1, y2 = sorted((max(0, min(height - 1, y1)), max(0, min(height - 1, y2))))
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def box_area(box: list[int]) -> int:
    x1, y1, x2, y2 = box
    return (x2 - x1) * (y2 - y1)


def box_iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    return inter / (box_area(a) + box_area(b) - inter)


def merge_candidate_boxes(raw_candidates: list[tuple[list[int], int]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for box, object_type in raw_candidates:
        match = None
        for group in groups:
            if box_iou(box, group["box"]) >= 0.85:
                match = group
                break
        if match is None:
            groups.append({"box": box, "boxes": [box], "object_types": {object_type}})
        else:
            match["boxes"].append(box)
            match["object_types"].add(object_type)
            match["box"] = max(match["boxes"], key=box_area)
    return groups


def select_teacher_candidate(
    result_item: dict[str, Any], width: int, height: int
) -> TeacherCandidate | None:
    raw_candidates: list[tuple[list[int], int]] = []
    for item in result_item.get("ResultList") or []:
        object_type = item.get("ObjectType")
        if object_type not in SUPPORTED_API_LABELS:
            continue
        for raw_box in item.get("ObjectPostList") or []:
            box = normalize_box(raw_box, width, height)
            if box is not None:
                raw_candidates.append((box, object_type))

    groups = merge_candidate_boxes(raw_candidates)
    if not groups:
        return None

    selected = min(groups, key=lambda group: (group["box"][1], -box_area(group["box"])))
    object_types = sorted(selected["object_types"])
    return TeacherCandidate(
        box_xyxy=selected["box"],
        source_api_labels=[SUPPORTED_API_LABELS[t] for t in object_types],
        source_api_object_types=object_types,
    )


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
    if "坐着" in source_api_labels:
        return "sit"
    if "站立" in source_api_labels:
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


def find_font_path() -> str:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return path
    raise RuntimeError("No Chinese-capable font found")


def text_size(draw: ImageDraw.ImageDraw, lines: list[str], font: ImageFont.FreeTypeFont, spacing: int) -> tuple[int, int]:
    stroke = max(1, font.size // 18)
    widths = []
    heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke)
        widths.append(bbox[2] - bbox[0])
        heights.append(bbox[3] - bbox[1])
    return (max(widths) if widths else 0, sum(heights) + spacing * max(0, len(lines) - 1))


def fit_font(
    draw: ImageDraw.ImageDraw,
    font_path: str,
    lines: list[str],
    target_width: float,
    max_height: float,
) -> ImageFont.FreeTypeFont:
    lo, hi = 4, 160
    best = 4
    while lo <= hi:
        mid = (lo + hi) // 2
        font = ImageFont.truetype(font_path, size=mid)
        spacing = max(1, mid // 8)
        width, height = text_size(draw, lines, font, spacing)
        if width <= target_width and height <= max_height:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return ImageFont.truetype(font_path, size=best)


def draw_box_only(src_path: Path, out_path: Path, box_xyxy: list[int] | None) -> None:
    image = Image.open(src_path).convert("RGB")
    if box_xyxy is not None:
        draw = ImageDraw.Draw(image)
        width, height = image.size
        line_width = max(4, min(width, height) // 180)
        draw.rectangle(box_xyxy, outline=RED, width=line_width)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, quality=95)


def draw_review_image(
    src_path: Path,
    out_path: Path,
    box_xyxy: list[int] | None,
    labels: list[str],
    font_path: str,
) -> None:
    image = Image.open(src_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    if box_xyxy is not None:
        x1, y1, x2, y2 = box_xyxy
        box_width = x2 - x1
        box_height = y2 - y1
        line_width = max(4, min(width, height) // 180)
        draw.rectangle(box_xyxy, outline=RED, width=line_width)
        lines = [DISPLAY_LABELS[label] for label in labels]
        if lines:
            font = fit_font(draw, font_path, lines, target_width=box_width / 2, max_height=box_height * 0.8)
            spacing = max(1, font.size // 8)
            label_width, label_height = text_size(draw, lines, font, spacing)
            tx = (x1 + x2) / 2 - label_width / 2
            ty = (y1 + y2) / 2 - label_height / 2
            stroke = max(1, font.size // 18)
            draw.multiline_text(
                (tx, ty),
                "\n".join(lines),
                font=font,
                fill=BLUE,
                spacing=spacing,
                align="center",
                stroke_width=stroke,
                stroke_fill=BLUE,
            )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, quality=95)


def post_json_with_retries(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 90) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if response.status_code == 200:
                return response.json()
            last_error = RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"POST failed after retries: {last_error}")


def detect_teacher_batch(paths: list[Path], detect_url: str) -> dict[str, dict[str, Any]]:
    payload = {
        "ImageList": [
            {"StoragePath": image_to_data_url(path), "ImageId": path.stem}
            for path in paths
        ]
    }
    data = post_json_with_retries(detect_url, payload, timeout=90)
    status = data.get("StatusObject") or {}
    if status.get("StatusCode") != 0:
        raise RuntimeError(f"ImageDetect failed: {json.dumps(status, ensure_ascii=False)}")
    result_by_id = {}
    for item in data.get("DataList") or []:
        image_id = (item.get("StatusObject") or {}).get("ImageId")
        if image_id:
            result_by_id[image_id] = item
    return result_by_id


def build_vlm_prompt(source_api_labels: list[str]) -> str:
    source = "、".join(source_api_labels) if source_api_labels else "无"
    return f"""
你是课堂图片数据标注员。请只判断红色框内的老师主体，不要判断其他学生或背景。

目标是输出 4 个英文标签中的一个或多个：
- sit：坐
- stand：站
- bbwriting：写板书
- teach：讲授演示

候选 API 标签是：{source}。候选标签可能错误，只能作为参考，必须以图片视觉内容为准。

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
    annotations_path = dataset_dir / "annotations.jsonl"
    classes_path = dataset_dir / "classes.txt"

    if args.clear_output:
        for directory in [dataset_dir, review_dir, preview_dir]:
            if directory.exists():
                shutil.rmtree(directory)

    for directory in [dataset_dir, review_dir, preview_dir, images_dir, yolo_dir, raw_vlm_dir]:
        directory.mkdir(parents=True, exist_ok=True)
    classes_path.write_text("\n".join(LABEL_ORDER) + "\n", encoding="utf-8")

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing API key env var: {args.api_key_env}")

    font_path = find_font_path()
    image_paths = sorted(
        path for path in src_dir.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    )
    if args.limit:
        image_paths = image_paths[: args.limit]

    annotations: list[dict[str, Any]] = []
    start = time.time()
    processed = 0
    needs_review_count = 0
    label_counts = {label: 0 for label in LABEL_ORDER}

    for index in range(0, len(image_paths), args.detect_batch_size):
        batch = image_paths[index:index + args.detect_batch_size]
        results = detect_teacher_batch(batch, args.detect_url)

        for image_path in batch:
            with Image.open(image_path) as image:
                width, height = image.size
            dataset_image_path = images_dir / image_path.name
            shutil.copy2(image_path, dataset_image_path)

            result_item = results.get(image_path.stem)
            candidate = select_teacher_candidate(result_item or {}, width=width, height=height)
            box_xyxy = candidate.box_xyxy if candidate else None
            source_api_labels = candidate.source_api_labels if candidate else []
            source_api_object_types = candidate.source_api_object_types if candidate else []
            normalized_box = normalize_xyxy_to_yolo(box_xyxy, width, height) if box_xyxy else None

            preview_path = preview_dir / image_path.name
            review_path = review_dir / image_path.name
            draw_box_only(image_path, preview_path, box_xyxy)

            if box_xyxy is None:
                parsed = {"labels": [], "needs_review": True, "reason": "未检测到候选老师框", "raw_json": {}}
                raw_response = {}
                raw_text = ""
            else:
                raw_response, raw_text = call_vlm(preview_path, source_api_labels, args.ark_url, args.model, api_key)
                parsed = parse_vlm_labels(raw_text, source_api_labels)

            raw_vlm_path = raw_vlm_dir / f"{image_path.stem}.json"
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
            write_yolo_labels(yolo_dir / f"{image_path.stem}.txt", labels, normalized_box)
            draw_review_image(image_path, review_path, box_xyxy, labels, font_path)

            annotation = {
                "image": image_path.name,
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
                "needs_review": parsed["needs_review"],
                "reason": parsed["reason"],
                "raw_vlm_path": str(raw_vlm_path),
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
    parser.add_argument("--detect-url", default="http://127.0.0.1:8881/ImageDetect/teacher/v1.0.0")
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
