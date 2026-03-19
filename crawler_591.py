#!/usr/bin/env python3
"""
591租屋網爬蟲
使用 Playwright 抓取多組搜尋結果頁的租屋物件，合併去重後輸出
"""
import asyncio
import json
from playwright.async_api import async_playwright

# 目標網址清單
URLS = [
    "https://rent.591.com.tw/list?region=1&section=1&kind=1&layout=2,1&other=pet&notice=not_cover&sort=posttime_desc",
    "https://rent.591.com.tw/list?region=1&section=2&kind=1&layout=2,1&other=pet&notice=not_cover&sort=posttime_desc",
    "https://rent.591.com.tw/list?region=1&section=3&kind=1&layout=2,1&other=pet&notice=not_cover&sort=posttime_desc",
    "https://rent.591.com.tw/list?region=1&section=4&kind=1&layout=2,1&other=pet&notice=not_cover&sort=posttime_desc",
    "https://rent.591.com.tw/list?region=1&section=5&kind=1&layout=2,1&other=pet&notice=not_cover&sort=posttime_desc",
    "https://rent.591.com.tw/list?region=1&section=6&kind=1&layout=2,1&other=pet&notice=not_cover&sort=posttime_desc",
    "https://rent.591.com.tw/list?region=1&section=7&kind=1&layout=2,1&other=pet&notice=not_cover&sort=posttime_desc",
    "https://rent.591.com.tw/list?region=1&section=12&kind=1&layout=2,1&other=pet&notice=not_cover&sort=posttime_desc",
    "https://rent.591.com.tw/list?region=3&section=34&kind=1&layout=2,1&other=pet&notice=not_cover&sort=posttime_desc",
]

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
