import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import telegram_utils

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
SAVED_LISTINGS = json.loads(os.environ["SAVED_LISTINGS"])
CF_API_TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]
CF_ACCOUNT_ID = os.environ["CLOUDFLARE_ACCOUNT_ID"]
D1_DATABASE_ID = "30b68c33-6437-4359-beb9-1cc8180b1542"


def check_listing_exists(item_id):
    try:
        resp = requests.get(
            f"https://rent.591.com.tw/{item_id}",
            allow_redirects=True,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible)"},
        )
        if resp.status_code >= 400:
            return False
        return "物件不存在" not in resp.text
    except Exception:
        return True  # assume still exists on error


def delete_from_d1(item_id):
    requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}"
        f"/d1/database/{D1_DATABASE_ID}/query",
        headers={
            "Authorization": f"Bearer {CF_API_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "sql": "DELETE FROM saved_listings WHERE item_id = ? AND chat_id = ?",
            "params": [str(item_id), str(CHAT_ID)],
        },
        timeout=15,
    )


def send_listing(item_id, caption):
    telegram_utils.send_message(
        BOT_TOKEN, CHAT_ID, caption,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup={
            "inline_keyboard": [[{"text": "🗑️ 移除",
                                   "callback_data": f"unsave:{item_id}"}]]
        },
    )


def main():
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(check_listing_exists, item["item_id"]): item
            for item in SAVED_LISTINGS
        }
        existence = {
            futures[f]["item_id"]: f.result()
            for f in as_completed(futures)
        }

    removed = [item for item in SAVED_LISTINGS if not existence[item["item_id"]]]
    active = [item for item in SAVED_LISTINGS if existence[item["item_id"]]]

    if removed:
        for item in removed:
            delete_from_d1(item["item_id"])
        telegram_utils.send_message(
            BOT_TOKEN, CHAT_ID,
            f"⚠️ 已自動移除 {len(removed)} 個已下架的物件。",
        )

    if not active:
        telegram_utils.send_message(BOT_TOKEN, CHAT_ID, "目前沒有儲存的物件。")
    else:
        for item in active:
            send_listing(item["item_id"], item["caption"])


if __name__ == "__main__":
    main()
