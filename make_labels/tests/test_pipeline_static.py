from pathlib import Path


PIPELINE_SOURCE = Path(__file__).resolve().parents[1] / "app" / "pipeline.py"


def test_pipeline_uses_queue_for_capture_and_label_overlap():
    source = PIPELINE_SOURCE.read_text(encoding="utf-8")

    assert "asyncio.Queue" in source
    assert "detect_workers" in source
    assert "asyncio.gather(producer()" in source


def test_pipeline_confirms_teacher_stream_and_checks_subject_before_labeling():
    source = PIPELINE_SOURCE.read_text(encoding="utf-8")

    assert "build_teacher_stream_confirm_prompt" in source
    assert "parse_teacher_stream_confirm_response" in source
    assert "build_subject_identity_prompt" in source
    assert "parse_subject_identity_response" in source
    assert "build_subject_identity_confirm_prompt" in source
    assert "render_box_preview" in source
    assert "subject_unknown" in source
    assert "subject_student" in source
