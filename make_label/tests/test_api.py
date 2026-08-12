import asyncio

from fastapi.testclient import TestClient

from make_label.config import load_settings
from make_label.main import build_runner_factory, create_app
from make_label.models import JobStatus, OrganizationItem


CONFIG_TEMPLATE = """
[platform]
base_url = "https://ft.nuaa.edu.cn"
course_list_path = "/jy-system-management-he/v1/vod"
vod_detail_path_template = "/jy-system-management-he/v1/vod/{course_id}"

[platform.auth]
token_path = "/cloud-rbac/access_token"
grant_type = "password"
client_secret = "client-secret"
client_id = "jy-system-management-he"
username = "admin"
password = "secret-password"

[video]

[dataset]

[algorithm_8881]
teacher_detect_url = "http://127.0.0.1:8881/ImageDetect/teacher/v1.0.0"

[vlm]
api_url = "https://ark.cn-beijing.volces.com/api/v3/responses"
model = "doubao-seed-2-0-mini-260428"
api_key = "ark-value"

[runtime]
"""


def test_health_and_status_endpoints():
    client = TestClient(create_app())

    assert client.get("/api/health").json() == {"status": "ok"}
    status = client.get("/api/jobs/status").json()
    assert status["running"] is False
    assert status["current_page"] == 0


def test_start_and_stop_job_endpoints():
    client = TestClient(create_app())

    started = client.post("/api/jobs/start").json()
    assert started["running"] is True

    stopped = client.post("/api/jobs/stop").json()
    assert stopped["running"] is False


def test_start_job_accepts_start_page_override():
    client = TestClient(create_app())

    started = client.post("/api/jobs/start", json={"start_page": 7, "max_pages": 2}).json()

    assert started["running"] is True
    assert started["requested_start_page"] == 7
    assert started["requested_max_pages"] == 2


def test_start_job_accepts_course_filter_overrides():
    client = TestClient(create_app())

    started = client.post(
        "/api/jobs/start",
        json={
            "start_page": 7,
            "max_pages": 2,
            "cour_begin_time": "2026-02-14 00:00:00",
            "cour_end_time": "2026-07-16 23:59:59",
            "orga_ids": [4, 6, 38],
        },
    ).json()

    assert started["running"] is True
    assert started["requested_cour_begin_time"] == "2026-02-14 00:00:00"
    assert started["requested_cour_end_time"] == "2026-07-16 23:59:59"
    assert started["requested_orga_ids"] == [4, 6, 38]


def test_config_summary_reports_auth_loaded_without_secrets(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    settings = load_settings(config_path)
    client = TestClient(create_app(settings, config_path=config_path))

    summary = client.get("/api/config").json()

    assert summary["loaded"] is True
    assert summary["platform_auth_loaded"] is True
    assert "secret-password" not in str(summary)
    assert "client-secret" not in str(summary)
    assert "ark-value" not in str(summary)


def test_runner_reloads_config_when_job_starts(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    captured = []

    class FakePipeline:
        def __init__(self, settings, status):
            self.settings = settings
            self.status = status

        async def run(self, start_page=None, max_pages=None, course_filters=None):
            captured.append(
                {
                    "api_key": self.settings.vlm.api_key,
                    "username": self.settings.platform.auth.username,
                    "start_page": start_page,
                    "max_pages": max_pages,
                    "course_filters": course_filters,
                }
            )

    settings_holder = {"settings": load_settings(config_path)}
    config_path.write_text(CONFIG_TEMPLATE.replace('api_key = "ark-value"', 'api_key = "second-ark"'), encoding="utf-8")
    runner = build_runner_factory(settings_holder, config_path=config_path, pipeline_class=FakePipeline)

    asyncio.run(
        runner(
            JobStatus(),
            {
                "start_page": 9,
                "max_pages": 1,
                "cour_begin_time": "2026-02-14 00:00:00",
                "cour_end_time": "2026-07-16 23:59:59",
                "orga_ids": [4, 6],
            },
        )
    )

    assert captured == [
        {
            "api_key": "second-ark",
            "username": "admin",
            "start_page": 9,
            "max_pages": 1,
            "course_filters": {
                "cour_begin_time": "2026-02-14 00:00:00",
                "cour_end_time": "2026-07-16 23:59:59",
                "orga_ids": [4, 6],
            },
        }
    ]
    assert settings_holder["settings"].vlm.api_key == "second-ark"


def test_organization_endpoint_returns_flat_items(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    settings = load_settings(config_path)

    class FakePlatformClient:
        def __init__(self, settings):
            self.settings = settings

        async def fetch_organizations(self):
            return [
                OrganizationItem(
                    id=4,
                    orga_name="计算机学院",
                    orga_level=2,
                    parent_id=1,
                    path="南京航空航天大学 / 计算机学院",
                )
            ]

    client = TestClient(create_app(settings, platform_client_class=FakePlatformClient))

    response = client.get("/api/platform/organizations")

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == 4
    assert response.json()["items"][0]["orga_name"] == "计算机学院"


def test_preflight_run_endpoint_uses_runner(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    settings = load_settings(config_path)

    class FakePreflightRunner:
        def __init__(self, settings):
            self.settings = settings

        async def run(self):
            return {"ok": True, "checks": [{"name": "platform_auth", "ok": True, "detail": "ok"}]}

    client = TestClient(create_app(settings, preflight_runner_class=FakePreflightRunner))

    response = client.post("/api/preflight/run")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["checks"][0]["name"] == "platform_auth"
