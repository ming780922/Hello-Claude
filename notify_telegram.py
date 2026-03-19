import argparse
import json
import os
import re
import sys
import requests


def is_within_hours(update_time: str, hours: int) -> bool:
    """Return True if update_time string represents a time within `hours` hours."""
    if not update_time:
        return False
    # Match "X分鐘內更新"
    m = re.match(r"^(\d+)分鐘內更新$", update_time)
    if m:
        return int(m.group(1)) <= hours * 60
    # Match "X小時內更新"
    m = re.match(r"^(\d+)小時內更新$", update_time)
    if m:
        return int(m.group(1)) <= hours
    return False


TELEGRAM_MAX_LENGTH = 4096


def format_item(item: dict) -> str:
    title = item.get("title", "（無標題）")
    region = item.get("region", "")
    layout = item.get("layout", "")
    area = item.get("area", "")
    floor = item.get("floor", "")
    price = item.get("price", "")
    update_time = item.get("update_time", "")
    url = item.get("link", "")
    meta = " · ".join(filter(None, [region, layout, area, floor, price, update_time]))
    return f"🏠 <b>{title}</b>\n{meta}\n{url}"


def send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()


def send_batched(token: str, chat_id: str, header: str, items: list[str]) -> None:
    """Send items as few messages as possible, splitting only when exceeding Telegram's limit."""
    separator = "\n\n"
    current = header
    for item in items:
        candidate = current + separator + item
        if len(candidate) > TELEGRAM_MAX_LENGTH:
            send_telegram(token, chat_id, current)
            current = item
        else:
            current = candidate
    send_telegram(token, chat_id, current)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send 591 rent listings to Telegram")
    parser.add_argument("--file", default="591_rent_data.json", help="Path to JSON data file")
    parser.add_argument("--hours", type=int, default=1, help="Include listings updated within this many hours")
    args = parser.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set", file=sys.stderr)
        sys.exit(1)

    with open(args.file, encoding="utf-8") as f:
        data = json.load(f)

    recent = [item for item in data if is_within_hours(item.get("update_time", ""), args.hours)]
    print(f"Filtered {len(recent)} / {len(data)} listings within {args.hours} hour(s)")

    header = (
        f"📊 <b>591 爬蟲摘要</b>\n"
        f"共抓取 {len(data)} 筆 ｜ {args.hours} 小時內更新 {len(recent)} 筆"
    )
    if not recent:
        send_telegram(token, chat_id, header)
        return

    items = [format_item(item) for item in recent]
    send_batched(token, chat_id, header, items)


if __name__ == "__main__":
    main()
