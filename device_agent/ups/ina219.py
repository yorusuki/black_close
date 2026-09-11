"""INA219 電流/電壓感測晶片驅動。

改寫自 official/UPS_HAT_C/INA219.py（Waveshare UPS HAT (C) 官方範例），
邏輯與暫存器位址/校正參數維持不變，只是：
  1. 拿掉檔尾的 `__main__` demo（改放到 ups_daemon.py 的 Battery 類別）。
  2. import smbus 失敗時退回 smbus2（pip 可裝，apt 版 python3-smbus 有時不好裝）。
"""
from __future__ import annotations

try:
    import smbus
except ImportError:  # Raspberry Pi OS 上通常用 apt 裝 python3-smbus；
    import smbus2 as smbus  # 裝不到的話可以 pip install smbus2 --break-system-packages

_REG_CONFIG = 0x00
_REG_SHUNTVOLTAGE = 0x01
_REG_BUSVOLTAGE = 0x02
_REG_POWER = 0x03
_REG_CURRENT = 0x04
_REG_CALIBRATION = 0x05


class BusVoltageRange:
    RANGE_16V = 0x00
    RANGE_32V = 0x01


class Gain:
    DIV_1_40MV = 0x00
    DIV_2_80MV = 0x01
    DIV_4_160MV = 0x02
    DIV_8_320MV = 0x03


class ADCResolution:
    ADCRES_12BIT_32S = 0x0D


class Mode:
    SANDBVOLT_CONTINUOUS = 0x07


class INA219:
    """對應 Waveshare UPS HAT (C)：16V / 5A 量測範圍、0.01Ω 分流電阻校正值。"""

    def __init__(self, i2c_bus: int = 1, addr: int = 0x43):
        self.bus = smbus.SMBus(i2c_bus)
        self.addr = addr
        self._cal_value = 0
        self._current_lsb = 0.0
        self._power_lsb = 0.0
        self._set_calibration_16v_5a()

    def _read(self, address: int) -> int:
        data = self.bus.read_i2c_block_data(self.addr, address, 2)
        return (data[0] * 256) + data[1]

    def _write(self, address: int, data: int) -> None:
        temp = [(data & 0xFF00) >> 8, data & 0xFF]
        self.bus.write_i2c_block_data(self.addr, address, temp)

    def _set_calibration_16v_5a(self) -> None:
        # 官方範例的校正值，對應 16V/5A 量測範圍 + 0.01Ω 分流電阻，不建議自行更動
        # （細節推導見官方 INA219.py 內的註解）。
        self._current_lsb = 0.1524   # 100uA / bit
        self._cal_value = 26868
        self._power_lsb = 0.003048   # 2mW / bit
        self._write(_REG_CALIBRATION, self._cal_value)

        config = (
            BusVoltageRange.RANGE_16V << 13
            | Gain.DIV_2_80MV << 11
            | ADCResolution.ADCRES_12BIT_32S << 7
            | ADCResolution.ADCRES_12BIT_32S << 3
            | Mode.SANDBVOLT_CONTINUOUS
        )
        self._write(_REG_CONFIG, config)

    def get_shunt_voltage_mv(self) -> float:
        self._write(_REG_CALIBRATION, self._cal_value)
        value = self._read(_REG_SHUNTVOLTAGE)
        if value > 32767:
            value -= 65535
        return value * 0.01

    def get_bus_voltage_v(self) -> float:
        self._write(_REG_CALIBRATION, self._cal_value)
        self._read(_REG_BUSVOLTAGE)
        return (self._read(_REG_BUSVOLTAGE) >> 3) * 0.004

    def get_current_ma(self) -> float:
        value = self._read(_REG_CURRENT)
        if value > 32767:
            value -= 65535
        return value * self._current_lsb

    def get_power_w(self) -> float:
        self._write(_REG_CALIBRATION, self._cal_value)
        value = self._read(_REG_POWER)
        if value > 32767:
            value -= 65535
        return value * self._power_lsb
