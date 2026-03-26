import argparse
import json
import os
import re
import sys

from telegram_utils import send_message, send_photo_bytes


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


def escape_mdv2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return re.sub(r'([\\_*\[\]()~`>#+=|{}.!\-])', r'\\\1', text)


def _build_price_parts(item: dict) -> list:
    price = item.get("price", "")
    management_fee = item.get("management_fee", "")
    parts = [price]
    if management_fee == '無':
        parts.append("管理費：無")
    elif management_fee:
        parts.append(f"管理費 {management_fee}")
        rent_num = int(re.sub(r'[^\d]', '', price) or '0')
        fee_num = int(re.sub(r'[^\d]', '', management_fee) or '0')
        if rent_num and fee_num:
            parts.append(f"合計 {rent_num + fee_num:,}元")
    return parts


def format_item(item: dict) -> str:
    title = item.get("title", "（無標題）")
    region = item.get("region", "")
    layout = item.get("layout", "")
    area = item.get("area", "")
    floor = item.get("floor", "")
    update_time = item.get("update_time", "")
    url = item.get("link", "")

    price_display = " ＋ ".join(_build_price_parts(item))
    meta = " · ".join(filter(None, [region, layout, area, floor, price_display, update_time]))
    return f"🏠 <b>{title}</b>\n{meta}\n{url}"


CAPTION_MAX = 1024


def format_item_mdv2(item: dict) -> str:
    title = item.get("title", "（無標題）")
    region = item.get("region", "")
    layout = item.get("layout", "")
    area = item.get("area", "")
    floor = item.get("floor", "")
    update_time = item.get("update_time", "")
    url = item.get("link", "")

    price_display = " ＋ ".join(_build_price_parts(item))
    meta = " · ".join(filter(None, [region, layout, area, floor, price_display, update_time]))

    caption = (
        f"🏠 *{escape_mdv2(title)}*\n"
        f"{escape_mdv2(meta)}\n"
        f"[詳情頁]({escape_mdv2(url)})"
    )
    if len(caption) > CAPTION_MAX:
        caption = caption[:CAPTION_MAX - 1] + "…"
    return caption


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
    send_message(token, chat_id, header, parse_mode="HTML")

    for item in recent:
        screenshot_path = item.get("screenshot_path")
        if screenshot_path and os.path.exists(screenshot_path):
            caption = format_item_mdv2(item)
            try:
                with open(screenshot_path, "rb") as f:
                    img_data = f.read()
                send_photo_bytes(
                    token, chat_id, img_data,
                    filename=os.path.basename(screenshot_path),
                    caption=caption,
                    parse_mode="MarkdownV2",
                )
            except Exception as e:
                print(f"Warning: photo send failed for {item.get('id')}: {e}", file=sys.stderr)
                send_message(token, chat_id, format_item(item),
                             parse_mode="HTML", disable_web_page_preview=True)
        else:
            send_message(token, chat_id, format_item(item),
                         parse_mode="HTML", disable_web_page_preview=True)


if __name__ == "__main__":
    main()
