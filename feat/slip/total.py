import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import action
import slip


def login(page, username: str, password: str) -> None:
    page.goto(action.login_url(), wait_until="domcontentloaded", timeout=30_000)
    page.locator(action.USERNAME_SELECTOR).fill(username)
    page.locator(action.PASSWORD_SELECTOR).fill(password)
    page.get_by_role("button", name="登 入", exact=True).click()


def open_attendance(page) -> None:
    page.get_by_role("link", name="簽到退", exact=True).click()
    page.wait_for_url("**/Sign.aspx", timeout=30_000)
    page.locator(action.GRID_TABLE_SELECTOR).wait_for(state="visible")


def open_leave_system(page):
    page.locator("div").filter(has_text="行政資源").nth(5).click()
    page.get_by_role("link", name="請假申請", exact=True).click()
    page.wait_for_timeout(1_000)
    leave_page = page.context.pages[-1]
    leave_page.wait_for_load_state("domcontentloaded")
    slip.wait_for_grid(leave_page)
    return leave_page


def read_leave_summary(page, today) -> dict:
    records = []
    for key, label_text in slip.STATUS_LABELS.items():
        slip.select_status(page, label_text)
        records.extend(
            slip.read_selected_page(
                page,
                key,
                last_page=key == "adjudicated",
            )
        )
    return {
        "date": today.isoformat(),
        "has_leave_today": any(
            slip.leave_covers_date(record, today) for record in records
        ),
    }


def main() -> int:
    load_dotenv()
    try:
        user_name = action.required_env("USER_NAME")
        login_username = action.required_env("LOGIN_USERNAME")
        login_password = action.required_env("LOGIN_PASSWORD")
        today = datetime.now(ZoneInfo("Asia/Taipei")).date()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            # browser = playwright.chromium.launch(headless=False, slow_mo=300)
            try:
                page = browser.new_page()
                login(page, login_username, login_password)

                open_attendance(page)
                result = action.read_attendance(page, user_name)

                leave_page = open_leave_system(page)
                result.update(read_leave_summary(leave_page, today))
                print(json.dumps(result, ensure_ascii=False))
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
