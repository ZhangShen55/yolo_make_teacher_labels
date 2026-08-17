import asyncio

from PIL import Image

import app.vlm_labeler as vlm_labeler
from app.vlm_labeler import (
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


def test_ark_vlm_client_uses_openai_responses_api_and_serializes_response(monkeypatch, tmp_path):
    image_path = tmp_path / "teacher.jpg"
    Image.new("RGB", (4, 4), "white").save(image_path)
    captured = {}

    class FakeResponse:
        output_text = '{"labels":["stand","teach"]}'

        def model_dump(self):
            return {"id": "response-id", "output_text": self.output_text}

    class FakeResponses:
        async def create(self, **kwargs):
            captured["request"] = kwargs
            return FakeResponse()

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.responses = FakeResponses()

        async def close(self):
            captured["closed"] = True

    monkeypatch.setattr(vlm_labeler, "AsyncOpenAI", FakeAsyncOpenAI, raising=False)
    client = ArkVlmClient(
        "https://ark.example/api/plan/v3",
        api_key="secret-value",
        model="doubao-seed-2.0-mini",
        timeout_seconds=45,
    )

    raw_response, response_text = asyncio.run(
        client.ask_images_with_raw([image_path], "判断教师行为")
    )
    asyncio.run(client.close())

    assert captured["client"] == {
        "base_url": "https://ark.example/api/plan/v3",
        "api_key": "secret-value",
        "timeout": 45,
    }
    assert captured["request"]["model"] == "doubao-seed-2.0-mini"
    content = captured["request"]["input"][0]["content"]
    assert content[0]["type"] == "input_image"
    assert content[0]["image_url"].startswith("data:image/jpeg;base64,")
    assert content[1] == {"type": "input_text", "text": "判断教师行为"}
    assert response_text == '{"labels":["stand","teach"]}'
    assert raw_response == {
        "id": "response-id",
        "output_text": '{"labels":["stand","teach"]}',
    }
    assert captured["closed"] is True


def test_parse_teacher_stream_choice_accepts_json_index():
    response = '```json\n{"teacher_index": 2, "confidence": 0.91, "reason": "讲台和教师"}\n```'

    parsed = parse_teacher_stream_choice(response, candidate_count=3)

    assert parsed.teacher_index == 2
    assert parsed.confidence == 0.91
    assert parsed.reason == "讲台和教师"


def test_parse_teacher_stream_choice_returns_none_when_uncertain():
    response = '{"teacher_index": null, "confidence": 0.2, "reason": "都是课件"}'

    parsed = parse_teacher_stream_choice(response, candidate_count=3)

    assert parsed.teacher_index is None
    assert parsed.confidence == 0.2


def test_parse_vlm_label_response_enforces_pose_mutex_and_action_multilabel():
    response = '{"labels": ["sit", "stand", "bbwriting", "teach"], "reason": "conflict"}'

    parsed = parse_vlm_label_response(response, fallback_labels=["sit"])

    assert parsed.labels == ["sit", "bbwriting", "teach"]
    assert parsed.needs_review is True


def test_parse_vlm_label_response_adds_fallback_pose_when_missing():
    response = '{"labels": ["teach"], "reason": "讲授"}'

    parsed = parse_vlm_label_response(response, fallback_labels=["stand", "teach"])

    assert parsed.labels == ["stand", "teach"]
    assert parsed.needs_review is True


def test_teacher_stream_prompt_mentions_three_candidates_and_20_minute_frame():
    prompt = build_teacher_stream_prompt(candidate_count=3)

    assert "3" in prompt
    assert "20分钟" in prompt
    assert "teacher_index" in prompt


def test_parse_teacher_stream_confirm_response_accepts_stream_types():
    parsed = parse_teacher_stream_confirm_response(
        '{"stream_type": "teacher_stream", "confidence": 0.88, "reason": "讲台区域"}'
    )

    assert parsed.stream_type == "teacher_stream"
    assert parsed.confidence == 0.88


def test_teacher_stream_confirm_prompt_is_non_leading_classification():
    prompt = build_teacher_stream_confirm_prompt()

    assert "teacher_stream" in prompt
    assert "student_stream" in prompt
    assert "screen_stream" in prompt
    assert "unknown" in prompt
    assert "是否确实" not in prompt


def test_parse_subject_identity_response_accepts_teacher_student_unknown():
    parsed = parse_subject_identity_response('{"subject": "student", "confidence": 0.74, "reason": "座位区域"}')

    assert parsed.subject == "student"
    assert parsed.confidence == 0.74
    assert parsed.reason == "座位区域"


def test_subject_identity_prompts_are_non_leading_and_include_scene_rules():
    first_prompt = build_subject_identity_prompt()
    second_prompt = build_subject_identity_confirm_prompt()

    for prompt in [first_prompt, second_prompt]:
        assert "teacher" in prompt
        assert "student" in prompt
        assert "unknown" in prompt
        assert "课堂场景" in prompt
        assert "前排" in prompt
        assert "背向镜头" in prompt
        assert "是否为" not in prompt


def test_label_prompt_contains_stricter_teach_and_pose_rules():
    prompt = build_label_prompt()

    assert "框上方" in prompt
    assert "初检候选" in prompt
    assert "保留、删除或补充" in prompt
    assert "204" in prompt
    assert "明显肢体" in prompt
    assert "嘴部" in prompt
    assert "背朝向镜头" in prompt
    assert "不能仅因为人物高度低" in prompt
    assert "讲台高" in prompt
    assert "优先标stand" in prompt
