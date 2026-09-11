"""螢幕驅動的共同介面。所有實際硬體驅動（Inky / 微雪）都包成這個形狀，
讓 agent.py / scheduler.py 不用知道底層是哪塊面板。
"""
from __future__ import annotations

from PIL import Image


class BaseDisplayDriver:
    def show(self, image: Image.Image, mode: str = "full", dirty_boxes: list | None = None) -> None:
        """把畫面推到面板。

        mode: "full" 整幅刷新 / "partial" 局部刷新（面板若不支援，驅動內部應自行
              退回整幅刷新，而不是報錯 —— 這個容錯留在各驅動實作內）。
        dirty_boxes: [[x,y,w,h], ...]，mode="partial" 時才有意義。
        """
        raise NotImplementedError

    def sleep(self) -> None:
        """低耗電休眠（多數面板支援），沒有的話留空實作即可。"""

    def close(self) -> None:
        """釋放 SPI/GPIO 資源。"""
