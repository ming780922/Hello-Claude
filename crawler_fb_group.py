#!/usr/bin/env python3
"""
Facebook 社團爬蟲（無登入，公開社團）
抓取前一天發布或更新的文章，輸出至 fb_group_data.json
"""
import asyncio
import json
from datetime import datetime, timezone, timedelta

from playwright.async_api import async_playwright

GROUP_URL = "https://www.facebook.com/groups/471259550067709/"
MBASIC_URL = "https://mbasic.facebook.com/groups/471259550067709/"

TZ_TW = timezone(timedelta(hours=8))


def get_yesterday_range():
    now = datetime.now(TZ_TW)
    yesterday = (now - timedelta(days=1)).date()
    start = int(datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=TZ_TW).timestamp())
    end = start + 86400
    return start, end


EXTRACT_JS = """
    (yesterdayStart, yesterdayEnd) => {
        const results = [];
        const seen = new Set();

        // 找所有含 data-utime 的時間元素
        const timeEls = Array.from(document.querySelectorAll('[data-utime]'));
        for (const timeEl of timeEls) {
            const utime = parseInt(timeEl.getAttribute('data-utime'), 10);
            if (isNaN(utime) || utime < yesterdayStart || utime >= yesterdayEnd) continue;

            // 向上找文章容器
            let post = timeEl.closest('[data-pagelet^="FeedUnit"]') ||
                       timeEl.closest('[role="article"]') ||
                       timeEl.closest('div[id^="mall_post"]');
            if (!post) continue;

            const postId = post.getAttribute('data-pagelet') || post.id || String(utime);
            if (seen.has(postId)) continue;
            seen.add(postId);

            // 作者
            const authorEl = post.querySelector('h2 a, h3 a, strong a, [data-hovercard] a');
            const author = authorEl ? authorEl.textContent.trim() : '';

            // 文章連結
            const linkEl = timeEl.closest('a') || post.querySelector('a[href*="/permalink/"], a[href*="/posts/"]');
            let url = linkEl ? linkEl.getAttribute('href') : '';
            if (url && url.startsWith('/')) url = 'https://www.facebook.com' + url;

            // 文章內容（取最長的文字區塊）
            const contentCandidates = Array.from(post.querySelectorAll('div[data-ad-preview="message"], div[dir="auto"], [data-testid="post_message"]'));
            let content = '';
            for (const el of contentCandidates) {
                const text = el.innerText || el.textContent || '';
                if (text.trim().length > content.length) content = text.trim();
            }
            if (!content) {
                content = post.innerText ? post.innerText.substring(0, 300).trim() : '';
            }

            results.push({
                utime: utime,
                author: author,
                content: content.substring(0, 500),
                url: url
            });
        }
        return results;
    }
"""

MBASIC_EXTRACT_JS = """
    (yesterdayStart, yesterdayEnd) => {
        const results = [];
        const seen = new Set();

        // mbasic 版本：找 abbr[data-utime] 或解析時間文字
        const abbrs = Array.from(document.querySelectorAll('abbr[data-utime]'));
        for (const abbr of abbrs) {
            const utime = parseInt(abbr.getAttribute('data-utime'), 10);
            if (isNaN(utime) || utime < yesterdayStart || utime >= yesterdayEnd) continue;

            // 找最近的文章區塊
            let post = abbr.closest('div[id]');
            if (!post) continue;

            const postId = post.id || String(utime);
            if (seen.has(postId)) continue;
            seen.add(postId);

            // 作者
            const authorEl = post.querySelector('h3 a, h2 a, strong a');
            const author = authorEl ? authorEl.textContent.trim() : '';

            // 連結
            const linkEl = abbr.closest('a') || post.querySelector('a[href*="story_fbid"], a[href*="/permalink/"]');
            let url = linkEl ? linkEl.getAttribute('href') : '';
            if (url && url.startsWith('/')) url = 'https://www.facebook.com' + url;

            // 內容
            const contentEl = post.querySelector('div[data-ft], p');
            const content = contentEl ? contentEl.innerText || contentEl.textContent || '' : '';

            results.push({
                utime: utime,
                author: author,
                content: content.substring(0, 500).trim(),
                url: url
            });
        }
        return results;
    }
"""


