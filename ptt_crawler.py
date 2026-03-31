#!/usr/bin/env python3
"""
PTT LifeIsMoney 網頁版爬蟲
使用 Playwright 直接爬取 PTT 網頁，不透過 RSS Feed 或 Proxy
"""
import asyncio
import json
import os
import re
import sys

from playwright.async_api import async_playwright

from telegram_utils import send_message

PTT_BASE = "https://www.ptt.cc"
BOARDS = ["LifeIsMoney", "creditcard", "Rent_apart"]
STATE_FILE = "/tmp/ptt_crawler_state.json"
MAX_PAGES = 5  # 最多往前翻幾頁


def extract_article_id(href: str) -> str | None:
    """從 href 路徑提取文章 ID，例如 M.1234567890.A.ABC"""
    m = re.search(r"/(M\.\d+\.\w+\.\w+)\.html", href)
    return m.group(1) if m else None


def extract_timestamp(article_id: str) -> int:
    """從文章 ID 提取 Unix timestamp，例如 M.1774255579.A.130 → 1774255579"""
    m = re.match(r"M\.(\d+)\.", article_id)
    return int(m.group(1)) if m else 0


def parse_articles(html_content: str) -> list[dict]:
    """從頁面 HTML 解析文章列表，回傳 list of {id, title, link}"""
    # 找所有 .r-ent 區塊中有連結的文章（跳過被刪除的）
    articles = []
    # 用 regex 解析，避免引入 BeautifulSoup 依賴
    pattern = re.compile(
        r'<div class="r-ent">.*?<div class="title">\s*(?:<a href="([^"]+)"[^>]*>(.*?)</a>|[^<]*)\s*</div>',
        re.DOTALL,
    )
    for m in pattern.finditer(html_content):
        href = m.group(1)
        title_raw = m.group(2)
        if not href or not title_raw:
            continue  # 被刪除的文章
        article_id = extract_article_id(href)
        if not article_id:
            continue
        title = re.sub(r"<[^>]+>", "", title_raw).strip()
        link = PTT_BASE + href
        articles.append({"id": article_id, "title": title, "link": link})
    return articles


def find_prev_page_url(html_content: str, board: str) -> str | None:
    """找「上頁」按鈕的連結"""
    m = re.search(rf'<a[^>]+href="(/bbs/{board}/index\d+\.html)"[^>]*>\s*‹ 上頁', html_content)
    if m:
        return PTT_BASE + m.group(1)
    # 備用：找 class="btn wide" 的上頁
    m = re.search(rf'href="(/bbs/{board}/index\d+\.html)"[^>]*>[^<]*上頁', html_content)
    return (PTT_BASE + m.group(1)) if m else None


async def fetch_page(page, url: str) -> str:
    """訪問頁面並回傳 HTML 內容"""
    print(f"訪問：{url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(1000)
    return await page.content()


async def main():
    BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
    CHAT_ID = os.environ["CHAT_ID"]

    # 讀取上次狀態
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        # 向下兼容，舊版格式為 {"last_timestamp": 1234}
        if "last_timestamps" in state:
            last_timestamps = state["last_timestamps"]
        elif "last_timestamp" in state:
            last_timestamps = {"LifeIsMoney": state["last_timestamp"]}
        else:
            last_timestamps = {}
    except FileNotFoundError:
        last_timestamps = {}

    all_collected = []  # 收集所有看板的新文章

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        # 設定 over18 cookie 跳過年齡確認
        await context.add_cookies([
            {"name": "over18", "value": "1", "domain": "www.ptt.cc", "path": "/"}
        ])
        page = await context.new_page()

        for board in BOARDS:
            print(f"--- 開始處理看板：{board} ---")
            board_last_ts = last_timestamps.get(board)
            is_first_run = board_last_ts is None
            print(f"[{board}] 上次最後文章 timestamp：{board_last_ts or '（首次紀錄）'}")

            board_collected = []
            board_latest_ts = board_last_ts or 0
            board_latest_title = None

            current_url = f"{PTT_BASE}/bbs/{board}/index.html"
            
            for page_num in range(MAX_PAGES):
                html = await fetch_page(page, current_url)
                articles = parse_articles(html)
                print(f"  [{board}] 本頁解析到 {len(articles)} 篇文章")

                if not articles:
                    print(f"  [{board}] 本頁無文章，停止翻頁")
                    break

                for article in articles:
                    ts = extract_timestamp(article["id"])
                    
                    if ts > board_latest_ts:
                        board_latest_ts = ts
                        board_latest_title = article["title"]
                        
                    if not is_first_run and board_last_ts and ts > board_last_ts:
                        board_collected.append({**article, "timestamp": ts, "board": board})

                if is_first_run:
                    # 首次執行只需記錄最新 timestamp，不推播
                    break

                prev_url = find_prev_page_url(html, board)
                if not prev_url:
                    print(f"  [{board}] 找不到上頁連結，停止翻頁")
                    break
                current_url = prev_url
            
            if board_latest_title:
                print(f"[{board}] 目前最新文章：{board_latest_title}")
                # 更新狀態 (只在這裡更新，確保有成功爬完該板)
                last_timestamps[board] = board_latest_ts
                
            all_collected.extend(board_collected)

        await browser.close()

    if all_collected:
        # 依 timestamp 由舊到新排序後推播，確保通知時序正確
        new_articles = sorted(all_collected, key=lambda a: a["timestamp"])
        print(f"\n發現共有 {len(new_articles)} 篇新文章，推播中...")
        for a in new_articles:
            msg = f"[{a['board']}] {a['title']}\n{a['link']}"
            r = send_message(BOT_TOKEN, CHAT_ID, msg, raise_on_error=True)
            print(f"  已送出：[{a['board']}] {a['title']}（{r.status_code}）")
    else:
        print("\n各看板均無新文章。")

    # 統一儲存所有看板最新狀態
    with open(STATE_FILE, "w") as f:
        json.dump({"last_timestamps": last_timestamps}, f)
    print(f"狀態已更新。")


if __name__ == "__main__":
    asyncio.run(main())
