import asyncio

import pytest

from app.config import PlatformAuthSettings, PlatformSettings
from app.models import CourseRecord, OrganizationItem, VideoEndpoint
from app.platform_client import (
    AuthExpiredError,
    build_platform_headers,
    extract_course_records,
    extract_organizations,
    extract_three_video_endpoints,
    PlatformClient,
)


def platform_settings(cookie: str = "") -> PlatformSettings:
    return PlatformSettings(
        base_url="https://ft.nuaa.edu.cn",
        course_list_path="/jy-system-management-he/v1/vod",
        vod_detail_path_template="/jy-system-management-he/v1/vod/{course_id}",
        organizations_path="/jy-system-management-he/v1/organizations",
        page_size=100,
        start_page=1,
        max_pages=0,
        begin_time="2026-02-14 00:00:00",
        end_time="2026-07-16 23:59:59",
        orga_ids=[4, 6],
        auth=PlatformAuthSettings(
            token_path="/cloud-rbac/access_token",
            grant_type="password",
            client_secret="client-secret",
            client_id="jy-system-management-he",
            username="admin",
            password="secret-password",
            refresh_interval_seconds=43200,
        ),
        cookie=cookie,
        referer="https://ft.nuaa.edu.cn/",
        origin="https://ft.nuaa.edu.cn",
    )


class StaticTokenProvider:
    def __init__(self, tokens: list[str] | None = None):
        self.tokens = tokens or ["jwt-value"]
        self.index = 0
        self.force_refresh_calls = 0

    async def get_token(self) -> str:
        return self.tokens[self.index]

    async def force_refresh(self) -> str:
        self.force_refresh_calls += 1
        self.index = min(self.index + 1, len(self.tokens) - 1)
        return self.tokens[self.index]


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_build_platform_headers_uses_jwt_token_without_cookie_when_cookie_empty():
    headers = build_platform_headers(
        jwt_token="jwt-value",
        origin="https://ft.nuaa.edu.cn",
        referer="https://ft.nuaa.edu.cn/",
    )

    assert "Cookie" not in headers
    assert headers["jwt-token"] == "jwt-value"
    assert headers["Origin"] == "https://ft.nuaa.edu.cn"
    assert headers["Referer"] == "https://ft.nuaa.edu.cn/"


def test_build_platform_headers_includes_optional_cookie():
    headers = build_platform_headers(
        jwt_token="jwt-value",
        origin="https://ft.nuaa.edu.cn",
        referer="https://ft.nuaa.edu.cn/",
        cookie="session=abc; lang=zh-CN",
    )

    assert headers["Cookie"] == "session=abc; lang=zh-CN"
    assert headers["jwt-token"] == "jwt-value"


def test_extract_course_records_from_platform_response():
    payload = {
        "data": {
            "pageIndex": 1,
            "records": [
                {"id": 1654186, "subjName": "核反应堆热工", "courBeginTime": "2026-06-09 14:00:00"},
                {"id": 1653819, "subjName": "思想道德与法治", "courBeginTime": "2026-06-09 14:00:00"},
            ],
        },
        "success": True,
    }

    records = extract_course_records(payload)

    assert records == [
        CourseRecord(course_id=1654186, subject_name="核反应堆热工", begin_time="2026-06-09 14:00:00"),
        CourseRecord(course_id=1653819, subject_name="思想道德与法治", begin_time="2026-06-09 14:00:00"),
    ]


def test_extract_three_video_endpoints_only_accepts_three_items():
    single_payload = {"data": [{"courId": 1, "url": "https://example.com/a.mp4", "viewNum": 1}]}
    triple_payload = {
        "data": [
            {"courId": 2, "url": "https://example.com/teacher.mp4", "viewNum": 2},
            {"courId": 2, "url": "https://example.com/student.mp4", "viewNum": 3},
            {"courId": 2, "url": "https://example.com/screen.mp4", "viewNum": 5},
        ]
    }

    assert extract_three_video_endpoints(single_payload) is None
    assert extract_three_video_endpoints(triple_payload) == [
        VideoEndpoint(course_id=2, url="https://example.com/teacher.mp4", view_num=2),
        VideoEndpoint(course_id=2, url="https://example.com/student.mp4", view_num=3),
        VideoEndpoint(course_id=2, url="https://example.com/screen.mp4", view_num=5),
    ]


