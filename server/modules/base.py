"""所有模組的共同介面。

新增功能 = 在 server/modules/ 底下新增一個檔案，繼承 BaseModule 並在檔尾
`register()`（見 registry.py）。不需要修改任何核心程式或前端程式碼，
排版編輯器會自動從 /api/modules 讀到新模組並顯示在模組面板上。
"""
from __future__ import annotations

from PIL import Image


class BaseModule:
    module_id: str = "base"
    display_name: str = "Base"
    description: str = ""

    #: 畫布上預設寬高（px），使用者可自行拖曳調整
    default_size: tuple[int, int] = (120, 40)

    #: fetch_data() 最短間隔秒數（防止使用者設過於頻繁）。
    min_refresh_interval: int = 30

    #: 是否允許比裝置「整幅刷新」更頻繁地局部更新（例如動畫）。
    #: 只有裝置 profile 標示 partial_refresh=True 時，這個旗標才會真的生效；
    #: 在僅支援整幅刷新的裝置（如 Inky pHAT）上，即使模組要求動畫也只會
    #: 跟著裝置原本的整幅刷新頻率一起更新，不會額外觸發整幅刷新。
    supports_partial: bool = False

    #: 預設刷新政策。auto 依裝置能力決定；partial 盡量局刷；full 則只要此模組變動
    #: 就要求整幅刷新。layout element 可用同名欄位覆寫，讓排版者以用途決定政策。
    refresh_policy: str = "auto"

    #: True 表示每個 tick 都要重新呼叫 render()（例如吉祥物動畫用時鐘挑影格）。
    #: 仍然只有在 supports_partial 且裝置支援時才會真的觸發面板刷新。
    always_rerender: bool = False

    #: 給排版編輯器產生設定表單用的 JSON schema（簡化版，非完整 JSON Schema）。
    #: 每個欄位: {"key":..., "label":..., "type": "text"|"number"|"json", "default":...}
    config_schema: list[dict] = []

    def fetch_data(self, cfg: dict) -> dict:
        """抓資料（可含網路請求）。回傳的 dict 會被快取，依 refresh_interval 節流呼叫。"""
        return {}

    def render(self, data: dict, size: tuple[int, int], color_mode: str, cfg: dict) -> Image.Image:
        """純畫圖，不做 I/O。回傳 RGBA/RGB 的 PIL Image，尺寸需等於 size。"""
        raise NotImplementedError

    def manifest(self) -> dict:
        return {
            "module_id": self.module_id,
            "display_name": self.display_name,
            "description": self.description,
            "default_size": list(self.default_size),
            "min_refresh_interval": self.min_refresh_interval,
            "supports_partial": self.supports_partial,
            "refresh_policy": self.refresh_policy,
            "config_schema": self.config_schema,
        }
