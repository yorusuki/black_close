"""微雪 4.26" 驅動包裝層。

只搬 official/ep_python 裡的 epd4in26.py + epdconfig.py 兩支檔案到
device_agent/vendor/（其餘 60 幾種面板的驅動不需要），這裡再包一層統一介面。

灰階對齊注意：4gray 模式一定要搭配 server 端 device_profiles.py 產生的
0x00/0x80/0xC0/0xFF 四階（不是均分的 0/85/170/255），否則
epd4in26.getbuffer_4Gray() 的分組邏輯會算錯，見該檔案註解。

局部刷新（display_Partial）目前只在 1bit 模式驗證過官方範例支援；
4Gray 模式下沒有局部刷新，這裡直接退回整幅刷新並記 log，不會報錯中斷。
"""
from __future__ import annotations

import logging

from PIL import Image

from .base import BaseDisplayDriver

log = logging.getLogger("device_agent.waveshare_driver")


class WaveshareDriver(BaseDisplayDriver):
    def __init__(self, panel: str = "4in26", color_mode: str = "1bit"):
        if panel != "4in26":
            raise ValueError(f"目前 WaveshareDriver 只支援 panel='4in26'，收到：{panel}")
        try:
            from device_agent.vendor.epd4in26 import EPD
        except Exception as exc:  # noqa: BLE001 - 在非 Pi 機器上 import 會直接失敗，訊息要清楚
            raise RuntimeError(
                "無法載入微雪驅動（device_agent/vendor/epd4in26.py + epdconfig.py）。"
                "這支驅動只能在真正的 Raspberry Pi 上執行（epdconfig.py 會偵測硬體），"
                "並需要先安裝：pip install gpiozero spidev --break-system-packages。"
                f" 原始錯誤：{exc!r}"
            ) from exc

        self._epd = EPD()
        self.color_mode = color_mode
        self._mode: str | None = None  # None | "base" | "4gray"

    def show(self, image: Image.Image, mode: str = "full", dirty_boxes: list | None = None) -> None:
        if self.color_mode == "4gray":
            if mode == "partial":
                log.warning("4 階灰階模式沒有局部刷新，改整幅刷新")
            if self._mode != "4gray":
                self._epd.init_4GRAY()
                self._mode = "4gray"
            buf = self._epd.getbuffer_4Gray(image)
            self._epd.display_4Gray(buf)
            return

        # 1bit 黑白
        if mode == "partial":
            if self._mode is None:
                self._epd.init()
                self._epd.Clear()
            self._mode = "base"
            buf = self._epd.getbuffer(image)
            self._epd.display_Partial(buf)
        else:
            if self._mode != "base":
                self._epd.init()
                self._mode = "base"
            buf = self._epd.getbuffer(image)
            self._epd.display(buf)

    def sleep(self) -> None:
        self._epd.sleep()
