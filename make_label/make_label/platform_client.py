from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urljoin

import httpx

from .config import PlatformSettings
from .models import CourseRecord, OrganizationItem, VideoEndpoint


class AuthExpiredError(RuntimeError):
    pass


def build_platform_headers(jwt_token: str, origin: str, referer: str, cookie: str = "") -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "jwt-token": jwt_token,
        "Origin": origin,
        "Referer": referer,
        "User-Agent": "Mozilla/5.0",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def parse_access_token_payload(payload: dict[str, Any]) -> str:
    candidates = [
        payload.get("access_token"),
        (payload.get("data") or {}).get("access_token") if isinstance(payload.get("data"), dict) else None,
        (payload.get("data") or {}).get("jwtToken") if isinstance(payload.get("data"), dict) else None,
        (payload.get("result") or {}).get("jwt_token") if isinstance(payload.get("result"), dict) else None,
        (payload.get("result") or {}).get("access_token") if isinstance(payload.get("result"), dict) else None,
        payload.get("jwtToken"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raise RuntimeError("Platform token response does not contain an access token")


class PlatformTokenProvider:
    def __init__(self, settings: PlatformSettings, *, clock=time.time):
        self.settings = settings
        self.clock = clock
        self._token = ""
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    def token_url(self) -> str:
        base = self.settings.base_url.rstrip("/") + "/"
        path = self.settings.auth.token_path.lstrip("/")
        return urljoin(base, path)

    def is_fresh(self) -> bool:
        if not self._token:
            return False
        return (self.clock() - self._fetched_at) < self.settings.auth.refresh_interval_seconds

    def token_params(self) -> dict[str, str]:
        auth = self.settings.auth
        return {
            "grant_type": auth.grant_type,
            "client_secret": auth.client_secret,
            "client_id": auth.client_id,
            "username": auth.username,
            "password": auth.password,
        }

    async def get_token(self) -> str:
        if self.is_fresh():
            return self._token
        async with self._lock:
            if self.is_fresh():
                return self._token
            return await self._refresh_locked()

    async def force_refresh(self) -> str:
        async with self._lock:
            return await self._refresh_locked()

    async def _refresh_locked(self) -> str:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            response = await client.post(self.token_url(), params=self.token_params())
        response.raise_for_status()
        self._token = parse_access_token_payload(response.json())
        self._fetched_at = self.clock()
        return self._token


def extract_course_records(payload: dict[str, Any]) -> list[CourseRecord]:
    data = payload.get("data") or {}
    records = data.get("records") or []
    result = []
    for record in records:
        course_id = record.get("id")
        if course_id is None:
            continue
        result.append(
            CourseRecord(
                course_id=int(course_id),
                subject_name=str(record.get("subjName") or ""),
                begin_time=str(record.get("courBeginTime") or ""),
            )
        )
    return result


def extract_three_video_endpoints(payload: dict[str, Any]) -> list[VideoEndpoint] | None:
    items = payload.get("data") or []
    if len(items) != 3:
        return None
    endpoints = []
    for item in items:
        url = item.get("url")
        course_id = item.get("courId")
        if not url or course_id is None:
            return None
        view_num = item.get("viewNum")
        endpoints.append(VideoEndpoint(course_id=int(course_id), url=str(url), view_num=int(view_num) if view_num is not None else None))
    return endpoints


def extract_organizations(payload: dict[str, Any]) -> list[OrganizationItem]:
    result: list[OrganizationItem] = []

    def walk(items: list[dict[str, Any]], parents: list[str]) -> None:
        for item in items:
            orga_id = item.get("id")
            if orga_id is None:
                continue
            name = str(item.get("orgaName") or "")
            path_parts = [*parents, name] if name else parents
            parent_id = item.get("orgaParentId")
            result.append(
                OrganizationItem(
                    id=int(orga_id),
                    orga_name=name,
                    orga_level=int(item["orgaLevel"]) if item.get("orgaLevel") is not None else None,
                    parent_id=int(parent_id) if parent_id is not None else None,
                    path=" / ".join(path_parts),
                )
            )
            children = item.get("childs") or []
            if children:
                walk(children, path_parts)

    walk(payload.get("data") or [], [])
    return result


class PlatformClient:
    def __init__(self, settings: PlatformSettings, token_provider: PlatformTokenProvider | None = None):
        self.settings = settings
        self.token_provider = token_provider or PlatformTokenProvider(settings)

    def course_list_url(self) -> str:
        return self.settings.base_url + self.settings.course_list_path

    def vod_detail_url(self, course_id: int) -> str:
        path = self.settings.vod_detail_path_template.format(course_id=course_id)
        return self.settings.base_url + path

    def organizations_url(self) -> str:
        return self.settings.base_url + self.settings.organizations_path

    def course_list_params(self, page_index: int, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        filters = filters or {}
        params: dict[str, Any] = {
            "page.pageIndex": page_index,
            "page.pageSize": self.settings.page_size,
        }
        begin_time = filters.get("cour_begin_time") or self.settings.begin_time
        end_time = filters.get("cour_end_time") or self.settings.end_time
        orga_ids = filters.get("orga_ids")
        if orga_ids is None:
            orga_ids = self.settings.orga_ids
        if begin_time:
            params["courBeginTime"] = begin_time
        if end_time:
            params["courEndTime"] = end_time
        if orga_ids:
            params["orgaIds"] = ",".join(str(int(item)) for item in orga_ids)
        return params

    async def get_json(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = await self.build_headers()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=headers, params=params)
        if response.status_code in {401, 403}:
            headers = await self.build_headers(force_refresh=True)
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, headers=headers, params=params)
            if response.status_code in {401, 403}:
                raise AuthExpiredError("平台鉴权失败：刷新 token 后仍然失败")
        response.raise_for_status()
        return response.json()

    async def build_headers(self, *, force_refresh: bool = False) -> dict[str, str]:
        token = await self.token_provider.force_refresh() if force_refresh else await self.token_provider.get_token()
        return build_platform_headers(
            jwt_token=token,
            origin=self.settings.origin,
            referer=self.settings.referer,
            cookie=self.settings.cookie,
        )

    async def fetch_course_records(self, page_index: int, filters: dict[str, Any] | None = None) -> list[CourseRecord]:
        payload = await self.get_json(self.course_list_url(), params=self.course_list_params(page_index, filters=filters))
        return extract_course_records(payload)

    async def fetch_video_endpoints(self, course_id: int) -> list[VideoEndpoint] | None:
        payload = await self.get_json(self.vod_detail_url(course_id))
        return extract_three_video_endpoints(payload)

    async def fetch_organization_tree(self) -> list[dict[str, Any]]:
        payload = await self.get_json(self.organizations_url(), params={"isTreeResult": 1})
        return payload.get("data") or []

    async def fetch_organizations(self) -> list[OrganizationItem]:
        payload = await self.get_json(self.organizations_url(), params={"isTreeResult": 1})
        return extract_organizations(payload)
