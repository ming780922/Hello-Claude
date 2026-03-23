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
PTT_INDEX = f"{PTT_BASE}/bbs/LifeIsMoney/index.html"
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


def find_prev_page_url(html_content: str) -> str | None:
    """找「上頁」按鈕的連結"""
    m = re.search(r'<a[^>]+href="(/bbs/LifeIsMoney/index\d+\.html)"[^>]*>\s*‹ 上頁', html_content)
    if m:
        return PTT_BASE + m.group(1)
    # 備用：找 class="btn wide" 的上頁
    m = re.search(r'href="(/bbs/LifeIsMoney/index\d+\.html)"[^>]*>[^<]*上頁', html_content)
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
        last_timestamp = state.get("last_timestamp")
    except FileNotFoundError:
        last_timestamp = None

    is_first_run = last_timestamp is None
    print(f"上次最後文章 timestamp：{last_timestamp or '（首次執行）'}")

    collected = []  # timestamp > last_timestamp 的新文章
    latest_timestamp = last_timestamp or 0
    latest_title = None

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

        current_url = PTT_INDEX
        for page_num in range(MAX_PAGES):
            html = await fetch_page(page, current_url)
            articles = parse_articles(html)
            print(f"  本頁解析到 {len(articles)} 篇文章")

            if not articles:
                print("  本頁無文章，停止翻頁")
                break

            for article in articles:
                ts = extract_timestamp(article["id"])
                if ts > latest_timestamp:
                    latest_timestamp = ts
                    latest_title = article["title"]
                if not is_first_run and last_timestamp and ts > last_timestamp:
                    collected.append({**article, "timestamp": ts})

            if is_first_run:
                # 首次執行只需記錄最新 timestamp，不推播
                break

            prev_url = find_prev_page_url(html)
            if not prev_url:
                print("  找不到上頁連結，停止翻頁")
                break
            current_url = prev_url

        await browser.close()

    if latest_title:
        print(f"目前最新文章：{latest_title}")

    if is_first_run:
        print(f"首次執行，記錄最新文章 timestamp：{latest_timestamp}，不推播。")
    elif collected:
        # 依 timestamp 由舊到新排序後推播
        new_articles = sorted(collected, key=lambda a: a["timestamp"])
        print(f"發現 {len(new_articles)} 篇新文章，推播中...")
        for a in new_articles:
            msg = f'{a["title"]}\n{a["link"]}'
            r = send_message(BOT_TOKEN, CHAT_ID, msg, raise_on_error=True)
            print(f"  已送出：{a['title']}（{r.status_code}）")
    else:
        print("無新文章。")

    # 更新狀態
    if latest_timestamp:
        with open(STATE_FILE, "w") as f:
            json.dump({"last_timestamp": latest_timestamp}, f)
        print(f"狀態已更新，last_timestamp = {latest_timestamp}")


if __name__ == "__main__":
    asyncio.run(main())
