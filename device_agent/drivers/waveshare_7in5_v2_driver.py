"""Waveshare 7.5 吋 e-Paper HAT V2（800×480、黑白）驅動包裝。

底層使用官方 ``ep_python`` 的 ``epd7in5_V2.py`` 與範例
``epd_7in5_V2_test.py`` 相同的初始化／輸出 API。請勿把 640×384 的舊
``epd7in5.py`` 套用到本型號；兩者控制器與解析度不同。

官方 V2 範例提供 ``init_part()`` 和 ``display_Partial()``。本系統先以
全畫面 partial buffer 呼叫它，讓 compositor 的一般內容變動走局刷波形；
結構變動與保護全刷仍由 compositor 指定 ``full``。
"""
from __future__ import annotations

import logging

from PIL import Image

from .base import BaseDisplayDriver

log = logging.getLogger("device_agent.waveshare_7in5_v2_driver")


class Waveshare7In5V2Driver(BaseDisplayDriver):
    """以官方 V2 黑白 API 顯示 800×480 畫面。"""

    width = 800
    height = 480

    def __init__(self):
        try:
            from device_agent.vendor.epd7in5_V2 import EPD
        except Exception as exc:  # noqa: BLE001 - hardware import may fail before driver creation
            raise RuntimeError(
                "無法載入 Waveshare 7.5 吋 V2 驅動（device_agent/vendor/epd7in5_V2.py）。"
                "此型號需在真正 Raspberry Pi 啟用 SPI 後執行，並需要 gpiozero、spidev 與系統 python3-lgpio。"
                f" 原始錯誤：{exc!r}"
            ) from exc
        self._epd = EPD()
        self._mode: str | None = None

    def _buffer(self, image: Image.Image):
        if image.size != (self.width, self.height):
            raise ValueError(f"7.5 吋 V2 只接受 {self.width}×{self.height} 畫面，收到 {image.size[0]}×{image.size[1]}")
        return self._epd.getbuffer(image)

    def show(self, image: Image.Image, mode: str = "full", dirty_boxes: list | None = None) -> None:
        buffer = self._buffer(image)
        if mode == "partial":
            if self._mode != "partial":
                self._epd.init_part()
                self._mode = "partial"
            # 官方範例也是將完整 800×480 buffer 傳入 partial API；此面板的
            # 局刷波形與全刷不同，座標區域最佳化則保留給日後實機驗證。
            self._epd.display_Partial(buffer, 0, 0, self.width, self.height)
            return

        if self._mode != "full":
            self._epd.init()
            self._mode = "full"
        self._epd.display(buffer)

    def sleep(self) -> None:
        self._epd.sleep()
