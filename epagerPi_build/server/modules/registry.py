"""模組自動註冊表。

新增模組只需要在本目錄新增檔案、繼承 BaseModule，並把 class 加進下面的
_MODULE_CLASSES 清單即可（Python 不像有些語言能單靠「檔案存在」自動掃描，
但這裡刻意保持「加一行」而非動核心邏輯，仍然符合「新增功能不改核心架構」的精神：
新模組的畫圖/資料邏輯完全獨立在自己的檔案裡）。
"""
from __future__ import annotations

from .clock_bar import ClockBarModule
from .mascot import MascotModule
from .progress_bar import ProgressBarModule
from .stat_pair import StatPairModule

_MODULE_CLASSES = [
    ClockBarModule,
    ProgressBarModule,
    StatPairModule,
    MascotModule,
]

MODULES: dict[str, "BaseModule"] = {cls.module_id: cls() for cls in _MODULE_CLASSES}


def get_module(module_id: str):
    return MODULES.get(module_id)


def list_manifests() -> list[dict]:
    return [m.manifest() for m in MODULES.values()]
