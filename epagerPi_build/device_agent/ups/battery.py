"""電量讀取封裝：INA219 原始讀值 → 電量百分比，並把最新讀值寫進共用快取檔，
給網頁排版裡的「電量顯示」模組讀（不用重複開 I2C 連線）。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .ina219 import INA219

log = logging.getLogger("device_agent.ups.battery")


def voltage_to_percent(bus_voltage: float) -> float:
    """沿用 Waveshare UPS HAT (C) 官方範例的換算公式：3.0V=0%、4.2V=100%（線性）。"""
    percent = (bus_voltage - 3.0) / 1.2 * 100
    return max(0.0, min(100.0, percent))


class Battery:
    def __init__(self, i2c_address: int = 0x43, state_path: Path | None = None):
        self._ina = INA219(addr=i2c_address)
        self.state_path = state_path

    def read(self) -> dict:
        bus_voltage = self._ina.get_bus_voltage_v()
        current_ma = self._ina.get_current_ma()
        power_w = self._ina.get_power_w()
        reading = {
            "bus_voltage": round(bus_voltage, 3),
            "current_ma": round(current_ma, 1),
            "power_w": round(power_w, 3),
            "percent": round(voltage_to_percent(bus_voltage), 1),
            # 充放電方向依實際接線可能相反，這裡先假設「負電流=正在充電」，
            # 上機後如果方向相反，把這裡的 `< 0` 改成 `> 0` 即可。
            "charging": current_ma < 0,
            "read_at": time.time(),
        }
        if self.state_path:
            self._write_state(reading)
        return reading

    def _write_state(self, reading: dict) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(reading, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.state_path)
        except OSError:
            log.exception("寫入電量快取檔失敗（不影響量測本身，只是顯示模組會讀到舊資料）")
