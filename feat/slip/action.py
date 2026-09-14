import json
import os
import re
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


USERNAME_SELECTOR = "#ctl00_ctl00_MainPane_Content_MainContent_Login1_UserName"
PASSWORD_SELECTOR = "#ctl00_ctl00_MainPane_Content_MainContent_Login1_Password"
GRID_ID = "ctl00_ctl00_MainPane_Content_MainContent_grid"
GRID_TABLE_SELECTOR = f"#{GRID_ID}_DXMainTable"
DATA_ROW_SELECTOR = f"tr[id^='{GRID_ID}_DXDataRow']"
HEADER_SELECTORS = {
    "name": f"#{GRID_ID}_col0",
    "clock_in": f"#{GRID_ID}_col3",
    "clock_out": f"#{GRID_ID}_col4",
}
EXPECTED_HEADERS = {
    "name": "姓名",
    "clock_in": "上班時間",
    "clock_out": "下班時間",
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


def column_index(page, key: str) -> int:
    header = page.locator(HEADER_SELECTORS[key])
    header.wait_for(state="visible")
    actual_text = header.inner_text().strip()
    if actual_text != EXPECTED_HEADERS[key]:
        raise RuntimeError(
            f"欄位 {HEADER_SELECTORS[key]} 預期為「{EXPECTED_HEADERS[key]}」，"
            f"實際為「{actual_text}」"
        )
    return header.evaluate(
        "element => Array.from(element.parentElement.children).indexOf(element)"
    )


def employee_name(cell_text: str) -> str:
    return re.sub(r"\s*\[[^\]]*\]\s*$", "", cell_text).strip()


def normalize_time(raw_value: str) -> str:
    value = raw_value.replace("\u00a0", " ").strip()
    if not value:
        return ""

    match = re.fullmatch(r"(上午|下午)?\s*(\d{1,2}):(\d{2})", value)
    if not match:
        raise ValueError(f"無法解析打卡時間：{value}")

    period, hour_text, minute_text = match.groups()
    hour = int(hour_text)
    minute = int(minute_text)
    if minute > 59 or hour > (12 if period else 23) or hour == 0 and period:
        raise ValueError(f"打卡時間不合法：{value}")
    if period == "上午" and hour == 12:
        hour = 0
    elif period == "下午" and hour != 12:
        hour += 12
    return f"{hour:02d}:{minute:02d}"


def read_attendance(page, user_name: str) -> dict[str, str]:
    indices = {key: column_index(page, key) for key in HEADER_SELECTORS}
    rows = page.locator(GRID_TABLE_SELECTOR).locator(DATA_ROW_SELECTOR)
    matches = []

    for row_number in range(rows.count()):
        row = rows.nth(row_number)
        cells = row.locator(":scope > td")
        if cells.count() <= max(indices.values()):
            continue
        if employee_name(cells.nth(indices["name"]).inner_text()) == user_name:
            matches.append(row)

    if not matches:
        raise LookupError(f"找不到姓名完全相符的資料列：{user_name}")
    if len(matches) > 1:
        raise LookupError(f"找到多筆同名資料列：{user_name}")

    cells = matches[0].locator(":scope > td")
    clock_in = normalize_time(cells.nth(indices["clock_in"]).inner_text())
    clock_out = normalize_time(cells.nth(indices["clock_out"]).inner_text())
    return {
        "user": user_name,
        "clock_in": clock_in,
        "clock_out": clock_out,
    }


def main() -> int:
    load_dotenv()
    try:
        user_name = required_env("USER_NAME")
        login_username = required_env("LOGIN_USERNAME")
        login_password = required_env("LOGIN_PASSWORD")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(login_url(), wait_until="domcontentloaded", timeout=30_000)
                page.locator(USERNAME_SELECTOR).fill(login_username)
                page.locator(PASSWORD_SELECTOR).fill(login_password)
                page.get_by_role("button", name="登 入", exact=True).click()
                page.get_by_role("link", name="簽到退", exact=True).click()
                page.wait_for_url("**/Sign.aspx", timeout=30_000)
                page.locator(GRID_TABLE_SELECTOR).wait_for(state="visible")
                result = read_attendance(page, user_name)
                print(json.dumps(result, ensure_ascii=False))
                page.wait_for_timeout(3_000)
            finally:
                browser.close()
    except (
        ValueError,
        RuntimeError,
        LookupError,
        PlaywrightTimeoutError,
        PlaywrightError,
    ) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
