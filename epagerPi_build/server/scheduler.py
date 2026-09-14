"""方案 A（all-in-one）用的本機排程迴圈：直接呼叫 compositor，同一個 Python 行程，
不經過網路，這是 Pi 上預設建議的跑法。

啟動：
    python -m server.scheduler --device phat-01
（run_pi.sh 會同時啟動這支跟 web app）

要切換成線上拆分模式（方案 B）時，這支就不需要在 Pi 上跑了，改跑
device_agent/agent.py 輪詢伺服器；渲染邏輯完全不用改。
"""
from __future__ import annotations

import argparse
import logging
import time

from . import store
from .render.compositor import render_device

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("server.scheduler")


def run(device_id: str, tick_seconds: float) -> None:
    from device_agent.drivers import build_driver  # 延後匯入：避免 web app 進場就載入硬體驅動

    profile = store.get_device(device_id)
    if profile is None:
        raise SystemExit(f"找不到裝置設定：{device_id}（請先在 data/devices.json 建立）")

    driver = build_driver(profile)
    log.info("排程器啟動：device=%s driver=%s tick=%ss", device_id, profile.get("driver"), tick_seconds)

    while True:
        try:
            image, meta = render_device(device_id)
            if meta["refresh_mode"] != "none":
                driver.show(image, mode=meta["refresh_mode"], dirty_boxes=meta["dirty_boxes"])
                log.info(
                    "刷新 %s：mode=%s scene=%s dirty=%d",
                    device_id, meta["refresh_mode"], meta["scene"], len(meta["dirty_boxes"]),
                )
        except Exception:
            log.exception("這次 tick 渲染/刷新失敗，略過並繼續下一輪（不讓單次錯誤中斷排程）")
        time.sleep(tick_seconds)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", required=True, help="裝置 id（對應 data/devices.json）")
    parser.add_argument("--tick-seconds", type=float, default=1.0)
    args = parser.parse_args()
    run(args.device, args.tick_seconds)


if __name__ == "__main__":
    main()
