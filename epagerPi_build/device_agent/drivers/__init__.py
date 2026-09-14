"""依裝置 profile 的 driver 欄位組出對應的驅動實例。"""
from __future__ import annotations

from .base import BaseDisplayDriver
from .mock_driver import MockDriver


def build_driver(profile: dict) -> BaseDisplayDriver:
    driver_name = profile.get("driver")

    if driver_name == "inky_phat":
        from .inky_driver import InkyDriver
        return InkyDriver(colour=profile.get("accent_color", "red"))

    if driver_name == "waveshare_4in26":
        from .waveshare_driver import WaveshareDriver
        return WaveshareDriver(color_mode=profile.get("color_mode", "1bit"))

    if driver_name == "mock":
        from .. import config as agent_config
        return MockDriver(agent_config.PREVIEW_PATH.format(device_id=profile["id"]))

    raise ValueError(f"不認識的 driver：{driver_name}")
