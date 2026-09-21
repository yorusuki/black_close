"""渲染引擎核心：layout JSON + 模組資料 → 合成畫面，並決定刷新方式。

刷新策略（對應架構文件第 3.2 節）：
  - 每個元素依自己的 refresh_interval 節流呼叫 fetch_data()（網路資料源省流量）。
  - render() 每個 tick 都可能被呼叫（畫圖成本低），用「元素畫出來的內容有沒有變」
    （雜湊比對）判斷該元素是否 dirty，藉此自動支援動畫模組（如吉祥物）而不用
    額外一套排程資料結構。
  - 裝置若不支援局部刷新：套用「最短整幅刷新間隔」節流，避免像動畫這種高頻變動
    去頻繁觸發整幅刷新（電子紙整幅刷新較傷面板、也比較慢）。
  - 裝置若支援局部刷新：一般變動局刷；首次輸出、版面切換與模組明確指定時整幅刷新，
    並在可設定的間隔或每日指定時間（微雪預設每天 12:00）全刷，避免殘影累積。

這個模組拆成兩段（對應 docs/IMPLEMENTATION_NOTES.md「拆分模式改成樹莓派本機渲染」）：

  resolve_layout_elements()：挑 layout、只解析各元素「要打網路的」資料（http 型別，
      依 refresh_interval 節流快取），回傳的 dict 完全可以 JSON 序列化，可以在雲端
      算（線上拆分模式的 /api/devices/<id>/layout-data 端點就是回傳這個）。

  render_from_elements()：畫圖＋雜湊比對 dirty 區塊＋整幅/局部刷新節流，純本機運算，
      一定要在驅動螢幕的那台機器上跑 —— 「本地就能算」的資料型別（manual/battery/
      time_until/time_progress）也是在這一步、在模組的 render() 當下才真的解析，
      不受 resolve_layout_elements() 的節流快取影響，倒數計時/生存進度條這類東西
      才能保持即時感，不用等到下次網路輪詢。

  render_device()：兩段的合併版，all-in-one 模式（server/scheduler.py）跟
      /frame.png、/frame-meta 端點都是呼叫這支，行為跟拆分前完全一樣；
      device_agent/agent.py（拆分模式）改成定期呼叫 resolve_layout_elements()
      拿 layout-data，然後自己用更短的 tick 頻率重複呼叫 render_from_elements()。
"""
from __future__ import annotations

import datetime
import hashlib
import json

from PIL import Image, ImageDraw

from .. import config, store
from ..modules.drawing import load_font
from ..modules.registry import get_module
from . import device_profiles, scenes

# 模組層級狀態快取（單一行程內有效；多工作行程部署時每個行程各自一份，
# 頂多讓 dirty-box 判斷偶爾多刷一次，不影響正確性）。
_fetch_cache: dict[tuple, dict] = {}
_last_element_state: dict[tuple, tuple] = {}
_last_full_refresh: dict[str, float] = {}
_last_partial_refresh: dict[str, float] = {}
_last_scheduled_full_day: dict[str, datetime.date] = {}
_partial_count_since_full: dict[str, int] = {}
_last_layout_signature: dict[str, str] = {}


def reset_device_render_state(device_id: str) -> None:
    """清除單台面板的刷新歷史，讓靜默時段結束後下一張畫面必定全刷。"""
    _last_full_refresh.pop(device_id, None)
    _last_partial_refresh.pop(device_id, None)
    _last_scheduled_full_day.pop(device_id, None)
    _partial_count_since_full.pop(device_id, None)
    _last_layout_signature.pop(device_id, None)


def _error_placeholder(size, message: str) -> Image.Image:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, size[0] - 1, size[1] - 1], outline="black")
    font = load_font(12)
    draw.text((4, 4), f"[模組錯誤] {message[:60]}", fill="black", font=font)
    return img


