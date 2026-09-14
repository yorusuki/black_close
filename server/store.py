"""極簡 JSON 檔案儲存層。

規模小（少數裝置/模組），刻意不用資料庫，減少 Pi 上的依賴與記憶體用量。
每個「集合」對應一個 JSON 檔案；每份文件（layout/scene）各自一個檔案。
用 threading.Lock 避免同進程內的寫入競爭；跨行程寫入採「先寫暫存檔再 rename」
確保讀到的檔案永遠是完整內容，不會讀到寫一半的資料。
"""

from __future__ import annotations
import json
import threading
from pathlib import Path
from typing import Any

from . import config

_LOCK = threading.Lock()


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with _LOCK:
        text = path.read_text(encoding="utf-8")
    return json.loads(text) if text.strip() else default


def write_json(path: Path, data: Any) -> None:
    _atomic_write(path, data)


# ---- devices ----
def devices_path() -> Path:
    return config.DATA_DIR / "devices.json"


def list_devices() -> list[dict]:
    return read_json(devices_path(), [])


def get_device(device_id: str) -> dict | None:
    for d in list_devices():
        if d["id"] == device_id:
            return d
    return None


def save_devices(devices: list[dict]) -> None:
    write_json(devices_path(), devices)


# ---- layouts ----
def layout_path(layout_id: str) -> Path:
    return config.DATA_DIR / "layouts" / f"{layout_id}.json"


def get_layout(layout_id: str) -> dict | None:
    return read_json(layout_path(layout_id))


def save_layout(layout_id: str, layout: dict) -> None:
    write_json(layout_path(layout_id), layout)


def list_layout_ids() -> list[str]:
    d = config.DATA_DIR / "layouts"
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


# ---- scenes（每個裝置一份，內含多個情境規則）----
def scenes_path(device_id: str) -> Path:
    return config.DATA_DIR / "scenes" / f"{device_id}.json"


def get_scenes(device_id: str) -> list[dict]:
    return read_json(scenes_path(device_id), [])


def save_scenes(device_id: str, scenes: list[dict]) -> None:
    write_json(scenes_path(device_id), scenes)


# ---- 國定假日清單（給情境判斷用）----
def holidays_path() -> Path:
    return config.DATA_DIR / "holidays_tw.json"


def get_holidays() -> list[str]:
    """回傳 YYYY-MM-DD 字串陣列（見 data/holidays_tw.json 的 "_note" 說明其侷限）。"""
    data = read_json(holidays_path(), {"dates": []})
    if isinstance(data, list):  # 相容純陣列格式
        return data
    return data.get("dates", [])
