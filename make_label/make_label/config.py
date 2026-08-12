from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


def require_config_value(section: str, data: dict, key: str) -> str:
    value = str(data.get(key, "")).strip()
    if not value:
        raise RuntimeError(f"Missing required config value: [{section}].{key}")
    return value


def require_config_section(parent: str, data: dict, key: str) -> dict:
    value = data.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Missing required config section: [{parent}.{key}]")
    return value


@dataclass(frozen=True)
class PlatformAuthSettings:
    token_path: str
    grant_type: str
    client_secret: str
    client_id: str
    username: str
    password: str
    refresh_interval_seconds: int


@dataclass(frozen=True)
class PlatformSettings:
    base_url: str
    course_list_path: str
    vod_detail_path_template: str
    organizations_path: str
    page_size: int
    start_page: int
    max_pages: int
    begin_time: str
    end_time: str
    orga_ids: list[int]
    auth: PlatformAuthSettings
    cookie: str
    referer: str
    origin: str


@dataclass(frozen=True)
class VideoSettings:
    teacher_select_probe_second: int
    capture_start_second: int
    capture_interval_second: int
    max_frames_per_course: int
    capture_workers: int
    command_timeout_seconds: int
    capture_jitter_seconds: int


@dataclass(frozen=True)
class DatasetSettings:
    output_root: Path
    batch_size: int
    batch_prefix: str


@dataclass(frozen=True)
class AlgorithmSettings:
    teacher_detect_url: str
    presence_object_type: int
    min_presence_count: int
    detect_workers: int
    timeout_seconds: int


@dataclass(frozen=True)
class VlmSettings:
    api_url: str
    model: str
    api_key: str
    workers: int
    timeout_seconds: int


@dataclass(frozen=True)
class RuntimeSettings:
    resume: bool
    log_dir: Path
    tmp_dir: Path
    failed_dir: Path
    log_sensitive_urls: bool


@dataclass(frozen=True)
class Settings:
    platform: PlatformSettings
    video: VideoSettings
    dataset: DatasetSettings
    algorithm_8881: AlgorithmSettings
    vlm: VlmSettings
    runtime: RuntimeSettings


def resolve_path(config_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = config_dir / path
    return path.resolve()


def parse_int_list(value: object) -> list[int]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [int(item.strip()) for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [int(item) for item in value]
    raise TypeError(f"Expected list or comma-separated string, got {type(value).__name__}")


def load_settings(config_path: str | Path) -> Settings:
    config_path = Path(config_path).expanduser().resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    config_dir = config_path.parent

    platform = data["platform"]
    platform_filters = platform.get("filters", {})
    platform_auth = require_config_section("platform", platform, "auth")
    vlm = data["vlm"]

    return Settings(
        platform=PlatformSettings(
            base_url=platform["base_url"].rstrip("/"),
            course_list_path=platform["course_list_path"],
            vod_detail_path_template=platform["vod_detail_path_template"],
            organizations_path=str(platform.get("organizations_path", "/jy-system-management-he/v1/organizations")),
            page_size=int(platform.get("page_size", 100)),
            start_page=int(platform.get("start_page", 1)),
            max_pages=int(platform.get("max_pages", 0)),
            begin_time=str(platform_filters.get("cour_begin_time", platform.get("begin_time", ""))),
            end_time=str(platform_filters.get("cour_end_time", platform.get("end_time", ""))),
            orga_ids=parse_int_list(platform_filters.get("orga_ids", platform.get("orga_ids", []))),
            auth=PlatformAuthSettings(
                token_path=require_config_value("platform.auth", platform_auth, "token_path"),
                grant_type=require_config_value("platform.auth", platform_auth, "grant_type"),
                client_secret=require_config_value("platform.auth", platform_auth, "client_secret"),
                client_id=require_config_value("platform.auth", platform_auth, "client_id"),
                username=require_config_value("platform.auth", platform_auth, "username"),
                password=require_config_value("platform.auth", platform_auth, "password"),
                refresh_interval_seconds=int(platform_auth.get("refresh_interval_seconds", 43200)),
            ),
            cookie=str(platform.get("cookie", "")).strip(),
            referer=str(platform.get("referer", platform["base_url"])),
            origin=str(platform.get("origin", platform["base_url"])),
        ),
        video=VideoSettings(
            teacher_select_probe_second=int(data["video"].get("teacher_select_probe_second", 1200)),
            capture_start_second=int(data["video"].get("capture_start_second", 300)),
            capture_interval_second=int(data["video"].get("capture_interval_second", 300)),
            max_frames_per_course=int(data["video"].get("max_frames_per_course", 8)),
            capture_workers=int(data["video"].get("capture_workers", 2)),
            command_timeout_seconds=int(data["video"].get("command_timeout_seconds", 60)),
            capture_jitter_seconds=int(data["video"].get("capture_jitter_seconds", 0)),
        ),
        dataset=DatasetSettings(
            output_root=resolve_path(config_dir, data["dataset"].get("output_root", "南航收集")),
            batch_size=int(data["dataset"].get("batch_size", 1000)),
            batch_prefix=str(data["dataset"].get("batch_prefix", "batch_")),
        ),
        algorithm_8881=AlgorithmSettings(
            teacher_detect_url=data["algorithm_8881"]["teacher_detect_url"],
            presence_object_type=int(data["algorithm_8881"].get("presence_object_type", 100)),
            min_presence_count=int(data["algorithm_8881"].get("min_presence_count", 1)),
            detect_workers=int(data["algorithm_8881"].get("detect_workers", 8)),
            timeout_seconds=int(data["algorithm_8881"].get("timeout_seconds", 30)),
        ),
        vlm=VlmSettings(
            api_url=vlm["api_url"],
            model=vlm["model"],
            api_key=require_config_value("vlm", vlm, "api_key"),
            workers=int(vlm.get("workers", 8)),
            timeout_seconds=int(vlm.get("timeout_seconds", 60)),
        ),
        runtime=RuntimeSettings(
            resume=bool(data["runtime"].get("resume", True)),
            log_dir=resolve_path(config_dir, data["runtime"].get("log_dir", "logs")),
            tmp_dir=resolve_path(config_dir, data["runtime"].get("tmp_dir", "tmp_frames")),
            failed_dir=resolve_path(config_dir, data["runtime"].get("failed_dir", "failed")),
            log_sensitive_urls=bool(data["runtime"].get("log_sensitive_urls", False)),
        ),
    )
