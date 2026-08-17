from __future__ import annotations

import base64
import json
from pathlib import Path
import re
from typing import Any

from openai import AsyncOpenAI

from .models import SubjectIdentityResult, TeacherStreamChoice, TeacherStreamConfirmResult, VlmLabelResult


LABEL_ORDER = ["sit", "stand", "bbwriting", "teach"]
STREAM_TYPES = {"teacher_stream", "student_stream", "screen_stream", "unknown"}
SUBJECT_TYPES = {"teacher", "student", "unknown"}


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
    clean = {label for label in labels if label in LABEL_ORDER}
    return [label for label in LABEL_ORDER if label in clean]


def fallback_pose(labels: list[str]) -> str:
    if "sit" in labels:
        return "sit"
    return "stand"


def parse_teacher_stream_choice(response_text: str, candidate_count: int) -> TeacherStreamChoice:
    try:
        payload = json.loads(strip_json_fence(response_text))
    except json.JSONDecodeError:
        return TeacherStreamChoice(teacher_index=None, confidence=0.0, reason=response_text.strip()[:300])

    raw_index = payload.get("teacher_index")
    teacher_index = int(raw_index) if isinstance(raw_index, int) and 1 <= raw_index <= candidate_count else None
    return TeacherStreamChoice(
        teacher_index=teacher_index,
        confidence=float(payload.get("confidence") or 0.0),
        reason=str(payload.get("reason") or ""),
    )


def parse_teacher_stream_confirm_response(response_text: str) -> TeacherStreamConfirmResult:
    try:
        payload = json.loads(strip_json_fence(response_text))
    except json.JSONDecodeError:
        return TeacherStreamConfirmResult(stream_type="unknown", confidence=0.0, reason=response_text.strip()[:300])
    stream_type = str(payload.get("stream_type") or "unknown").strip()
    if stream_type not in STREAM_TYPES:
        stream_type = "unknown"
    return TeacherStreamConfirmResult(
        stream_type=stream_type,
        confidence=float(payload.get("confidence") or 0.0),
        reason=str(payload.get("reason") or ""),
    )


def parse_subject_identity_response(response_text: str) -> SubjectIdentityResult:
    try:
        payload = json.loads(strip_json_fence(response_text))
    except json.JSONDecodeError:
        return SubjectIdentityResult(subject="unknown", confidence=0.0, reason=response_text.strip()[:300])
    subject = str(payload.get("subject") or "unknown").strip()
    if subject not in SUBJECT_TYPES:
        subject = "unknown"
    return SubjectIdentityResult(
        subject=subject,
        confidence=float(payload.get("confidence") or 0.0),
        reason=str(payload.get("reason") or ""),
    )


def parse_vlm_label_response(response_text: str, fallback_labels: list[str]) -> VlmLabelResult:
    needs_review = False
    reason = ""
    try:
        payload = json.loads(strip_json_fence(response_text))
    except json.JSONDecodeError:
        payload = {}
        needs_review = True
        reason = response_text.strip()[:300]

    if isinstance(payload.get("labels"), list):
        labels = ordered_labels([str(item).strip() for item in payload["labels"]])
    else:
        labels = ordered_labels(
            [
                label
                for label in LABEL_ORDER
                if payload.get(label) is True or str(payload.get(label)).lower() == "true"
            ]
        )

    if isinstance(payload.get("needs_review"), bool):
        needs_review = needs_review or payload["needs_review"]
    if isinstance(payload.get("reason"), str):
        reason = payload["reason"]

    has_sit = "sit" in labels
    has_stand = "stand" in labels
    if has_sit and has_stand:
        labels = [label for label in labels if label not in {"sit", "stand"}]
        labels.insert(0, fallback_pose(fallback_labels))
        needs_review = True
    elif not has_sit and not has_stand:
        labels.insert(0, fallback_pose(fallback_labels))
        needs_review = True

    return VlmLabelResult(labels=ordered_labels(labels), needs_review=needs_review, reason=reason, raw_json=payload)


def build_teacher_stream_prompt(candidate_count: int) -> str:
    return (
        f"这里有同一节课三端视频在20分钟位置抽取的{candidate_count}张候选帧。"
        "请判断哪一张是拍摄讲台/教师/老师授课视角。"
        "只输出JSON：{\"teacher_index\": 1或2或3或null, \"confidence\": 0到1, \"reason\": \"简短原因\"}。"
        "如果无法明确判断教师端，teacher_index 输出 null。"
    )


