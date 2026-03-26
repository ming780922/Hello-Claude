import argparse
import json
import os
import re
import sys

from telegram_utils import send_telegram, send_batched


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


def format_item(item: dict) -> str:
    title = item.get("title", "（無標題）")
    region = item.get("region", "")
    layout = item.get("layout", "")
    area = item.get("area", "")
    floor = item.get("floor", "")
    price = item.get("price", "")
    update_time = item.get("update_time", "")
    url = item.get("link", "")
    management_fee = item.get("management_fee", "")

    price_parts = [price]
    if management_fee == '無':
        price_parts.append("管理費：無")
    elif management_fee:
        price_parts.append(f"管理費 {management_fee}")
        rent_num = int(re.sub(r'[^\d]', '', price) or '0')
        fee_num = int(re.sub(r'[^\d]', '', management_fee) or '0')
        if rent_num and fee_num:
            price_parts.append(f"合計 {rent_num + fee_num:,}元")

    price_display = " ＋ ".join(price_parts)
    meta = " · ".join(filter(None, [region, layout, area, floor, price_display, update_time]))
    return f"🏠 <b>{title}</b>\n{meta}\n{url}"


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
    recent.sort(key=lambda x: int(re.sub(r'[^\d]', '', x.get('price', '0')) or '0'), reverse=True)
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
