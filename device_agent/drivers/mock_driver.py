"""沒有實體硬體時用的假驅動：把畫面存成 PNG，方便在開發機/沒接螢幕的 Pi 上測試整條流程。"""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from .base import BaseDisplayDriver

log = logging.getLogger("device_agent.mock_driver")


class MockDriver(BaseDisplayDriver):
    def __init__(self, output_path: str | Path):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def show(self, image: Image.Image, mode: str = "full", dirty_boxes: list | None = None) -> None:
        image.save(self.output_path)
        log.info("MockDriver: 寫出 %s（mode=%s, dirty=%s）", self.output_path, mode, dirty_boxes)
