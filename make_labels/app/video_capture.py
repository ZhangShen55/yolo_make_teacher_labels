from __future__ import annotations

from pathlib import Path
import random
import subprocess
import time


class VideoCommandError(RuntimeError):
    pass


def should_probe_video(duration_seconds: float, probe_second: int) -> bool:
    return duration_seconds >= probe_second


def frame_offsets(
    duration_seconds: float,
    start_second: int,
    interval_second: int,
    max_frames: int,
    *,
    jitter_seconds: int = 0,
    rng: random.Random | None = None,
) -> list[int]:
    offsets: list[int] = []
    current = start_second
    generator = rng or random.Random()
    max_offset = max(start_second, int(duration_seconds) - 1)
    while current < duration_seconds and len(offsets) < max_frames:
        offset = current
        if jitter_seconds > 0:
            offset += generator.randint(-jitter_seconds, jitter_seconds)
            offset = max(start_second, min(max_offset, offset))
        if offset not in offsets:
            offsets.append(offset)
        current += interval_second
    return sorted(offsets)


def summarize_stderr(stderr: str | None, limit: int = 300) -> str:
    text = (stderr or "").strip().replace("\n", " ")
    return text[:limit] if text else "no stderr"


def run_video_command(
    command: list[str],
    *,
    retries: int = 2,
    retry_delay_seconds: float = 1.0,
    timeout_seconds: float | None = 60,
) -> subprocess.CompletedProcess[str]:
    attempts = retries + 1
    last_error: subprocess.CalledProcessError | None = None
    last_timeout: subprocess.TimeoutExpired | None = None
    for attempt in range(1, attempts + 1):
        try:
            return subprocess.run(
                command,
                check=True,
                text=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_seconds,
            )
        except subprocess.CalledProcessError as exc:
            last_error = exc
            last_timeout = None
            if attempt < attempts:
                time.sleep(retry_delay_seconds)
        except subprocess.TimeoutExpired as exc:
            last_timeout = exc
            last_error = None
            if attempt < attempts:
                time.sleep(retry_delay_seconds)
    tool = Path(command[0]).name
    if last_timeout is not None:
        timeout = last_timeout.timeout if last_timeout.timeout is not None else timeout_seconds
        raise VideoCommandError(f"{tool} failed after {attempts} attempts: timed out after {timeout:g} seconds") from last_timeout
    assert last_error is not None
    raise VideoCommandError(
        f"{tool} failed after {attempts} attempts with exit {last_error.returncode}: "
        f"{summarize_stderr(last_error.stderr)}"
    ) from last_error


def ffprobe_duration(video_url: str, *, timeout_seconds: float | None = 60) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_url,
    ]
    result = run_video_command(command, timeout_seconds=timeout_seconds)
    return float(result.stdout.strip())


def extract_frame(video_url: str, offset_second: int, out_path: Path, *, timeout_seconds: float | None = 60) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(offset_second),
        "-i",
        video_url,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-y",
        str(out_path),
    ]
    run_video_command(command, timeout_seconds=timeout_seconds)
    return out_path
