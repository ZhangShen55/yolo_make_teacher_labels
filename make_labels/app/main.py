from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field
import uvicorn

from .config import Settings, load_settings
from .job_manager import JobManager
from .logging_utils import configure_logging
from .pipeline import LabelPipeline
from .platform_client import PlatformClient
from .preflight import PreflightRunner


logger = logging.getLogger(__name__)


class JobStartRequest(BaseModel):
    start_page: int | None = Field(default=None, ge=1)
    max_pages: int | None = Field(default=None, ge=1)
    cour_begin_time: str | None = None
    cour_end_time: str | None = None
    orga_ids: list[int] | None = None


def build_runner_factory(
    settings_holder: dict[str, Settings | None],
    *,
    config_path: Path | None = None,
    pipeline_class: type[LabelPipeline] = LabelPipeline,
):
    if settings_holder.get("settings") is None and config_path is None:
        return None

    async def run(status, options: dict[str, Any]):
        active_settings = settings_holder.get("settings")
        if config_path is not None:
            active_settings = load_settings(config_path)
            settings_holder["settings"] = active_settings
        if active_settings is None:
            return
        course_filters = {
            key: options[key]
            for key in ["cour_begin_time", "cour_end_time", "orga_ids"]
            if key in options
        }
        await pipeline_class(active_settings, status).run(
            start_page=options.get("start_page"),
            max_pages=options.get("max_pages"),
            course_filters=course_filters,
        )

    return run


def create_app(
    settings: Settings | None = None,
    *,
    config_path: str | Path | None = None,
    pipeline_class: type[LabelPipeline] = LabelPipeline,
    platform_client_class: type[PlatformClient] = PlatformClient,
    preflight_runner_class: type[PreflightRunner] = PreflightRunner,
    run_startup_preflight: bool = False,
) -> FastAPI:
    resolved_config_path = Path(config_path).expanduser().resolve() if config_path is not None else None
    settings_holder = {"settings": settings}
    runner_factory = build_runner_factory(
        settings_holder,
        config_path=resolved_config_path,
        pipeline_class=pipeline_class,
    )
    manager = JobManager(runner_factory=runner_factory)
    app = FastAPI(title="Make Label Service")

    def current_settings(refresh: bool = False) -> Settings | None:
        if refresh and resolved_config_path is not None:
            settings_holder["settings"] = load_settings(resolved_config_path)
        return settings_holder["settings"]

    async def run_startup_checks() -> None:
        if not run_startup_preflight:
            return
        logger.info("开始启动自检")
        try:
            await run_preflight()
            logger.info("启动自检完成 ok=%s checks=%s", app.state.preflight.get("ok"), app.state.preflight.get("checks"))
        except Exception as exc:  # noqa: BLE001
            app.state.preflight = {"ok": False, "checks": [], "status": "error", "detail": str(exc)}
            logger.exception("启动自检失败")

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        await run_startup_checks()
        yield

    app.router.lifespan_context = lifespan
    app.state.job_manager = manager
    app.state.settings_holder = settings_holder
    app.state.preflight = {"ok": None, "checks": [], "status": "not_run"}

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/config")
    def config_summary():
        settings = current_settings(refresh=True)
        if settings is None:
            return {"loaded": False}
        return {
            "loaded": True,
            "platform_base_url": settings.platform.base_url,
            "output_root": str(settings.dataset.output_root),
            "batch_size": settings.dataset.batch_size,
            "capture_workers": settings.video.capture_workers,
            "capture_jitter_seconds": settings.video.capture_jitter_seconds,
            "detect_workers": settings.algorithm_8881.detect_workers,
            "vlm_workers": settings.vlm.workers,
            "platform_auth_loaded": bool(settings.platform.auth.username and settings.platform.auth.client_id),
        }

    @app.get("/api/platform/organizations")
    async def list_organizations():
        settings = current_settings(refresh=True)
        if settings is None:
            return {"items": []}
        items = await platform_client_class(settings.platform).fetch_organizations()
        return {"items": [item.__dict__ for item in items]}

    @app.get("/api/platform/organizations/tree")
    async def organization_tree():
        settings = current_settings(refresh=True)
        if settings is None:
            return {"items": []}
        return {"items": await platform_client_class(settings.platform).fetch_organization_tree()}

    @app.get("/api/preflight")
    def get_preflight():
        return app.state.preflight

    @app.post("/api/preflight/run")
    async def run_preflight():
        settings = current_settings(refresh=True)
        if settings is None:
            app.state.preflight = {"ok": False, "checks": [], "status": "config_not_loaded"}
            return app.state.preflight
        app.state.preflight = await preflight_runner_class(settings).run()
        app.state.preflight["status"] = "complete"
        return app.state.preflight

    @app.get("/api/jobs/status")
    def job_status():
        return manager.as_dict()

    @app.post("/api/jobs/start")
    async def start_job(payload: JobStartRequest | None = None):
        options = payload.model_dump(exclude_none=True) if payload is not None else {}
        return await manager.start(options)

    @app.post("/api/jobs/stop")
    async def stop_job():
        return await manager.stop()

    @app.get("/api/batches")
    def list_batches():
        settings = current_settings(refresh=True)
        if settings is None or not settings.dataset.output_root.exists():
            return {"items": []}
        batches = []
        for path in sorted(settings.dataset.output_root.glob(f"{settings.dataset.batch_prefix}*")):
            if not path.is_dir():
                continue
            images_dir = path / "images"
            labels_dir = path / "labels"
            batches.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "images": len(list(images_dir.glob("*"))) if images_dir.exists() else 0,
                    "labels": len(list(labels_dir.glob("*.txt"))) if labels_dir.exists() else 0,
                }
            )
        return {"items": batches}

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.toml", help="Path to config.toml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    configure_logging()
    config_path = Path(args.config).expanduser().resolve()
    settings = load_settings(config_path)
    uvicorn.run(create_app(settings, config_path=config_path, run_startup_preflight=True), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
