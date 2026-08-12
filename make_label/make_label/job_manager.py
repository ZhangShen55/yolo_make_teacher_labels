from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from .models import JobStatus


def format_exception_message(exc: BaseException) -> str:
    text = str(exc).strip()
    name = exc.__class__.__name__
    return f"{name}: {text}" if text else name


class JobManager:
    def __init__(self, runner_factory: Callable[[JobStatus, dict[str, Any]], Awaitable[None]] | None = None):
        self.status = JobStatus()
        self.runner_factory = runner_factory
        self.task: asyncio.Task | None = None
        self.options: dict[str, Any] = {}

    async def start(self, options: dict[str, Any] | None = None) -> dict:
        if self.status.running:
            return self.status.as_dict()
        self.options = options or {}
        self.status.requested_start_page = self.options.get("start_page")
        self.status.requested_max_pages = self.options.get("max_pages")
        self.status.requested_cour_begin_time = self.options.get("cour_begin_time")
        self.status.requested_cour_end_time = self.options.get("cour_end_time")
        self.status.requested_orga_ids = self.options.get("orga_ids")
        self.status.running = True
        self.status.stop_requested = False
        if self.runner_factory is not None:
            self.task = asyncio.create_task(self._run())
        return self.status.as_dict()

    async def _run(self) -> None:
        try:
            assert self.runner_factory is not None
            await self.runner_factory(self.status, self.options)
        except Exception as exc:  # noqa: BLE001 - keep service alive and expose the error.
            self.status.add_error(format_exception_message(exc))
        finally:
            self.status.running = False

    async def stop(self) -> dict:
        self.status.stop_requested = True
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.status.running = False
        return self.status.as_dict()

    def as_dict(self) -> dict:
        return self.status.as_dict()