def resolve_layout_elements(device_id: str, now: datetime.datetime | None = None) -> dict:
    """選 layout，只解析每個元素「要打網路的」資料（節流快取）。

    回傳結果完全可以 JSON 序列化，給 /api/devices/<id>/layout-data 端點、以及
    render_device() 自己共用。"""
    now = now or config.now_local()
    profile = device_profiles.get_profile(device_id)
    if profile is None:
        raise ValueError(f"找不到裝置設定：{device_id}")

    layout_id = scenes.select_layout_id(device_id, now)
    layout = store.get_layout(layout_id) if layout_id else None
    if layout is None:
        layout = {"elements": []}

    elements_out = []
    for el in layout.get("elements", []):
        module = get_module(el.get("module_id"))
        if module is None:
            continue

        instance_id = el.get("instance_id", el.get("module_id"))
        key = (device_id, instance_id)
        cfg = el.get("config", {})
        interval = max(
            el.get("refresh_interval", module.min_refresh_interval),
            module.min_refresh_interval if not module.always_rerender else 0,
        )

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

        elements_out.append({
            "instance_id": instance_id,
            "module_id": el.get("module_id"),
            "x": int(el.get("x", 0)),
            "y": int(el.get("y", 0)),
            "w": int(el.get("w", module.default_size[0])),
            "h": int(el.get("h", module.default_size[1])),
            "z": el.get("z", 0),
            "config": cfg,
            "data": data,
            "refresh_policy": el.get("refresh_policy", module.refresh_policy),
        })

    return {
        "device_id": device_id,
        "profile": profile,
        "layout_id": layout_id,
        "scene": scenes.active_scene_name(device_id, now),
        "elements": elements_out,
        "resolved_at": now.isoformat(timespec="seconds"),
    }


def _decide_refresh_mode(
    device_id: str,
    profile: dict,
    dirty_boxes: list,
    dirty_policies: set[str],
    now: datetime.datetime,
    *,
    layout_changed: bool,
):
    canvas_box = [[0, 0, int(profile["resolution"][0]), int(profile["resolution"][1])]]
    # 每日排程要在斷網、靜態頁面也能成立：Pi 本機 tick 會持續呼叫這裡，
    # 不依賴 Server 再送新的 layout。設定由 Server profile 下發，未來只改 Server。
    daily_at = profile.get("full_refresh_daily_at")
    if profile.get("partial_refresh", False) and isinstance(daily_at, str) and len(daily_at) == 5:
        try:
            scheduled_time = datetime.time.fromisoformat(daily_at)
        except ValueError:
            scheduled_time = None
        if scheduled_time and now.time() >= scheduled_time and _last_scheduled_full_day.get(device_id) != now.date():
            _last_scheduled_full_day[device_id] = now.date()
            _partial_count_since_full[device_id] = 0
            _last_full_refresh[device_id] = now.timestamp()
            return "full", canvas_box

    # 即使畫面內容沒有變化，也在設定的保護週期做一次全刷。這讓離線的靜態頁
    # 不會永久缺少全刷；一般時間仍只有 dirty 元件才局刷。
    if not dirty_boxes:
        if profile.get("partial_refresh", False):
            full_interval = max(600, min(86_400, int(profile.get("full_refresh_interval_seconds", 1200))))
            last_full = _last_full_refresh.get(device_id)
            if last_full is not None and now.timestamp() - last_full >= full_interval:
                _partial_count_since_full[device_id] = 0
                _last_full_refresh[device_id] = now.timestamp()
                return "full", canvas_box
        return "none", []

    # 第一次輸出、切換場景／layout、或有模組明確要求時，一律整幅刷新。這可避免
    # 移除元件後舊像素殘留，也讓「下班／週末」切到靜態頁面時畫面狀態確定一致。
    if layout_changed or "full" in dirty_policies:
        _partial_count_since_full[device_id] = 0
        _last_full_refresh[device_id] = now.timestamp()
        return "full", dirty_boxes

    if not profile.get("partial_refresh", False):
        min_interval = profile.get("min_full_refresh_interval_seconds", 300)
        last = _last_full_refresh.get(device_id, 0)
        if now.timestamp() - last < min_interval:
            return "none", []
        _last_full_refresh[device_id] = now.timestamp()
        return "full", dirty_boxes

    # 不再以「局刷 N 次」強制全刷；改為固定時間窗口。局刷次數仍保留在 meta，方便
    # 實機測試殘影是否與次數相關。靜態頁的到期情形在上方提前處理。
    full_interval = max(600, min(86_400, int(profile.get("full_refresh_interval_seconds", 1200))))
    last_full = _last_full_refresh.get(device_id)
    if last_full is None or now.timestamp() - last_full >= full_interval:
        _partial_count_since_full[device_id] = 0
        _last_full_refresh[device_id] = now.timestamp()
        return "full", dirty_boxes

    # 這是最後一道硬體保護：Server/UI 設定、動畫模組、倒數與直接 API 寫入
    # 都不能讓實際 partial 輸出快過型號指定的安全下限。注意不可在此僅回傳
    # none 後忘記 dirty 狀態；render_from_elements 會保留未輸出的 hash，直到
    # 到期時把最新一幀送出。
    raw_minimum = profile.get("partial_refresh_min_interval_seconds", 1.0)
    try:
        partial_minimum = max(1.0, min(60.0, float(raw_minimum)))
    except (TypeError, ValueError):
        partial_minimum = 1.0
    last_partial = _last_partial_refresh.get(device_id)
    if last_partial is not None and now.timestamp() - last_partial < partial_minimum:
        return "none", []

    _last_partial_refresh[device_id] = now.timestamp()
    _partial_count_since_full[device_id] = _partial_count_since_full.get(device_id, 0) + 1
    return "partial", dirty_boxes


