import json
import os
import sys

from telegram_utils import send_telegram, send_batched


def format_item(item: dict) -> str:
    author = item.get("author", "（未知作者）")
    time_str = item.get("time_str", "")
    content = item.get("content", "").strip()
    if len(content) > 200:
        content = content[:200] + "..."
    url = item.get("url", "")
    header = f"📌 <b>{author}</b>"
    if time_str:
        header += f"  {time_str}"
    parts = [header]
    if content:
        parts.append(content)
    if url:
        parts.append(url)
    return "\n".join(parts)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set", file=sys.stderr)
        sys.exit(1)

    with open("fb_group_data.json", encoding="utf-8") as f:
        data = json.load(f)

    print(f"共讀取 {len(data)} 筆文章")

    header = f"📣 <b>Facebook 社團爬蟲結果</b>\n昨天共 {len(data)} 篇文章"
    if not data:
        send_telegram(token, chat_id, header, parse_mode="HTML")
        return

    items = [format_item(item) for item in data]
    send_batched(token, chat_id, header, items)


if __name__ == "__main__":
    main()
