"""硬體診斷小工具：依序嘗試初始化各驅動（Inky pHAT / 微雪 4.26" / UPS INA219），
回報哪一個能用、哪一個失敗（連同原始錯誤訊息），方便上機後快速確認接線/驅動安裝
狀況，不需要先設定 device_agent/config.yaml，也跟 layout/伺服器無關。

用法（在 repo 根目錄執行）：
    python -m device_agent.detect_hardware              # 只測初始化/讀值，不動螢幕
    python -m device_agent.detect_hardware --show        # 額外對能初始化成功的螢幕
                                                           # 推一張測試圖（會真的刷新面板）
    python -m device_agent.detect_hardware --only inky   # 只測其中一項
"""
from __future__ import annotations

import argparse
import logging

from PIL import Image, ImageDraw

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def _test_image(size, label: str) -> Image.Image:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, size[0] - 1, size[1] - 1], outline="black", width=2)
    draw.line([(0, 0), (size[0] - 1, size[1] - 1)], fill="black", width=1)
    draw.line([(0, size[1] - 1), (size[0] - 1, 0)], fill="black", width=1)
    draw.text((6, 6), label, fill="black")
    return img


def check_inky(show: bool) -> None:
    print('\n[Inky pHAT] 嘗試初始化...')
    try:
        from device_agent.drivers.inky_driver import InkyDriver
        driver = InkyDriver(colour="red")
    except Exception as exc:  # noqa: BLE001 - 診斷工具就是要把原始錯誤攤開給人看
        print(f"  x 失敗：{exc}")
        return
    print("  ok 初始化成功")
    if show:
        try:
            driver.show(_test_image((212, 104), "epagerPi OK"), mode="full")
            print("  ok 已推送測試圖（請看螢幕）")
        except Exception as exc:  # noqa: BLE001
            print(f"  x 推送測試圖失敗：{exc}")


def check_waveshare(show: bool) -> None:
    print('\n[微雪 4.26"] 嘗試初始化...')
    try:
        from device_agent.drivers.waveshare_driver import WaveshareDriver
        driver = WaveshareDriver(color_mode="1bit")
    except Exception as exc:  # noqa: BLE001
        print(f"  x 失敗：{exc}")
        return
    print("  ok 初始化成功（提醒：device_agent/vendor/epd4in26.py 是重新猜寫的，"
          "不是官方檔案，command 序列還沒有實體面板驗證過，畫面沒反應/亂碼請先看那支檔案）")
    if show:
        try:
            driver.show(_test_image((800, 480), "epagerPi OK"), mode="full")
            print("  ok 已推送測試圖（請看螢幕）")
        except Exception as exc:  # noqa: BLE001
            print(f"  x 推送測試圖失敗：{exc}")


def check_ups() -> None:
    print("\n[UPS HAT (C) / INA219] 嘗試讀取電量...")
    try:
        from device_agent.ups.battery import Battery
        battery = Battery()
        reading = battery.read()
    except Exception as exc:  # noqa: BLE001
        print(f"  x 失敗：{exc}")
        return
    print(
        f"  ok 讀取成功：{reading['percent']}%（{reading['bus_voltage']}V, "
        f"{reading['current_ma']}mA, {'充電中' if reading['charging'] else '放電中'}）"
    )
    print("  提醒：charging 方向是假設值（current_ma < 0 = 充電中），如果實際接線相反，"
          "改 device_agent/ups/battery.py 那行的判斷式")


def main() -> None:
    parser = argparse.ArgumentParser(description="epagerPi 硬體診斷工具")
    parser.add_argument("--show", action="store_true",
                         help="連同推送一張測試圖到能初始化成功的螢幕（會真的刷新面板）")
    parser.add_argument("--only", choices=["inky", "waveshare", "ups"], help="只測其中一項")
    args = parser.parse_args()

    print("epagerPi 硬體診斷工具 —— 只測「能不能初始化/讀到值」，不代表畫面或電量數字一定正確。")

    if args.only in (None, "inky"):
        check_inky(args.show)
    if args.only in (None, "waveshare"):
        check_waveshare(args.show)
    if args.only in (None, "ups"):
        check_ups()

    print("\n完成。")


if __name__ == "__main__":
    main()