def _layout_signature(resolved: dict) -> str:
    """只描述會遺留舊像素的結構，不含可局刷覆蓋的內容設定。"""
    elements = []
    for el in resolved.get("elements", []):
        elements.append({
            key: el.get(key)
            for key in ("instance_id", "module_id", "x", "y", "w", "h", "z")
        })
    raw = json.dumps(
        {"layout_id": resolved.get("layout_id"), "scene": resolved.get("scene"), "elements": elements},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def render_from_elements(resolved: dict, now: datetime.datetime | None = None):
    """純本機運算：畫圖＋雜湊比對 dirty 區塊＋整幅/局部刷新節流。

    一定要在驅動螢幕的那台機器上跑（dirty-box 快取跟刷新歷史都是跟「這台特定螢幕」
    綁在一起的模組層級狀態）。回傳 (最終量化後的 PIL Image, meta dict)。"""
    now = now or config.now_local()
    device_id = resolved["device_id"]
    profile = resolved["profile"]

    canvas = Image.new("RGB", tuple(profile["resolution"]), "white")
    dirty_boxes = []
    dirty_policies: set[str] = set()
    signature = _layout_signature(resolved)
    layout_changed = _last_layout_signature.get(device_id) != signature

    elements = sorted(resolved.get("elements", []), key=lambda e: e.get("z", 0) or 0)
    next_element_states: dict[tuple, tuple] = {}
    for el in elements:
        module = get_module(el.get("module_id"))
        if module is None:
            continue

        size = (int(el["w"]), int(el["h"]))
        cfg = el.get("config", {})
        try:
            element_img = module.render(el.get("data", {}), size, profile.get("color_mode"), cfg)
            if element_img.size != size:
                element_img = element_img.resize(size)
        except Exception as exc:  # noqa: BLE001 - 單一模組壞掉不能拖垮整個裝置畫面
            element_img = _error_placeholder(size, repr(exc))

        x, y = int(el["x"]), int(el["y"])
        canvas.paste(element_img.convert("RGB"), (x, y))

        key = (device_id, el["instance_id"])
        state_hash = hashlib.sha256(element_img.tobytes()).digest()
        prev = _last_element_state.get(key)
        box = [x, y, size[0], size[1]]
        if prev is None or prev[0] != state_hash:
            dirty_boxes.append(box)
            policy = el.get("refresh_policy", module.refresh_policy)
            dirty_policies.add(policy if policy in {"auto", "partial", "full"} else "auto")
        # 只先收集、不立刻寫入。若局刷仍在硬體冷卻時間，下一個 tick 仍要
        # 看見這個差異，否則最後一幀會被錯誤地當成「已顯示」。
        next_element_states[key] = (state_hash, box)

    if layout_changed:
        # 即使新舊內容剛好相同，切換過的 layout 也要完整清屏一次。
        dirty_boxes = [[0, 0, int(profile["resolution"][0]), int(profile["resolution"][1])]]

    final = device_profiles.quantize(canvas, profile)
    refresh_mode, out_boxes = _decide_refresh_mode(
        device_id, profile, dirty_boxes, dirty_policies, now, layout_changed=layout_changed,
    )
    if refresh_mode != "none":
        _last_element_state.update(next_element_states)
    _last_layout_signature[device_id] = signature

    meta = {
        "device_id": device_id,
        "layout_id": resolved.get("layout_id"),
        "scene": resolved.get("scene"),
        "refresh_mode": refresh_mode,
        "dirty_boxes": out_boxes,
        "partial_count_since_full": _partial_count_since_full.get(device_id, 0),
        "partial_refresh_min_interval_seconds": profile.get("partial_refresh_min_interval_seconds"),
        "rendered_at": now.isoformat(timespec="seconds"),
    }
    return final, meta


def render_device(device_id: str, now: datetime.datetime | None = None):
    """resolve_layout_elements() + render_from_elements() 的合併版，回傳
    (最終量化後的 PIL Image, meta dict)。all-in-one 模式跟 /frame.png、/frame-meta
    都用這支，行為維持不變。"""
    now = now or datetime.datetime.now()
    resolved = resolve_layout_elements(device_id, now)
    return render_from_elements(resolved, now)