async def dismiss_popups(page):
    """嘗試關閉 Facebook 登入彈窗"""
    selectors = [
        '[aria-label="關閉"]',
        '[aria-label="Close"]',
        'div[role="dialog"] [data-testid="royal_close_button"]',
        'div[role="dialog"] button[type="button"]:last-child',
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass


async def crawl_main(browser, yesterday_start, yesterday_end) -> list:
    """嘗試從主站抓取"""
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        locale="zh-TW",
    )
    page = await context.new_page()
    print(f"訪問: {GROUP_URL}")
    await page.goto(GROUP_URL, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    # 關閉彈窗
    await dismiss_popups(page)
    await page.wait_for_timeout(1000)

    # 滾動載入更多文章（最多滾動 10 次）
    prev_height = 0
    for i in range(10):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        height = await page.evaluate("document.body.scrollHeight")
        await dismiss_popups(page)
        if height == prev_height:
            break
        prev_height = height
        print(f"  滾動 {i+1} 次，頁面高度: {height}")

    items = await page.evaluate(EXTRACT_JS, yesterday_start, yesterday_end)
    await context.close()
    print(f"  主站找到 {len(items)} 筆昨天的文章")
    return items


async def crawl_mbasic(browser, yesterday_start, yesterday_end) -> list:
    """使用 mbasic 版本抓取"""
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36",
        locale="zh-TW",
    )
    page = await context.new_page()
    print(f"Fallback - 訪問: {MBASIC_URL}")

    all_items = []
    url = MBASIC_URL
    for page_num in range(5):
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        items = await page.evaluate(MBASIC_EXTRACT_JS, yesterday_start, yesterday_end)
        all_items.extend(items)
        print(f"  mbasic 第 {page_num+1} 頁找到 {len(items)} 筆")

        # 找下一頁連結
        next_link = await page.query_selector('a:has-text("查看更多"), a:has-text("See More"), #m_more_item a')
        if not next_link:
            break
        href = await next_link.get_attribute("href")
        if not href:
            break
        url = "https://mbasic.facebook.com" + href if href.startswith("/") else href

    await context.close()
    print(f"  mbasic 共找到 {len(all_items)} 筆昨天的文章")
    return all_items


async def main():
    yesterday_start, yesterday_end = get_yesterday_range()
    yesterday_str = datetime.fromtimestamp(yesterday_start, tz=TZ_TW).strftime("%Y-%m-%d")
    print(f"抓取日期：{yesterday_str}（Unix {yesterday_start} ~ {yesterday_end}）")

    all_items = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # 先嘗試主站
        try:
            items = await crawl_main(browser, yesterday_start, yesterday_end)
            all_items = items
        except Exception as e:
            print(f"主站爬取失敗: {e}")

        # 若主站無結果，fallback 到 mbasic
        if not all_items:
            try:
                items = await crawl_mbasic(browser, yesterday_start, yesterday_end)
                all_items = items
            except Exception as e:
                print(f"mbasic 爬取失敗: {e}")

        await browser.close()

    # 去重（依 utime + author）
    seen = set()
    deduped = []
    for item in all_items:
        key = (item["utime"], item["author"])
        if key not in seen:
            seen.add(key)
            # 加入可讀時間
            dt = datetime.fromtimestamp(item["utime"], tz=TZ_TW)
            item["time_str"] = dt.strftime("%Y-%m-%d %H:%M")
            deduped.append(item)

    deduped.sort(key=lambda x: x["utime"])
    print(f"\n合計找到 {len(deduped)} 筆昨天（{yesterday_str}）的文章")

    output_file = "fb_group_data.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)
    print(f"資料已儲存至: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
