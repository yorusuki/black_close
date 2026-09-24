"""在實際 Server 資料庫中建立 7.5 吋設備、頁面與 4.26 吋規則副本。

使用方式（必須在掛載正式 ``/app/data`` 的 epagerpi 容器內執行）：

    python -m server.provision_7in5

這個指令不會覆寫現有頁面或規則，可安全重跑。首次建立設備時，device token 只會
輸出到目前終端一次；不要把輸出貼到 issue、Git 或聊天記錄。
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Callable

from . import default_layouts, workspace_store


DEFAULT_SOURCE_DEVICE = "waveshare426-01"
DEFAULT_TARGET_DEVICE = "waveshare7in5-01"
TARGET_MODEL = "waveshare_7in5_v2"

_PAGES: dict[str, Callable[[], dict]] = {
    "7.5 吋工作儀表板": default_layouts.waveshare_7in5_dashboard_layout,
    "7.5 吋午休資訊頁": default_layouts.waveshare_7in5_lunch_layout,
    "7.5 吋下班頁": default_layouts.waveshare_7in5_off_work_layout,
    "7.5 吋週末休假頁": default_layouts.waveshare_7in5_weekend_layout,
    "7.5 吋國定假日頁": default_layouts.waveshare_7in5_holiday_layout,
    "7.5 吋請假頁": default_layouts.waveshare_leave_layout,
    "7.5 吋專注清單頁": default_layouts.waveshare_7in5_focus_layout,
}


def _source_device(user_id: str | None, source_name: str) -> dict:
    """在指定 owner 或唯一來源名稱下尋找可複製的 4.26 吋設備。"""
    if user_id:
        candidates = [device for device in workspace_store.list_devices(user_id) if device["name"] == source_name]
    else:
        with workspace_store._db() as con:
            rows = con.execute("SELECT user_id FROM devices WHERE name=?", (source_name,)).fetchall()
        owner_ids = {row["user_id"] for row in rows}
        if len(owner_ids) != 1:
            raise ValueError("找不到唯一的來源設備；請以 --user-id 指定其 owner")
        user_id = owner_ids.pop()
        candidates = [device for device in workspace_store.list_devices(user_id) if device["name"] == source_name]
    if len(candidates) != 1:
        raise ValueError("找不到唯一的來源設備；請確認 --source-device 與 --user-id")
    source = candidates[0]
    if source["model_id"] != "waveshare_4in26":
        raise ValueError("來源設備必須是 Waveshare 4.26 吋")
    return source


def _target_page_name(source_page: dict, rule: dict) -> str:
    """依規則語意選擇 7.5 吋頁面，不把 4.26 吋頁面跨型號複製。"""
    if rule.get("attendance_status") == "leave":
        return "7.5 吋請假頁"
    if rule.get("holiday") is True:
        if rule.get("name") == "國定／自訂休假（週休頁）":
            return "7.5 吋週末休假頁"
        return "7.5 吋國定假日頁"
    if set(rule.get("weekdays") or []) == {5, 6}:
        return "7.5 吋週末休假頁"
    if rule.get("attendance_status") == "working" and rule.get("start_time") == "12:00" and rule.get("end_time") == "13:10":
        return "7.5 吋午休資訊頁"
    page_name, rule_name = source_page["name"], rule["name"]
    if "off_work" in page_name or "下班" in rule_name:
        return "7.5 吋下班頁"
    return "7.5 吋工作儀表板"


def _copy_rule_data(rule: dict, target_device: dict, page_id: str) -> dict:
    """保留原本時段、出勤、假日、啟用與優先序；修正舊工作規則的下班遮蔽。"""
    copied = {
        "device_id": target_device["id"], "page_id": page_id,
        "name": f"複製｜{rule['name']}", "priority": rule["priority"],
        "weekdays": rule["weekdays"], "start_time": rule["start_time"], "end_time": rule["end_time"],
        "attendance_status": rule["attendance_status"], "holiday": rule["holiday"], "enabled": rule["enabled"],
    }
    # 舊預設的 08:00–23:59 工作頁會蓋住下班頁；新設備保留同一優先序，但讓工作頁
    # 只在已上班且 18:30 前成立，否則可落到既有的下班／清晨規則。
    if rule["name"] == "平日上班時段" and copied["start_time"] == "08:00" and copied["end_time"] == "23:59":
        copied["end_time"], copied["attendance_status"] = "18:30", "working"
    return copied


def provision_7in5(*, source_device_name: str = DEFAULT_SOURCE_DEVICE,
                   target_device_name: str = DEFAULT_TARGET_DEVICE,
                   user_id: str | None = None) -> dict:
    """建立可部署的 7.5 吋副本；回傳摘要及首次建立時的一次性 token。"""
    workspace_store.init()
    source = _source_device(user_id, source_device_name)
    user_id = source["user_id"]
    target = next((device for device in workspace_store.list_devices(user_id) if device["name"] == target_device_name), None)
    device_created = target is None
    token = None
    if target is None:
        inherited = {
            key: value for key, value in source["profile"].items()
            if key not in workspace_store._HARDWARE_PROFILE_FIELDS
        }
        target = workspace_store.create_device(user_id, target_device_name, TARGET_MODEL, inherited)
        token = target.pop("token")
    elif target["model_id"] != TARGET_MODEL:
        raise ValueError("同名目標設備已存在但不是 7.5 吋型號；請改用 --target-device")

    target_pages = {page["name"]: page for page in workspace_store.list_pages(user_id) if page["model_id"] == TARGET_MODEL}
    pages_created: list[str] = []
    for name, factory in _PAGES.items():
        if name not in target_pages:
            target_pages[name] = workspace_store.create_page(user_id, name, factory(), TARGET_MODEL)
            pages_created.append(name)

    all_pages = {page["id"]: page for page in workspace_store.list_pages(user_id)}
    source_rules = [rule for rule in workspace_store.list_rules(user_id) if rule["device_id"] == source["id"]]
    existing_names = {rule["name"] for rule in workspace_store.list_rules(user_id) if rule["device_id"] == target["id"]}
    rules_created: list[str] = []
    for rule in source_rules:
        copied = _copy_rule_data(rule, target, target_pages[_target_page_name(all_pages[rule["page_id"]], rule)]["id"])
        if copied["name"] in existing_names:
            continue
        workspace_store.create_rule(user_id, copied)
        rules_created.append(copied["name"])

    # provision_7in5 可直接在容器內執行，不能假設網頁服務已替這台新設備建立
    # 假日預設規則；已有來源假日規則副本時，此呼叫會保留它。
    workspace_store.ensure_default_holiday_rules(target["id"])

    return {
        "device": {"id": target["id"], "name": target["name"], "model_id": target["model_id"]},
        "device_created": device_created, "device_token": token,
        "pages_created": pages_created, "rules_created": rules_created,
        "source_rule_count": len(source_rules),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="建立 7.5 吋裝置與 4.26 吋規則副本")
    parser.add_argument("--source-device", default=DEFAULT_SOURCE_DEVICE, help="來源 4.26 吋設備名稱")
    parser.add_argument("--target-device", default=DEFAULT_TARGET_DEVICE, help="新 7.5 吋設備名稱")
    parser.add_argument("--user-id", help="來源設備 owner；同名設備跨帳號時必填")
    args = parser.parse_args(argv)
    try:
        result = provision_7in5(source_device_name=args.source_device, target_device_name=args.target_device, user_id=args.user_id)
    except (ValueError, KeyError) as exc:
        print(f"建立失敗：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["device_token"]:
        print("\n請立即將 device_token 寫進 Pi 的 device_agent/config.yaml；此 token 不會再次顯示。", file=sys.stderr)
    elif not result["device_created"]:
        print("\n設備已存在，因此不會輸出 token；需要 Pi 連線時請在管理台按「重配發 token」。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
