"""Pi agent: it knows only a Server URL and its own device token."""
from __future__ import annotations

import datetime
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, UnidentifiedImageError

from . import config as agent_config
from .drivers import build_driver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("device_agent.agent")
LAYOUT_CACHE_PATH = agent_config.BASE_DIR / "data" / "runtime" / "last_device_layout.json"
MAX_ASSET_DOWNLOAD_BYTES = 30 * 1024 * 1024
MAX_ANIMATION_DOWNLOAD_BYTES = 30 * 1024 * 1024
MAX_ANIMATION_FRAMES = 24


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def display_is_quiet(profile: object, now: datetime.datetime) -> bool:
    """判定是否位於 Server 下發的畫面靜默時段；格式無效時安全地維持正常刷新。"""
    settings = profile.get("display_quiet_hours") if isinstance(profile, dict) else None
    if not isinstance(settings, dict) or settings.get("enabled") is not True:
        return False
    if settings.get("pause_weekends", True) is True and now.weekday() >= 5:
        return True
    start, end = settings.get("start"), settings.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        return False
    try:
        start_time, end_time = datetime.time.fromisoformat(start), datetime.time.fromisoformat(end)
    except ValueError:
        return False
    if start_time == end_time:
        return False
    current = now.time()
    return start_time <= current < end_time if start_time < end_time else current >= start_time or current < end_time


def fetch_layout(server_url: str, headers: dict) -> dict:
    response = requests.get(f"{server_url}/api/v1/device/layout", headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()


def _valid_cached_layout(value: object) -> bool:
    """只接受 agent 可安全拿去本機渲染的最小 layout 結構。"""
    if not isinstance(value, dict) or not isinstance(value.get("device_id"), str):
        return False
    profile = value.get("profile")
    resolution = profile.get("resolution") if isinstance(profile, dict) else None
    return (
        isinstance(resolution, list)
        and len(resolution) == 2
        and all(isinstance(item, int) and item > 0 for item in resolution)
        and isinstance(value.get("elements"), list)
    )


def load_layout_cache() -> dict | None:
    """載入最後一次 API 成功回應，讓 Pi 重啟後仍能在離線狀態本機刷新。"""
    try:
        value = json.loads(LAYOUT_CACHE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        log.warning("離線版面快取無法讀取，會等待 Server 提供新版本")
        return None
    if not _valid_cached_layout(value):
        log.warning("離線版面快取格式無效，會等待 Server 提供新版本")
        return None
    return value


def save_layout_cache(resolved: dict) -> None:
    """以原子替換保存非機密的已解析版面，檔案僅限 Pi 帳號讀寫。"""
    if not _valid_cached_layout(resolved):
        raise ValueError("Server 回傳的 layout 格式不完整")
    LAYOUT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = LAYOUT_CACHE_PATH.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(resolved, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(LAYOUT_CACHE_PATH)
    finally:
        # replace() 成功後暫存檔已不存在；失敗時盡力清理，不影響既有有效快取。
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def report_telemetry(server_url: str, headers: dict, payload: dict) -> None:
    try:
        requests.post(f"{server_url}/api/v1/device/telemetry", headers=headers, json=payload, timeout=10).raise_for_status()
    except requests.RequestException:
        # Telemetry is advisory: it must not stop rendering if a remote server is unavailable.
        log.warning("telemetry 上傳失敗，會在下個輪詢週期重試")


def _safe_asset_filename(value: object) -> str | None:
    """只允許 Server 下發的一個檔名，禁止 layout 資料跨出 Pi 快取資料夾。"""
    if not isinstance(value, str) or not value or len(value) > 180:
        return None
    return value if Path(value).name == value and value not in {".", ".."} else None


def _valid_asset_file(path: Path) -> bool:
    try:
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_ASSET_DOWNLOAD_BYTES:
            return False
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, UnidentifiedImageError, ValueError):
        return False


def _download_asset_path(server_url: str, headers: dict, path: str, destination: Path, *, byte_limit: int, label: str) -> bool:
    """串流下載、大小限制、完整驗證後才原子替換舊圖片。"""
    temporary_name: str | None = None
    try:
        response = requests.get(
            f"{server_url}/api/v1/device/{path}", headers=headers, timeout=30, stream=True
        )
        response.raise_for_status()
        destination.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False) as temporary:
            temporary_name = temporary.name
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > byte_limit:
                    raise ValueError("素材下載超過允許大小")
                temporary.write(chunk)
            temporary.flush()
            os.fsync(temporary.fileno())
        if not _valid_asset_file(Path(temporary_name)):
            raise ValueError("素材下載內容不是有效圖片")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, destination)
        temporary_name = None
        log.info("素材已同步且驗證完成：%s", destination.name)
        return True
    except (requests.RequestException, OSError, ValueError):
        log.exception("素材同步失敗，保留舊圖片並於下一輪重試：%s", label)
        return False
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        if "response" in locals():
            getattr(response, "close", lambda: None)()


