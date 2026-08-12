import asyncio

import pytest

from make_label.config import PlatformAuthSettings, PlatformSettings
from make_label.platform_client import PlatformTokenProvider, parse_access_token_payload


def platform_settings(refresh_interval_seconds: int = 3600) -> PlatformSettings:
    return PlatformSettings(
        base_url="https://mlb.ahnu.edu.cn",
        course_list_path="/jy-system-management-he/v1/vod",
        vod_detail_path_template="/jy-system-management-he/v1/vod/{course_id}",
        organizations_path="/jy-system-management-he/v1/organizations",
        page_size=50,
        start_page=1,
        max_pages=0,
        begin_time="",
        end_time="",
        orga_ids=[],
        auth=PlatformAuthSettings(
            token_path="/cloud-rbac/access_token",
            grant_type="password",
            client_secret="client-secret",
            client_id="jy-system-management-he",
            username="admin",
            password="secret-password",
            refresh_interval_seconds=refresh_interval_seconds,
        ),
        cookie="",
        referer="https://mlb.ahnu.edu.cn/",
        origin="https://mlb.ahnu.edu.cn/",
    )


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200, headers: dict | None = None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_parse_access_token_payload_accepts_common_shapes():
    assert parse_access_token_payload({"access_token": "token-a"}) == "token-a"
    assert parse_access_token_payload({"data": {"access_token": "token-b"}}) == "token-b"
    assert parse_access_token_payload({"data": {"jwtToken": "token-c"}}) == "token-c"
    assert parse_access_token_payload({"result": {"jwt_token": "token-d"}}) == "token-d"
    assert parse_access_token_payload({"result": {"access_token": "token-e"}}) == "token-e"


def test_parse_access_token_payload_rejects_missing_token():
    with pytest.raises(RuntimeError, match="access token"):
        parse_access_token_payload({"data": {"ok": True}})


def test_token_provider_builds_token_url_from_base_url_and_path():
    provider = PlatformTokenProvider(platform_settings())

    assert provider.token_url() == "https://mlb.ahnu.edu.cn/cloud-rbac/access_token"


def test_first_token_fetch_uses_configured_password_grant(monkeypatch):
    calls = []

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, params):
            calls.append({"url": url, "params": params, "kwargs": self.kwargs})
            return FakeResponse({"access_token": "token-1"})

    monkeypatch.setattr("make_label.platform_client.httpx.AsyncClient", FakeAsyncClient)

    token = asyncio.run(PlatformTokenProvider(platform_settings()).get_token())

    assert token == "token-1"
    assert calls == [
        {
            "url": "https://mlb.ahnu.edu.cn/cloud-rbac/access_token",
            "params": {
                "grant_type": "password",
                "client_secret": "client-secret",
                "client_id": "jy-system-management-he",
                "username": "admin",
                "password": "secret-password",
            },
            "kwargs": {"timeout": 30, "trust_env": False},
        }
    ]


def test_cached_token_is_reused_before_refresh_interval(monkeypatch):
    now = [1000.0]
    calls = []

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, params):
            calls.append(params)
            return FakeResponse({"access_token": f"token-{len(calls)}"})

    monkeypatch.setattr("make_label.platform_client.httpx.AsyncClient", FakeAsyncClient)
    provider = PlatformTokenProvider(platform_settings(refresh_interval_seconds=3600), clock=lambda: now[0])

    first = asyncio.run(provider.get_token())
    now[0] += 3599
    second = asyncio.run(provider.get_token())

    assert first == "token-1"
    assert second == "token-1"
    assert len(calls) == 1


def test_stale_token_refreshes_after_refresh_interval(monkeypatch):
    now = [1000.0]
    calls = []

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, params):
            calls.append(params)
            return FakeResponse({"access_token": f"token-{len(calls)}"})

    monkeypatch.setattr("make_label.platform_client.httpx.AsyncClient", FakeAsyncClient)
    provider = PlatformTokenProvider(platform_settings(refresh_interval_seconds=3600), clock=lambda: now[0])

    first = asyncio.run(provider.get_token())
    now[0] += 3600
    second = asyncio.run(provider.get_token())

    assert first == "token-1"
    assert second == "token-2"
    assert len(calls) == 2


def test_concurrent_first_requests_share_one_token_refresh(monkeypatch):
    calls = []

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, params):
            calls.append(params)
            await asyncio.sleep(0)
            return FakeResponse({"access_token": "shared-token"})

    monkeypatch.setattr("make_label.platform_client.httpx.AsyncClient", FakeAsyncClient)
    provider = PlatformTokenProvider(platform_settings())

    async def run_requests():
        return await asyncio.gather(*(provider.get_token() for _ in range(5)))

    assert asyncio.run(run_requests()) == ["shared-token"] * 5
    assert len(calls) == 1
