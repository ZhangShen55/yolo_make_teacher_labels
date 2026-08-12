from pathlib import Path

import pytest

from make_label.config import load_settings


def write_config(tmp_path: Path, *, platform_auth: str | None = None, vlm_extra: str = 'api_key = "ark-value"') -> Path:
    config_path = tmp_path / "config.toml"
    output_root = tmp_path / "out"
    auth = platform_auth
    if auth is None:
        auth = """
[platform.auth]
token_path = "/cloud-rbac/access_token"
grant_type = "password"
client_secret = "client-secret"
client_id = "jy-system-management-he"
username = "admin"
password = "secret-password"
refresh_interval_seconds = 3600
"""
    config_path.write_text(
        f"""
[platform]
base_url = "https://ft.nuaa.edu.cn"
course_list_path = "/jy-system-management-he/v1/vod"
vod_detail_path_template = "/jy-system-management-he/v1/vod/{{course_id}}"
organizations_path = "/jy-system-management-he/v1/organizations"
page_size = 100
start_page = 2
max_pages = 3
begin_time = "2026-06-01 00:00:00"
end_time = "2026-06-10 23:59:59"
orga_ids = [4, 6]
referer = "https://ft.nuaa.edu.cn/"
origin = "https://ft.nuaa.edu.cn"
{auth}

[video]
teacher_select_probe_second = 1200
capture_start_second = 300
capture_interval_second = 300
max_frames_per_course = 8
capture_workers = 2
command_timeout_seconds = 45
capture_jitter_seconds = 30

[dataset]
output_root = "{output_root}"
batch_size = 1000
batch_prefix = "batch_"

[algorithm_8881]
teacher_detect_url = "http://127.0.0.1:8881/ImageDetect/teacher/v1.0.0"
presence_object_type = 100
min_presence_count = 1
detect_workers = 8
timeout_seconds = 30

[vlm]
api_url = "https://ark.cn-beijing.volces.com/api/v3/responses"
model = "doubao-seed-2-0-mini-260428"
{vlm_extra}
workers = 8
timeout_seconds = 60

[runtime]
resume = true
log_dir = "logs"
tmp_dir = "tmp_frames"
failed_dir = "failed"
log_sensitive_urls = true
""",
        encoding="utf-8",
    )
    return config_path


def test_load_settings_reads_platform_auth_and_vlm_api_key_from_toml(tmp_path, monkeypatch):
    monkeypatch.delenv("VOD_COOKIE", raising=False)
    monkeypatch.delenv("VOD_JWT_TOKEN", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    config_path = write_config(tmp_path)

    settings = load_settings(config_path)

    assert settings.platform.page_size == 100
    assert settings.platform.start_page == 2
    assert settings.platform.organizations_path == "/jy-system-management-he/v1/organizations"
    assert settings.platform.orga_ids == [4, 6]
    assert settings.platform.auth.token_path == "/cloud-rbac/access_token"
    assert settings.platform.auth.grant_type == "password"
    assert settings.platform.auth.client_secret == "client-secret"
    assert settings.platform.auth.client_id == "jy-system-management-he"
    assert settings.platform.auth.username == "admin"
    assert settings.platform.auth.password == "secret-password"
    assert settings.platform.auth.refresh_interval_seconds == 3600
    assert settings.platform.cookie == ""
    assert settings.video.command_timeout_seconds == 45
    assert settings.video.capture_jitter_seconds == 30
    assert settings.runtime.log_sensitive_urls is True
    assert settings.vlm.api_key == "ark-value"
    assert settings.dataset.output_root == (tmp_path / "out").resolve()


def test_platform_auth_refresh_interval_defaults_to_twelve_hours(tmp_path, monkeypatch):
    monkeypatch.delenv("VOD_COOKIE", raising=False)
    monkeypatch.delenv("VOD_JWT_TOKEN", raising=False)
    auth_without_interval = """
[platform.auth]
token_path = "/cloud-rbac/access_token"
grant_type = "password"
client_secret = "client-secret"
client_id = "jy-system-management-he"
username = "admin"
password = "secret-password"
"""
    settings = load_settings(write_config(tmp_path, platform_auth=auth_without_interval))

    assert settings.platform.auth.refresh_interval_seconds == 43200


@pytest.mark.parametrize(
    ("auth", "missing"),
    [
        ("", "[platform.auth]"),
        (
            """
[platform.auth]
grant_type = "password"
client_secret = "client-secret"
client_id = "jy-system-management-he"
username = "admin"
password = "secret-password"
""",
            "token_path",
        ),
        (
            """
[platform.auth]
token_path = "/cloud-rbac/access_token"
client_secret = "client-secret"
client_id = "jy-system-management-he"
username = "admin"
password = "secret-password"
""",
            "grant_type",
        ),
        (
            """
[platform.auth]
token_path = "/cloud-rbac/access_token"
grant_type = "password"
client_id = "jy-system-management-he"
username = "admin"
password = "secret-password"
""",
            "client_secret",
        ),
        (
            """
[platform.auth]
token_path = "/cloud-rbac/access_token"
grant_type = "password"
client_secret = "client-secret"
username = "admin"
password = "secret-password"
""",
            "client_id",
        ),
        (
            """
[platform.auth]
token_path = "/cloud-rbac/access_token"
grant_type = "password"
client_secret = "client-secret"
client_id = "jy-system-management-he"
password = "secret-password"
""",
            "username",
        ),
        (
            """
[platform.auth]
token_path = "/cloud-rbac/access_token"
grant_type = "password"
client_secret = "client-secret"
client_id = "jy-system-management-he"
username = "admin"
""",
            "password",
        ),
    ],
)
def test_load_settings_fails_when_platform_auth_field_missing(tmp_path, auth, missing):
    config_path = write_config(tmp_path, platform_auth=auth)

    with pytest.raises((KeyError, RuntimeError), match=missing):
        load_settings(config_path)


def test_load_settings_fails_when_vlm_api_key_missing(tmp_path):
    config_path = write_config(tmp_path, vlm_extra="")

    with pytest.raises((KeyError, RuntimeError), match=r"\[vlm\]\.api_key"):
        load_settings(config_path)
