from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from .config import Settings
from .detector import TeacherDetectClient
from .platform_client import PlatformClient
from .vlm_labeler import ArkVlmClient


class PreflightRunner:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def run(self) -> dict[str, Any]:
        checks = [
            await self.check_command("ffmpeg"),
            await self.check_command("ffprobe"),
            await self.check_output_root(),
            await self.check_platform_auth(),
            await self.check_8881(),
            await self.check_vlm(),
        ]
        return {"ok": all(item["ok"] for item in checks), "checks": checks}

    async def check_command(self, command: str) -> dict[str, Any]:
        path = shutil.which(command)
        return {
            "name": command,
            "ok": bool(path),
            "detail": path or f"{command} not found in PATH",
        }

    async def check_output_root(self) -> dict[str, Any]:
        try:
            self.settings.dataset.output_root.mkdir(parents=True, exist_ok=True)
            probe = self.settings.dataset.output_root / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return {"name": "output_root", "ok": True, "detail": str(self.settings.dataset.output_root)}
        except Exception as exc:  # noqa: BLE001
            return {"name": "output_root", "ok": False, "detail": str(exc)}

    async def check_platform_auth(self) -> dict[str, Any]:
        try:
            items = await PlatformClient(self.settings.platform).fetch_organization_tree()
            return {"name": "platform_auth", "ok": True, "detail": f"organizations={len(items)}"}
        except Exception as exc:  # noqa: BLE001
            return {"name": "platform_auth", "ok": False, "detail": str(exc)}

    async def check_8881(self) -> dict[str, Any]:
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                image_path = Path(tmp_dir) / "preflight.jpg"
                Image.new("RGB", (32, 32), "white").save(image_path)
                await TeacherDetectClient(
                    self.settings.algorithm_8881.teacher_detect_url,
                    timeout_seconds=self.settings.algorithm_8881.timeout_seconds,
                ).detect_image(str(image_path), image_id="preflight")
            return {"name": "algorithm_8881", "ok": True, "detail": "teacher detect reachable"}
        except Exception as exc:  # noqa: BLE001
            return {"name": "algorithm_8881", "ok": False, "detail": str(exc)}

    async def check_vlm(self) -> dict[str, Any]:
        client = ArkVlmClient(
            self.settings.vlm.api_url,
            api_key=self.settings.vlm.api_key,
            model=self.settings.vlm.model,
            timeout_seconds=self.settings.vlm.timeout_seconds,
        )
        try:
            await client.ask_images([], "请只回复 ok")
            return {"name": "vlm", "ok": True, "detail": self.settings.vlm.model}
        except Exception as exc:  # noqa: BLE001
            return {"name": "vlm", "ok": False, "detail": str(exc)}
        finally:
            await client.close()
