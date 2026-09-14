import json
import os
import re
import sys
from datetime import date, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


USERNAME_SELECTOR = "#ctl00_ctl00_MainPane_Content_MainContent_Login1_UserName"
PASSWORD_SELECTOR = "#ctl00_ctl00_MainPane_Content_MainContent_Login1_Password"
GRID_ID = "ctl00_ctl00_MainPane_Content_MainContent_grid"
GRID_TABLE_SELECTOR = f"#{GRID_ID}_DXMainTable"
DATA_ROW_SELECTOR = f"tr[id^='{GRID_ID}_DXDataRow']"
CURRENT_PAGE_SELECTOR = f"#{GRID_ID}_DXPagerBottom .dxp-current"
STATUS_LABELS = {
    "editing": "編輯中",
    "reviewing": "簽核中",
    "adjudicated": "已裁決",
}
FIELD_HEADERS = {
    "applicant": ("col1", "請假人"),
    "leave_number": ("col2", "假單號"),
    "application_date": ("col3", "申請日"),
    "leave_type": ("col4", "假別"),
    "start_time": ("col5", "起始時間"),
    "end_time": ("col6", "結束時間"),
    "hours": ("col7", "時數"),
    "reason": ("col8", "事由"),
    "substitute": ("col9", "職代"),
    "status": ("col10", "狀態"),
}


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f".env 缺少必填設定：{name}")
    return value


def login_url() -> str:
    """讀取登入端點；只接受 HTTPS，避免意外把帳密送到不安全網址。"""
    value = required_env("EIP_LOGIN_URL")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("EIP_LOGIN_URL 必須是未含帳密的 HTTPS 網址")
    return value


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()


def column_indices(page) -> dict[str, int]:
    indices = {}
    for key, (column_id, expected_text) in FIELD_HEADERS.items():
        header = page.locator(f"#{GRID_ID}_{column_id}")
        header.wait_for(state="visible")
        actual_text = clean_text(header.inner_text())
        if actual_text != expected_text:
            raise RuntimeError(
                f"欄位 {column_id} 預期為「{expected_text}」，"
                f"實際為「{actual_text}」"
            )
        indices[key] = header.evaluate(
            "element => Array.from(element.parentElement.children).indexOf(element)"
        )
    return indices


def read_current_page(page, indices: dict[str, int], query_state: str) -> list[dict]:
    records = []
    rows = page.locator(GRID_TABLE_SELECTOR).locator(DATA_ROW_SELECTOR)
    for row_number in range(rows.count()):
        cells = rows.nth(row_number).locator(":scope > td")
        if cells.count() <= max(indices.values()):
            raise RuntimeError("假單資料列欄位數量與表頭不一致")
        record = {
            key: clean_text(cells.nth(index).inner_text())
            for key, index in indices.items()
        }
        record["query_state"] = query_state
        records.append(record)
    return records


def wait_for_grid(page) -> None:
    page.wait_for_function(
        "() => typeof window.grid !== 'undefined' && !window.grid.InCallback()",
        timeout=30_000,
    )
    page.locator(GRID_TABLE_SELECTOR).wait_for(state="visible", timeout=30_000)


def select_status(page, label_text: str) -> None:
    label = page.locator("label").filter(
        has_text=re.compile(f"^{re.escape(label_text)}$")
    )
    if label.count() != 1:
        raise RuntimeError(f"找不到唯一的查詢狀態：{label_text}")
    label.click()
    wait_for_grid(page)


def go_to_last_page(page) -> None:
    page_links = page.locator(f"#{GRID_ID}_DXPagerBottom a.dxp-num")
    if page_links.count() == 0:
        return

    numbered_links = []
    for index in range(page_links.count()):
        link = page_links.nth(index)
        text = clean_text(link.inner_text())
        if text.isdigit():
            numbered_links.append((int(text), link))
    if not numbered_links:
        return

    current_locator = page.locator(CURRENT_PAGE_SELECTOR)
    current_page = clean_text(current_locator.inner_text())
    last_page_number, last_page_link = max(numbered_links, key=lambda item: item[0])
    if current_page == f"[{last_page_number}]":
        return

    last_page_link.click()
    page.wait_for_function(
        "([selector, expected]) => {"
        " const current = document.querySelector(selector);"
        " return current && current.textContent.trim() === expected;"
        "}",
        arg=[CURRENT_PAGE_SELECTOR, f"[{last_page_number}]"],
        timeout=30_000,
    )
    wait_for_grid(page)


def read_selected_page(page, query_state: str, *, last_page: bool = False) -> list[dict]:
    indices = column_indices(page)
    if last_page:
        go_to_last_page(page)
    return read_current_page(page, indices, query_state)


def parse_leave_datetime(value: str) -> datetime:
    match = re.fullmatch(
        r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(?:(上午|下午)\s+)?"
        r"(\d{1,2}):(\d{2})(?::(\d{2}))?",
        clean_text(value),
    )
    if not match:
        raise ValueError(f"無法解析假單時間：{value}")
    year, month, day, period, hour, minute, second = match.groups()
    hour_number = int(hour)
    if period == "上午" and hour_number == 12:
        hour_number = 0
    elif period == "下午" and hour_number != 12:
        hour_number += 12
    return datetime(
        int(year),
        int(month),
        int(day),
        hour_number,
        int(minute),
        int(second or 0),
        tzinfo=ZoneInfo("Asia/Taipei"),
    )


def leave_covers_date(record: dict, target_date: date) -> bool:
    start = parse_leave_datetime(record["start_time"])
    end = parse_leave_datetime(record["end_time"])
    if end < start:
        raise ValueError(f"假單 {record['leave_number']} 的結束時間早於起始時間")
    return start.date() <= target_date <= end.date()


def build_result(records_by_state: dict[str, list[dict]], today: date) -> dict:
    all_records = [
        record
        for state_records in records_by_state.values()
        for record in state_records
    ]
    today_records = [
        record for record in all_records if leave_covers_date(record, today)
    ]
    return {
        "date": today.isoformat(),
        "has_leave_today": bool(today_records),
        "today_leave_records": today_records,
        "total_records": len(all_records),
        "records": records_by_state,
    }


def main() -> int:
    load_dotenv()
    try:
        login_username = required_env("LOGIN_USERNAME")
        login_password = required_env("LOGIN_PASSWORD")
        today = datetime.now(ZoneInfo("Asia/Taipei")).date()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(login_url(), wait_until="domcontentloaded", timeout=30_000)
                page.locator(USERNAME_SELECTOR).fill(login_username)
                page.locator(PASSWORD_SELECTOR).fill(login_password)
                page.get_by_role("button", name="登 入", exact=True).click()
                page.locator("div").filter(has_text="行政資源").nth(5).click()
                page.get_by_role("link", name="請假申請", exact=True).click()
                page.wait_for_timeout(1_000)
                page = page.context.pages[-1]
                page.wait_for_load_state("domcontentloaded")
                wait_for_grid(page)

                records_by_state = {}
                for key, label_text in STATUS_LABELS.items():
                    select_status(page, label_text)
                    records_by_state[key] = read_selected_page(
                        page,
                        key,
                        last_page=key == "adjudicated",
                    )

                print(
                    json.dumps(
                        build_result(records_by_state, today),
                        ensure_ascii=False,
                    )
                )
            finally:
                browser.close()
    except (
        ValueError,
        RuntimeError,
        PlaywrightTimeoutError,
        PlaywrightError,
    ) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
