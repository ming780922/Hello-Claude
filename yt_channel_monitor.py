import json
import os
import sys
import xml.etree.ElementTree as ET

import requests

from telegram_utils import send_message

STATE_FILE = "/tmp/yt_state.json"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt":   "http://www.youtube.com/xml/schemas/2015",
}


def main():
    BOT_TOKEN  = os.environ["TELEGRAM_BOT_TOKEN"]
    CHAT_ID    = os.environ["CHAT_ID"]
    CHANNEL_ID = os.environ["YT_CHANNEL_ID"]
    KEYWORD    = os.environ["YT_KEYWORD"]

    FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"

    # 讀取上次狀態
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {"seen_ids": []}

    seen_ids = set(state["seen_ids"])
    is_first_run = len(seen_ids) == 0

    # 拉 Feed
    try:
        resp = requests.get(FEED_URL, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"Feed 取得失敗：{e}")
        sys.exit(1)

    root = ET.fromstring(resp.text)
    entries = root.findall("atom:entry", NS)

    # 找出含關鍵字的新影片
    new_entries = []
    current_ids = []
    for entry in entries:
        vid = entry.findtext("yt:videoId", namespaces=NS) or ""
        current_ids.append(vid)
        if not vid or vid in seen_ids:
            continue
        title   = entry.findtext("atom:title", namespaces=NS) or "(無標題)"
        link_el = entry.find("atom:link", NS)
        link    = link_el.get("href") if link_el is not None else ""
        if KEYWORD.lower() in title.lower():
            new_entries.append({"id": vid, "title": title, "link": link})

    if is_first_run:
        print(f"首次執行，記錄 {len(current_ids)} 部影片，不推播。")
    elif new_entries:
        print(f"發現 {len(new_entries)} 部符合關鍵字「{KEYWORD}」的新影片，推播中...")
        for e in reversed(new_entries):  # 由舊到新
            msg = f"{e['title']}\n{e['link']}"
            r = send_message(BOT_TOKEN, CHAT_ID, msg, raise_on_error=True)
            print(f"  Telegram 回應：{r.status_code} {r.text}")
            print(f"  已送出：{e['title']}")
    else:
        print(f"無符合關鍵字「{KEYWORD}」的新影片。")

    # 更新狀態（記錄所有看過的影片 ID，不論是否符合關鍵字）
    state["seen_ids"] = [vid for vid in current_ids if vid]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


if __name__ == "__main__":
    main()