def test_course_list_params_include_time_range_and_orga_ids():
    params = PlatformClient(platform_settings(), token_provider=StaticTokenProvider()).course_list_params(
        3,
        filters={
            "cour_begin_time": "2026-03-01 00:00:00",
            "cour_end_time": "2026-03-31 23:59:59",
            "orga_ids": [38, 39],
        },
    )

    assert params["page.pageIndex"] == 3
    assert params["courBeginTime"] == "2026-03-01 00:00:00"
    assert params["courEndTime"] == "2026-03-31 23:59:59"
    assert params["orgaIds"] == "38,39"


def test_get_json_uses_dynamic_token_header_without_cookie(monkeypatch):
    calls = []

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params):
            calls.append({"url": url, "headers": headers, "params": params})
            return FakeResponse({"ok": True})

    monkeypatch.setattr("app.platform_client.httpx.AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        PlatformClient(platform_settings(), token_provider=StaticTokenProvider(["jwt-dynamic"])).get_json(
            "https://ft.nuaa.edu.cn/api",
            params={"x": 1},
        )
    )

    assert result == {"ok": True}
    assert calls[0]["headers"]["jwt-token"] == "jwt-dynamic"
    assert "Cookie" not in calls[0]["headers"]


def test_get_json_includes_optional_cookie(monkeypatch):
    calls = []

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params):
            calls.append(headers)
            return FakeResponse({"ok": True})

    monkeypatch.setattr("app.platform_client.httpx.AsyncClient", FakeAsyncClient)

    asyncio.run(
        PlatformClient(platform_settings(cookie="session=abc"), token_provider=StaticTokenProvider()).get_json(
            "https://ft.nuaa.edu.cn/api"
        )
    )

    assert calls[0]["Cookie"] == "session=abc"


@pytest.mark.parametrize("status_code", [401, 403])
def test_get_json_force_refreshes_and_retries_once_on_auth_failure(monkeypatch, status_code):
    calls = []

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params):
            calls.append(headers["jwt-token"])
            if len(calls) == 1:
                return FakeResponse({"error": "expired"}, status_code=status_code)
            return FakeResponse({"ok": True})

    token_provider = StaticTokenProvider(["old-token", "new-token"])
    monkeypatch.setattr("app.platform_client.httpx.AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        PlatformClient(platform_settings(), token_provider=token_provider).get_json("https://ft.nuaa.edu.cn/api")
    )

    assert result == {"ok": True}
    assert calls == ["old-token", "new-token"]
    assert token_provider.force_refresh_calls == 1


def test_get_json_reports_auth_error_after_refresh_retry_fails(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params):
            return FakeResponse({"error": "expired"}, status_code=401)

    monkeypatch.setattr("app.platform_client.httpx.AsyncClient", FakeAsyncClient)

    with pytest.raises(AuthExpiredError, match="刷新 token 后仍然失败"):
        asyncio.run(
            PlatformClient(platform_settings(), token_provider=StaticTokenProvider(["old-token", "new-token"])).get_json(
                "https://ft.nuaa.edu.cn/api"
            )
        )


def test_extract_organizations_flattens_tree_with_path():
    payload = {
        "data": [
            {
                "id": 1,
                "orgaName": "南京航空航天大学",
                "orgaLevel": 1,
                "orgaParentId": None,
                "childs": [
                    {
                        "id": 4,
                        "orgaName": "计算机学院",
                        "orgaLevel": 2,
                        "orgaParentId": 1,
                        "childs": None,
                    }
                ],
            }
        ]
    }

    assert extract_organizations(payload) == [
        OrganizationItem(
            id=1,
            orga_name="南京航空航天大学",
            orga_level=1,
            parent_id=None,
            path="南京航空航天大学",
        ),
        OrganizationItem(
            id=4,
            orga_name="计算机学院",
            orga_level=2,
            parent_id=1,
            path="南京航空航天大学 / 计算机学院",
        ),
    ]
