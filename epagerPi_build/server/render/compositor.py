"""渲染引擎核心：layout JSON + 模組資料 → 合成畫面，並決定刷新方式。

刷新策略（對應架構文件第 3.2 節）：
  - 每個元素依自己的 refresh_interval 節流呼叫 fetch_data()（網路資料源省流量）。
  - render() 每個 tick 都可能被呼叫（畫圖成本低），用「元素畫出來的內容有沒有變」
    （雜湊比對）判斷該元素是否 dirty，藉此自動支援動畫模組（如吉祥物）而不用
    額外一套排程資料結構。
  - 裝置若不支援局部刷新：套用「最短整幅刷新間隔」節流，避免像動畫這種高頻變動
    去頻繁觸發整幅刷新（電子紙整幅刷新較傷面板、也比較慢）。
  - 裝置若支援局部刷新：正常局部刷新，但每 N 次局部刷新強制一次整幅刷新，
    避免電子紙局部刷新殘影持續累積。

這個模組刻意設計成「純函式 + 一組模組層級快取」，同一個 render_device() 呼叫
可以被 Flask API（線上/預覽用）跟本機排程器（Pi 端）共用。
"""
from __future__ import annotations

import datetime

from PIL import Image, ImageDraw

from .. import store
from ..modules.drawing import load_font
from ..modules.registry import get_module
from . import device_profiles, scenes

# 模組層級狀態快取（單一行程內有效；多工作行程部署時每個行程各自一份，
# 頂多讓 dirty-box 判斷偶爾多刷一次，不影響正確性）。
_fetch_cache: dict[tuple, dict] = {}
_last_element_state: dict[tuple, tuple] = {}
_last_full_refresh: dict[str, float] = {}
_partial_count_since_full: dict[str, int] = {}


def _error_placeholder(size, message: str) -> Image.Image:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, size[0] - 1, size[1] - 1], outline="black")
    font = load_font(12)
    draw.text((4, 4), f"[模組錯誤] {message[:60]}", fill="black", font=font)
    return img


def _render_elements(device_id: str, layout: dict, profile: dict, now: datetime.datetime):
    canvas = Image.new("RGB", tuple(profile["resolution"]), "white")
    dirty_boxes = []

    for el in layout.get("elements", []):
        module = get_module(el.get("module_id"))
        if module is None:
            continue

        instance_id = el.get("instance_id", el.get("module_id"))
        key = (device_id, instance_id)
        cfg = el.get("config", {})
        interval = max(el.get("refresh_interval", module.min_refresh_interval), module.min_refresh_interval if not module.always_rerender else 0)

        cache = _fetch_cache.get(key)
        need_fetch = (
            module.always_rerender
            or cache is None
            or (now.timestamp() - cache["ts"]) >= interval
        )
        if need_fetch:
            try:
                data = module.fetch_data(cfg)
            except Exception:
                data = cache["data"] if cache else {}
            _fetch_cache[key] = {"ts": now.timestamp(), "data": data}
        else:
            data = cache["data"]

        size = (int(el.get("w", module.default_size[0])), int(el.get("h", module.default_size[1])))
        try:
            element_img = module.render(data, size, profile.get("color_mode"), cfg)
            if element_img.size != size:
                element_img = element_img.resize(size)
        except Exception as exc:  # noqa: BLE001 - 單一模組壞掉不能拖垮整個裝置畫面
            element_img = _error_placeholder(size, repr(exc))

        x, y = int(el.get("x", 0)), int(el.get("y", 0))
        canvas.paste(element_img.convert("RGB"), (x, y))

        state_hash = hash(element_img.tobytes())
        prev = _last_element_state.get(key)
        box = [x, y, size[0], size[1]]
        if prev is None or prev[0] != state_hash:
            dirty_boxes.append(box)
        _last_element_state[key] = (state_hash, box)

    return canvas, dirty_boxes


def _decide_refresh_mode(device_id: str, profile: dict, dirty_boxes: list, now: datetime.datetime):
    if not dirty_boxes:
        return "none", []

    if not profile.get("partial_refresh", False):
        min_interval = profile.get("min_full_refresh_interval_seconds", 300)
        last = _last_full_refresh.get(device_id, 0)
        if now.timestamp() - last < min_interval:
            return "none", []
        _last_full_refresh[device_id] = now.timestamp()
        return "full", dirty_boxes

    force_every = profile.get("force_full_refresh_every", 20)
    count = _partial_count_since_full.get(device_id, 0)
    if count >= force_every:
        _partial_count_since_full[device_id] = 0
        _last_full_refresh[device_id] = now.timestamp()
        return "full", dirty_boxes

    _partial_count_since_full[device_id] = count + 1
    return "partial", dirty_boxes


def render_device(device_id: str, now: datetime.datetime | None = None):
    """回傳 (最終量化後的 PIL Image, meta dict)。"""
    now = now or datetime.datetime.now()
    profile = device_profiles.get_profile(device_id)
    if profile is None:
        raise ValueError(f"找不到裝置設定：{device_id}")

    layout_id = scenes.select_layout_id(device_id, now)
    layout = store.get_layout(layout_id) if layout_id else None
    if layout is None:
        layout = {"elements": []}

    canvas, dirty_boxes = _render_elements(device_id, layout, profile, now)
    final = device_profiles.quantize(canvas, profile)
    refresh_mode, out_boxes = _decide_refresh_mode(device_id, profile, dirty_boxes, now)

    meta = {
        "device_id": device_id,
        "layout_id": layout_id,
        "scene": scenes.active_scene_name(device_id, now),
        "refresh_mode": refresh_mode,
        "dirty_boxes": out_boxes,
        "rendered_at": now.isoformat(timespec="seconds"),
    }
    return final, meta
