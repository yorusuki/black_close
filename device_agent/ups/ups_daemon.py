"""UPS 電量看門狗：獨立跑（建議用 systemd，見 systemd/epagerpi-ups.service）。

規則：電量 < shutdown_threshold_percent，且「連續 shutdown_confirm_reads 次」都
低於門檻，才觸發關機 —— 避免單次讀值雜訊誤判導致不必要的關機。
"""
from __future__ import annotations

import logging
import subprocess
import time

from .. import config as agent_config
from .battery import Battery

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("device_agent.ups_daemon")


def run() -> None:
    cfg = agent_config.load_config()
    ups_cfg = cfg.get("ups", {})
    if not ups_cfg.get("enabled", True):
        log.info("UPS 監控已在設定檔關閉，daemon 直接結束")
        return

    battery = Battery(
        i2c_address=ups_cfg.get("i2c_address", 0x43),
        state_path=agent_config.BATTERY_STATE_PATH,
    )
    threshold = ups_cfg.get("shutdown_threshold_percent", 35)
    confirm_reads = ups_cfg.get("shutdown_confirm_reads", 3)
    poll_interval = ups_cfg.get("poll_interval_seconds", 30)

    low_streak = 0
    log.info("UPS daemon 啟動：threshold=%s%% confirm=%d次 poll=%ss", threshold, confirm_reads, poll_interval)

    while True:
        try:
            reading = battery.read()
            log.info(
                "電量 %.1f%%（%.2fV, %.1fmA, %s）",
                reading["percent"], reading["bus_voltage"], reading["current_ma"],
                "充電中" if reading["charging"] else "放電中",
            )
            if reading["percent"] < threshold:
                low_streak += 1
                log.warning("電量低於門檻 %s%%（第 %d/%d 次確認）", threshold, low_streak, confirm_reads)
                if low_streak >= confirm_reads:
                    log.critical("已連續 %d 次低於門檻，執行關機", low_streak)
                    subprocess.run(["systemctl", "poweroff"], check=False)
                    return
            else:
                low_streak = 0
        except Exception:
            log.exception("讀取電量失敗，等下一輪重試（不因單次讀取失敗就關機）")

        time.sleep(poll_interval)


if __name__ == "__main__":
    run()