def _download_asset(server_url: str, headers: dict, asset_id: str, destination: Path) -> bool:
    """相容既有靜態素材下載入口。"""
    if not isinstance(asset_id, str) or not asset_id:
        return False
    return _download_asset_path(
        server_url, headers, f"assets/{quote(asset_id, safe='')}", destination,
        byte_limit=MAX_ASSET_DOWNLOAD_BYTES, label=asset_id,
    )


def _animation_frames(data: object) -> list[dict] | None:
    """驗證 Server 下發的動畫資料；None 代表不是動畫，空 list 代表格式不安全。"""
    if not isinstance(data, dict) or "animation" not in data:
        return None
    animation = data.get("animation")
    if not isinstance(animation, dict) or animation.get("animated") is not True:
        return []
    frames = animation.get("frames")
    if not isinstance(frames, list) or not 2 <= len(frames) <= MAX_ANIMATION_FRAMES:
        return []
    clean: list[dict] = []
    for frame in frames:
        if not isinstance(frame, dict):
            return []
        filename, duration = _safe_asset_filename(frame.get("filename")), frame.get("duration_ms")
        if not filename or not isinstance(duration, int) or not 20 <= duration <= 10_000:
            return []
        clean.append({"filename": filename, "duration_ms": duration})
    return clean


def _ensure_asset(server_url: str, headers: dict, asset_id: str, destination: Path, *, byte_limit: int, path: str | None = None) -> bool:
    if destination.is_file():
        try:
            if _valid_asset_file(destination):
                return True
            log.warning("本機素材驗證失敗，會重新下載：%s", destination.name)
        except OSError:
            pass
    if path is None:
        return _download_asset(server_url, headers, asset_id, destination)
    return _download_asset_path(server_url, headers, path, destination, byte_limit=byte_limit, label=asset_id)


def sync_assets(server_url: str, headers: dict, resolved: dict) -> bool:
    """同步目前 layout 的圖片；任一張未就緒時回傳 False，呼叫者不可切換新版面。"""
    assets_dir = agent_config.BASE_DIR / "data" / "assets"
    ready = True
    for element in resolved.get("elements", []):
        if not isinstance(element, dict):
            ready = False
            continue
        if element.get("module_id") != "image":
            continue
        config = element.get("config") or {}
        data = element.get("data") or {}
        asset_id = config.get("asset_id") if isinstance(config, dict) else None
        filename = _safe_asset_filename(data.get("filename") if isinstance(data, dict) else None)
        # 沒選圖片是圖片模組的正常空白狀態，不影響整張 layout 套用。
        if not asset_id:
            continue
        if not isinstance(asset_id, str) or not filename:
            log.warning("新版面含有不完整圖片資料，暫不套用：asset_id=%r filename=%r", asset_id, filename)
            ready = False
            continue
        destination = assets_dir / filename
        if not _ensure_asset(server_url, headers, asset_id, destination, byte_limit=MAX_ASSET_DOWNLOAD_BYTES):
            ready = False
            continue

        frames = _animation_frames(data)
        if frames == []:
            log.warning("新版面含有不安全的動畫資料，暫不套用：%s", asset_id)
            ready = False
            continue
        if frames is None:
            continue
        total = 0
        animation_ready = True
        for index, frame in enumerate(frames):
            frame_path = assets_dir / frame["filename"]
            if frame_path.is_file() and _valid_asset_file(frame_path):
                total += frame_path.stat().st_size
                if total > MAX_ANIMATION_DOWNLOAD_BYTES:
                    animation_ready = False
                    break
                continue
            remaining = MAX_ANIMATION_DOWNLOAD_BYTES - total
            if remaining <= 0 or not _ensure_asset(
                server_url,
                headers,
                asset_id,
                frame_path,
                byte_limit=remaining,
                path=f"assets/{quote(asset_id, safe='')}/frames/{index}",
            ):
                animation_ready = False
                break
            total += frame_path.stat().st_size
        if not animation_ready:
            log.warning("動畫影格尚未完整同步，保留目前已套用版面：%s", asset_id)
            ready = False
    return ready


def effective_tick_seconds(configured_seconds: float, resolved: dict | None) -> float:
    """以 Server 下發的型號能力縮短本機 renderer tick。

    這不是面板的局刷間隔本身（該間隔仍由 compositor 強制節流），而是讓 7.5
    吋 1.2 秒、4.26 吋 2.1 秒的安全下限不會被舊有 1 秒輪詢粗略化成更慢的
    2/3 秒。設定檔的值仍可自行調得更短；沒有新版 profile 時維持舊行為。
    """
    profile = resolved.get("profile", {}) if isinstance(resolved, dict) else {}
    requested = profile.get("partial_refresh_tick_seconds") if isinstance(profile, dict) else None
    try:
        candidate = float(requested)
    except (TypeError, ValueError):
        return configured_seconds
    if not 0.1 <= candidate <= 5:
        return configured_seconds
    return min(configured_seconds, candidate)


