#!/usr/bin/env python3
"""
591租屋網爬蟲
使用 Playwright 抓取多組搜尋結果頁的租屋物件，合併去重後輸出
"""
import asyncio
import csv
import io
import json
import os
from pathlib import Path
import requests
from playwright.async_api import async_playwright


def load_urls_from_sheet():
    sheet_url = os.environ["SHEET_591_URL"]
    resp = requests.get(sheet_url, timeout=10)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    return [row["url"].strip() for row in reader if row.get("url", "").strip()]


URLS = load_urls_from_sheet()

EXTRACT_JS = """
    () => {
        const itemElements = Array.from(document.querySelectorAll('[data-id]'));
        return itemElements.map(item => {
            const dataId = item.getAttribute('data-id');
            const titleEl = item.querySelector('.item-title, [class*="title"]');
            const title = titleEl?.textContent?.trim() || '';
            const priceEl = item.querySelector('.item-price, [class*="price"]');
            const price = priceEl?.textContent?.trim() || '';
            const imgEl = item.querySelector('img');
            const image = imgEl?.getAttribute('src') || imgEl?.getAttribute('data-src') || '';
            const linkEl = item.querySelector('a');
            const link = linkEl?.getAttribute('href') || '';
            const allText = item.textContent?.trim() || '';
            const layoutMatch = allText.match(/(\\d+房\\d+廳)/);
            const layout = layoutMatch ? layoutMatch[1] : '';
            const areaMatch = allText.match(/(\\d+\\.?\\d*坪)/);
            const area = areaMatch ? areaMatch[1] : '';
            const floorMatch = allText.match(/(\\d+F\\/\\d+F)/);
            const floor = floorMatch ? floorMatch[1] : '';
            const regionMatch = allText.match(/(中山區|大安區|信義區|松山區|內湖區|士林區|北投區|大同區|萬華區|中正區|南港區|文山區)-/);
            const region = regionMatch ? regionMatch[1] : '';
            const lineEls = Array.from(item.querySelectorAll('span.line'));
            const updateEl = lineEls.find(el => el.textContent.includes('更新'));
            const updateTime = updateEl ? updateEl.textContent.trim() : '';
            return {
                id: dataId,
                title: title,
                price: price,
                layout: layout,
                area: area,
                floor: floor,
                region: region,
                update_time: updateTime,
                image: image,
                link: link
            };
        });
    }
"""


MGMT_FEE_JS = """
    () => {
        const bodyText = document.body.innerText;
        const match = bodyText.match(/管理費(無|[\\d,]+元\\/月)/);
        return match ? match[1] : '';
    }
"""


async def fetch_detail_data(browser, url: str, item_id: str, screenshots_dir: Path) -> tuple:
    """Fetch management fee and take a screenshot from the detail page.
    Returns (management_fee: str, screenshot_path: str | None).
    """
    if not url or not item_id:
        return '', None
    page = await browser.new_page()
    screenshot_path = None
    try:
        await page.goto(url, wait_until='load', timeout=20000)
        await page.evaluate("window.scrollTo(0, 600)")
        try:
            await page.wait_for_load_state('networkidle', timeout=8000)
        except Exception:
            pass
        mgmt_fee = await page.evaluate(MGMT_FEE_JS)
        try:
            path = screenshots_dir / f"{item_id}.jpg"
            await page.screenshot(path=str(path), type="jpeg", full_page=False)
            screenshot_path = str(path)
        except Exception:
            pass
        return mgmt_fee, screenshot_path
    except Exception:
        return '', None
    finally:
        await page.close()


async def enrich_with_management_fees(browser, items: list) -> None:
    screenshots_dir = Path("screenshots")
    screenshots_dir.mkdir(exist_ok=True)
    semaphore = asyncio.Semaphore(3)

    async def fetch_one(item):
        async with semaphore:
            mgmt_fee, screenshot_path = await fetch_detail_data(
                browser, item.get('link', ''), item.get('id', ''), screenshots_dir
            )
            item['management_fee'] = mgmt_fee
            item['screenshot_path'] = screenshot_path

    await asyncio.gather(*[fetch_one(item) for item in items])


async def crawl_591(browser, url: str) -> list:
    """單一網址爬取，回傳物件列表"""
    page = await browser.new_page()
    print(f"正在訪問: {url}")
    await page.goto(url)
    await page.wait_for_timeout(2000)
    try:
        close_button = page.locator('button:has-text("×")').first
        if await close_button.is_visible():
            await close_button.click()
    except:
        pass
    await page.evaluate("window.scrollTo(0, 1200)")
    await page.wait_for_timeout(3000)
    items = await page.evaluate(EXTRACT_JS)
    await page.close()
    print(f"  抓到 {len(items)} 筆")
    return items


async def main():
    all_items = []
    seen_ids = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for url in URLS:
            items = await crawl_591(browser, url)
            for item in items:
                if item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    all_items.append(item)
        print(f"\n正在抓取 {len(all_items)} 筆物件的管理費資訊...")
        await enrich_with_management_fees(browser, all_items)
        await browser.close()

    print(f"\n合計抓取 {len(all_items)} 筆（已去重）\n")
    print("=" * 80)
    for idx, item in enumerate(all_items, 1):
        print(f"\n物件 {idx}:")
        print(f"  ID: {item['id']}")
        print(f"  標題: {item['title']}")
        print(f"  價格: {item['price']}")
        print(f"  房型: {item['layout']}")
        print(f"  坪數: {item['area']}")
        print(f"  樓層: {item['floor']}")
        print(f"  地區: {item['region']}")
        print(f"  更新時間: {item['update_time']}")
        print(f"  連結: {item['link']}")

    output_file = "591_rent_data.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)
    print(f"\n資料已儲存至: {output_file}")
    print(f"總共抓取: {len(all_items)} 筆物件")


if __name__ == "__main__":
    asyncio.run(main())
