import json
import os
import re
import requests
import gspread
from google.oauth2.service_account import Credentials
from telegram_utils import send_message

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
WORKSHEET_NAME = "saved_listings"


def parse_caption(caption):
    """Extract title and url from a saved listing caption.

    Caption format (from notify_telegram.py):
      🏠 <b>title</b>
      region · layout · area · floor · price · update_time
      https://...
    """
    lines = [l.strip() for l in caption.strip().splitlines() if l.strip()]
    title = ""
    url = ""
    for line in lines:
        m = re.search(r"<b>(.*?)</b>", line)
        if m:
            title = m.group(1)
        if line.startswith("http"):
            url = line
    return title, url


def is_available(url, timeout=10):
    """Return True if the 591 listing URL is still live (not 404/gone)."""
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True,
                            headers={"User-Agent": "Mozilla/5.0"})
        # 591 returns 200 even for removed listings but redirects to /home or /index
        if resp.status_code == 404:
            return False
        # Treat redirect away from a detail page as unavailable
        final = resp.url
        if "rent-detail" not in final and "rent.591.com.tw" not in final:
            return False
        return True
    except Exception:
        return False


def get_or_create_worksheet(spreadsheet):
    try:
        return spreadsheet.worksheet(WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=2)
        ws.append_row(["title", "url"])
        return ws


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    listings = json.loads(os.environ["LISTINGS_JSON"])
    sa_json = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    sheet_id = os.environ["EXPORT_SHEET_ID"]

    creds = Credentials.from_service_account_info(sa_json, scopes=SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(sheet_id)
    ws = get_or_create_worksheet(spreadsheet)

    existing_urls = set(ws.col_values(2)[1:])  # skip header

    new_rows = []
    skipped_dup = 0
    skipped_unavailable = 0

    for item in listings:
        title, url = parse_caption(item.get("caption", ""))
        if not url:
            continue
        if url in existing_urls:
            skipped_dup += 1
            continue
        if not is_available(url):
            skipped_unavailable += 1
            continue
        new_rows.append([title, url])
        existing_urls.add(url)

    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")

    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    parts = [f"✅ 已匯出 {len(new_rows)} 筆新物件"]
    if skipped_dup:
        parts.append(f"{skipped_dup} 筆重複略過")
    if skipped_unavailable:
        parts.append(f"{skipped_unavailable} 筆已下架略過")
    msg = "，".join(parts) + f"\n{sheet_url}"
    send_message(token, chat_id, msg)


if __name__ == "__main__":
    main()