def build_teacher_stream_confirm_prompt() -> str:
    return (
        "这是一节课堂录播三端视频中的一个候选画面。请根据画面主体内容判断该画面主要属于哪类视角："
        "teacher_stream=拍摄讲台/教师授课区域；student_stream=拍摄学生区域；"
        "screen_stream=课件或电脑录屏内容；unknown=无法明确判断。"
        "请只输出JSON：{\"stream_type\":\"teacher_stream|student_stream|screen_stream|unknown\","
        "\"confidence\":0到1,\"reason\":\"简短原因\"}。"
    )


def build_subject_identity_prompt() -> str:
    return (
        "这是一张课堂场景图片，红框标出一个人物主体。"
        "请结合讲台、黑板/屏幕、座位方向、人物朝向、人物所在区域，判断红框中人物更可能是老师、学生还是无法判断。"
        "如果人物坐在前排或学生座位区域、朝向讲台/黑板/屏幕、背向镜头，通常更可能是学生。"
        "如果人物位于讲台、黑板或屏幕附近，承担授课、板书、演示或操作讲台区域的角色，通常更可能是老师。"
        "请只输出JSON：{\"subject\":\"teacher|student|unknown\",\"confidence\":0到1,\"reason\":\"简短原因\"}。"
    )


def build_subject_identity_confirm_prompt() -> str:
    return (
        "这是课堂场景中的一张图片，红框标出一个人物。"
        "请独立判断红框中人物在这个课堂场景里更可能是老师、学生还是无法判断。"
        "判断时结合讲台、黑板/屏幕、座位方向、前排位置、人物朝向和背向镜头等线索。"
        "请只输出JSON：{\"subject\":\"teacher|student|unknown\",\"confidence\":0到1,\"reason\":\"简短原因\"}。"
    )


def build_label_prompt() -> str:
    return (
        "图片中已用红框标出老师主体，并在框上方如实标出 detector 返回的全部中文初检候选标签。"
        "这些初检候选可能存在误检或漏检，你必须以图片视觉内容为准，对候选行为进行保留、删除或补充，不能照抄文字。"
        "其中 detector 的 ObjectType=204 表示讲授候选，但只有视觉上确实正在讲授时才保留 teach；"
        "即使没有 204，只要画面明显在讲授，也可以补充 teach。"
        "请判断最终教师行为标签，只输出JSON。"
        "labels 只能从 sit, stand, bbwriting, teach 中选择。"
        "sit和stand互斥且必须二选一；bbwriting和teach可同时存在。"
        "只有明显讲授行为才标teach：例如有明显肢体讲解动作、指向黑板/屏幕/学生、面向学生讲解，"
        "或嘴部有明显讲话动作，或正在进行课堂内容讲授演示。"
        "如果只是站在讲台上、走动、低头看电脑、整理物品，没有明显讲授动作，不标teach。"
        "如果背朝向镜头且只是在板书，不标teach，只标bbwriting。"
        "明显边板书边讲授才同时标bbwriting和teach。"
        "坐站判断：不能仅因为人物高度低、老师身高矮、讲台高、下半身被讲台遮挡，就判断为sit。"
        "如果人物位于讲台后，虽然身体被遮挡，但上半身姿态像站立授课，应标stand。"
        "只有明确看到坐姿、椅子/座位关系、身体重心明显为坐着，才标sit。"
        "坐站不确定时，优先标stand，并设置needs_review=true。"
        "格式：{\"labels\":[\"stand\",\"teach\"],\"needs_review\":false,\"reason\":\"简短原因\"}"
    )


def image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


class ArkVlmClient:
    def __init__(self, api_url: str, api_key: str, model: str, timeout_seconds: int = 60):
        self.api_url = api_url
        self.model = model
        self.client = AsyncOpenAI(
            base_url=api_url,
            api_key=api_key,
            timeout=timeout_seconds,
        )

    async def ask_images(self, image_paths: list[Path], prompt: str) -> str:
        _, response_text = await self.ask_images_with_raw(image_paths, prompt)
        return response_text

    async def close(self) -> None:
        await self.client.close()

    async def ask_images_with_raw(
        self,
        image_paths: list[Path],
        prompt: str,
    ) -> tuple[dict[str, Any], str]:
        content: list[dict[str, Any]] = [
            {"type": "input_image", "image_url": image_to_data_url(path)} for path in image_paths
        ]
        content.append({"type": "input_text", "text": prompt})
        response = await self.client.responses.create(
            model=self.model,
            input=[{"role": "user", "content": content}],
        )
        return response.model_dump(), extract_response_text(response)


def extract_response_text(payload: Any) -> str:
    output_text = getattr(payload, "output_text", None)
    if isinstance(output_text, str) and output_text:
        return output_text
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    if not isinstance(payload, dict):
        return str(payload)

    texts: list[str] = []
    for item in payload.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                texts.append(str(content["text"]))
    if texts:
        return "\n".join(texts)
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    return json.dumps(payload, ensure_ascii=False)