def run() -> None:
    from server import config as server_config
    from server.render.compositor import render_from_elements, reset_device_render_state

    cfg = agent_config.load_config()
    server_url, headers = cfg["server_url"], _headers(cfg["device_token"])
    poll_interval, configured_tick_seconds = cfg["poll_interval_seconds"], cfg["tick_seconds"]
    resolved = load_layout_cache()
    tick_seconds = effective_tick_seconds(configured_tick_seconds, resolved)
    driver = None
    last_poll = 0.0
    last_mode = "none"
    quiet_active = False
    quiet_final_frame_pending = False
    has_displayed_since_start = False
    last_displayed_layout_id: str | None = None
    log.info("agent 啟動：server=%s，採 device token 驗證", server_url)
    if resolved is not None:
        try:
            driver = build_driver(resolved["profile"])
            log.info("已載入最後有效版面；Server 不可達時仍可依本機刷新政策運作")
        except (ValueError, KeyError):
            log.exception("離線版面設定無法建立硬體驅動，將等待 Server 提供新版本")
            resolved = None

    while True:
        now = time.monotonic()
        fetched_layout = False
        if resolved is None or now - last_poll >= poll_interval:
            try:
                fresh_layout = fetch_layout(server_url, headers)
                if not _valid_cached_layout(fresh_layout):
                    raise ValueError("Server 回傳的 layout 格式不完整")
                last_poll = now
                assets_ready = sync_assets(server_url, headers, fresh_layout)
                if not assets_ready and resolved is not None:
                    # 已有畫面時絕不讓未同步圖片的新版面蓋掉舊圖；下一個 poll 完整
                    # 下載並驗證後才切換。
                    log.warning("新版面仍有圖片下載中，保留目前已套用版面")
                    continue
                resolved = fresh_layout
                tick_seconds = effective_tick_seconds(configured_tick_seconds, resolved)
                fetched_layout = True
                if assets_ready:
                    try:
                        save_layout_cache(fresh_layout)
                    except OSError:
                        # 儲存空間或檔案權限問題不能妨礙已驗證的當前版面顯示；記錄後
                        # 下輪會重試保存，既有快取也不會被破壞。
                        log.exception("無法保存離線版面快取，這次仍使用 Server 新版面")
                else:
                    # 冷啟動沒有上一份版面可保留時會顯示安全佔位，且不污染離線快取。
                    log.warning("尚無可保留的舊版面；圖片完成同步前暫以佔位顯示")
                if driver is None:
                    driver = build_driver(resolved["profile"])
                report_telemetry(server_url, headers, {"status": "online", "agent_version": "v1", "refresh_mode": last_mode})
            except (requests.RequestException, ValueError, KeyError):
                log.exception("無法取得 device layout；保留上一份有效畫面")

        wall_now = server_config.now_local()
        quiet_now = resolved is not None and display_is_quiet(resolved.get("profile"), wall_now)
        if quiet_now:
            if not quiet_active:
                # 若本程式原本正在顯示，保留一個機會讓剛進入靜默的最新
                # layout（通常是下班頁）寫到面板；冷啟動於靜默時則不喚醒面板。
                quiet_final_frame_pending = has_displayed_since_start
                quiet_active = True
                log.info("進入畫面靜默時段；停止實體面板刷新至設定結束時間")
        elif quiet_active and resolved is not None:
            # 靜默期間仍會取回最新版面／素材，但不更新實體面板；恢復時清除記憶，
            # 使第一張畫面一定全刷，清掉過夜可能殘留的像素。
            reset_device_render_state(resolved["device_id"])
            quiet_active = False
            quiet_final_frame_pending = False
            log.info("畫面靜默時段結束；將以全刷恢復顯示")

        render_during_quiet_entry = quiet_now and quiet_final_frame_pending and fetched_layout
        # 週末靜默不是把週末頁永遠卡在前一頁：只要 Server 第一次下發專用週末
        # layout，就輸出一次。其後即使每日 marker 或文字模組被重新解析，也不再刷新。
        render_weekend_static_page = (
            quiet_now and wall_now.weekday() >= 5 and fetched_layout
            and resolved is not None and resolved.get("layout_id") != last_displayed_layout_id
        )
        if resolved is not None and driver is not None and (not quiet_now or render_during_quiet_entry or render_weekend_static_page):
            try:
                image, meta = render_from_elements(resolved, wall_now)
                last_mode = meta["refresh_mode"]
                if last_mode != "none":
                    driver.show(image, mode=last_mode, dirty_boxes=meta["dirty_boxes"])
                    log.info("刷新完成：mode=%s dirty=%d", last_mode, len(meta["dirty_boxes"]))
                has_displayed_since_start = True
                last_displayed_layout_id = resolved.get("layout_id")
                if render_during_quiet_entry:
                    quiet_final_frame_pending = False
            except Exception:
                log.exception("本機渲染／刷新失敗，將於下一個 tick 重試")
        time.sleep(tick_seconds)


if __name__ == "__main__":
    run()
