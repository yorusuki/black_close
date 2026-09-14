"""Pimoroni Inky pHAT / wHAT 驅動包裝層。

不搬 official/inky-main 整包程式碼，直接吃 pip 裝的 `inky` 套件（`pip install inky`）。
Inky 官方驅動的 show() 只有整幅刷新，沒有局部刷新，所以這裡固定整幅刷新，
mode="partial" 的請求會被忽略並記一筆 log（正常情況下 compositor 對這種
device profile 本來就只會要求 full，這裡只是防呆）。
"""
from __future__ import annotations

import logging

from PIL import Image

from .base import BaseDisplayDriver

log = logging.getLogger("device_agent.inky_driver")


class InkyDriver(BaseDisplayDriver):
    def __init__(self, colour: str = "red", variant: str = "phat"):
        """
        :param colour: 'red' / 'yellow' / 'black'（對應面板上實際印刷的第三色）
        :param variant: 目前只接 'phat'（2.13" Inky pHAT）；wHAT 需要時可仿照擴充
        """
        if variant != "phat":
            raise ValueError(f"目前 InkyDriver 只支援 variant='phat'，收到：{variant}")

        try:
            from inky import InkyPHAT
            self._display = InkyPHAT(colour)
        except Exception as exc:  # noqa: BLE001 - 非 Pi 機器上會在匯入或初始化階段失敗
            raise RuntimeError(
                "無法初始化 Inky pHAT。請確認：(1) 在真正的 Raspberry Pi 上執行、"
                "(2) 已安裝 inky 套件（pip install inky --break-system-packages）、"
                "(3) 已啟用 SPI/I2C（raspi-config）。"
                f" 原始錯誤：{exc!r}"
            ) from exc

    def show(self, image: Image.Image, mode: str = "full", dirty_boxes: list | None = None) -> None:
        if mode == "partial":
            log.warning("Inky pHAT 官方驅動不支援局部刷新，改用整幅刷新")
        self._display.set_image(image)
        self._display.show()
