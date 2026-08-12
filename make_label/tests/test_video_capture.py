import subprocess

import pytest

from make_label.video_capture import VideoCommandError, extract_frame, frame_offsets, run_video_command, should_probe_video


def test_should_probe_video_skips_when_shorter_than_probe_second():
    assert should_probe_video(duration_seconds=1199, probe_second=1200) is False
    assert should_probe_video(duration_seconds=1200, probe_second=1200) is True


def test_frame_offsets_start_every_interval_with_max_count_and_duration_limit():
    offsets = frame_offsets(
        duration_seconds=2400,
        start_second=300,
        interval_second=300,
        max_frames=8,
    )

    assert offsets == [300, 600, 900, 1200, 1500, 1800, 2100]


def test_frame_offsets_caps_at_max_frames():
    offsets = frame_offsets(
        duration_seconds=4000,
        start_second=300,
        interval_second=300,
        max_frames=8,
    )

    assert offsets == [300, 600, 900, 1200, 1500, 1800, 2100, 2400]


def test_frame_offsets_apply_jitter_with_bounds_and_sorting():
    class FixedRandom:
        def __init__(self):
            self.values = iter([-30, 10, 30])

        def randint(self, lower, upper):
            assert (lower, upper) == (-30, 30)
            return next(self.values)

    offsets = frame_offsets(
        duration_seconds=1000,
        start_second=300,
        interval_second=300,
        max_frames=3,
        jitter_seconds=30,
        rng=FixedRandom(),
    )

    assert offsets == [300, 610, 930]


def test_run_video_command_retries_transient_failures(monkeypatch):
    calls = []

    def fake_run(command, check, text, capture_output, stdin, timeout):
        calls.append({"command": command, "stdin": stdin, "timeout": timeout})
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, command, stderr="End of file")
        return subprocess.CompletedProcess(command, 0, stdout="12.5\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_video_command(["ffprobe", "url"], retries=2, retry_delay_seconds=0, timeout_seconds=15)

    assert result.stdout == "12.5\n"
    assert len(calls) == 2
    assert calls[0]["stdin"] is subprocess.DEVNULL
    assert calls[0]["timeout"] == 15


def test_run_video_command_raises_short_error_after_retries(monkeypatch):
    def fake_run(command, check, text, capture_output, stdin, timeout):
        raise subprocess.CalledProcessError(187, command, stderr="Stream ends prematurely\nError opening input")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(VideoCommandError) as exc:
        run_video_command(["ffmpeg", "url"], retries=1, retry_delay_seconds=0)

    assert "ffmpeg failed after 2 attempts" in str(exc.value)
    assert "Stream ends prematurely" in str(exc.value)


def test_run_video_command_raises_clear_error_on_timeout(monkeypatch):
    def fake_run(command, check, text, capture_output, stdin, timeout):
        raise subprocess.TimeoutExpired(command, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(VideoCommandError) as exc:
        run_video_command(["ffmpeg", "url"], retries=1, retry_delay_seconds=0, timeout_seconds=10)

    assert "ffmpeg failed after 2 attempts" in str(exc.value)
    assert "timed out after 10 seconds" in str(exc.value)


def test_extract_frame_disables_ffmpeg_stdin(monkeypatch, tmp_path):
    captured = {}

    def fake_run_video_command(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("make_label.video_capture.run_video_command", fake_run_video_command)

    extract_frame("https://example.com/video.mp4", 120, tmp_path / "frame.jpg")

    assert "-nostdin" in captured["command"]
    assert captured["kwargs"]["timeout_seconds"] == 60
