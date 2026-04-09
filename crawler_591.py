#!/usr/bin/env python3
"""
591租屋網爬蟲
使用 Playwright 抓取多組搜尋結果頁的租屋物件，合併去重後輸出
"""
import asyncio
import csv
import io
import os
import json
from datetime import datetime
from pathlib import Path
import requests
from playwright.async_api import async_playwright


def load_urls_from_sheet():
    sheet_url = os.environ["SHEET_591_URL"]
    resp = requests.get(sheet_url, timeout=10)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    return [row["url"].strip() for row in reader if row.get("url", "").strip()]

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
            const regionMatch = allText.match(/([^\\s]{2,4}[區鄉鎮])/);
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
                link: link,
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


def log(message: str):
    """帶時間戳記的 Log"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {message}")


async def fetch_detail_data(context, url: str, item_id: str, screenshots_dir: Path) -> tuple:
    """Fetch management fee and take a screenshot from the detail page.
    Returns (management_fee: str, screenshot_path: str | None).
    """
    if not url or not item_id:
        return '', None
    page = await context.new_page()
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
            await page.evaluate("window.scrollTo(0, 0)")
            await page.screenshot(path=str(path), type="jpeg", quality=85, full_page=False)
            screenshot_path = str(path)
        except Exception:
            pass
        return mgmt_fee, screenshot_path
    except Exception:
        return '', None
    finally:
        await page.close()


async def enrich_with_management_fees(context, items: list) -> None:
    screenshots_dir = Path("screenshots")
    screenshots_dir.mkdir(exist_ok=True)
    semaphore = asyncio.Semaphore(3)

    async def fetch_one(item):
        async with semaphore:
            item_url = item.get('link', '')
            item_id = item.get('id', '')
            log(f"    正在抓取詳細資料 [{item_id}]: {item.get('title')}")
            mgmt_fee, screenshot_path = await fetch_detail_data(
                context, item_url, item_id, screenshots_dir
            )
            item['management_fee'] = mgmt_fee
            item['screenshot_path'] = screenshot_path

    await asyncio.gather(*[fetch_one(item) for item in items])


async def crawl_591(context, url: str) -> list:
    """爬取所有分頁，回傳所有物件列表"""
    all_items = []
    max_pages = 50

    for page_idx in range(max_pages):
        first_row = page_idx * 30
        sep = "&" if "?" in url else "?"
        page_url = f"{url}{sep}firstRow={first_row}"

        page = await context.new_page()
        log(f"訪問列表 (第 {page_idx + 1} 頁): {page_url}")

        try:
            await page.goto(page_url)
            await page.wait_for_timeout(2000)
            try:
                close_button = page.locator('button:has-text("×")').first
                if await close_button.is_visible():
                    await close_button.click()
            except Exception:
                pass

            await page.evaluate("window.scrollTo(0, 1200)")
            await page.wait_for_timeout(3000)
            items = await page.evaluate(EXTRACT_JS)
            log(f"  第 {page_idx + 1} 頁抓到 {len(items)} 筆")

            if not items:
                log(f"  第 {page_idx + 1} 頁無資料，停止換頁")
                break

            all_items.extend(items)

            if len(items) < 30:
                log("  已到達最後一頁")
                break

        except Exception as e:
            log(f"  抓取分頁 {page_idx + 1} 失敗: {e}")
        finally:
            await page.close()

    return all_items


def load_cookies_or_storage():
    """載入 cookies 或 storage state"""
    storage_file = Path("591_storage.json")
    if storage_file.exists():
        log(f"找到瀏覽器狀態檔: {storage_file}")
        return {"storage_state": str(storage_file)}
    
    # 如果沒有 storage 檔，嘗試從 591_cookies.json 載入 (用於初始登入)
    cookie_file = Path("591_cookies.json")
    if cookie_file.exists():
        try:
            with open(cookie_file, "r") as f:
                cookies = json.load(f)
                log(f"從 {cookie_file} 注入 {len(cookies)} 個初始 cookies")
                return {"cookies": cookies}
        except Exception as e:
            log(f"載入 Cookies 失敗: {e}")
            
    # 最後嘗試從環境變數載入 (適合 CI)
    env_cookies = os.environ.get("591_COOKIES_JSON")
    if env_cookies:
        try:
            cookies = json.loads(env_cookies)
            log(f"從環境變數注入 {len(cookies)} 個初始 cookies")
            return {"cookies": cookies}
        except Exception as e:
            log(f"從環境變數載入 Cookies 失敗: {e}")
            
    log("未找到任何登入資訊，將以遊客身份爬取")
    return {}


def load_history():
    """載入歷史看過的 ID"""
    history_file = Path("591_seen_history.json")
    if history_file.exists():
        try:
            with open(history_file, "r") as f:
                history = set(json.load(f))
                log(f"找到歷史記錄，載入 {len(history)} 筆已看過的 ID")
                return history
        except Exception as e:
            log(f"載入歷史記錄失敗: {e}")
    return set()


def save_history(history):
    """儲存歷史看過的 ID"""
    try:
        with open("591_seen_history.json", "w") as f:
            json.dump(list(history), f)
        log(f"已更新歷史記錄 (目前共 {len(history)} 筆)")
    except Exception as e:
        log(f"儲存歷史記錄失敗: {e}")


async def main():
    log("開始執行 591 爬蟲程式...")

    urls = load_urls_from_sheet()
    log(f"共載入 {len(urls)} 個搜尋 URL")

    all_items = []
    all_time_seen = load_history()
    seen_ids: set[str] = set()

    async with async_playwright() as p:
        log("啟動 Playwright 瀏覽器...")
        browser = await p.chromium.launch(headless=True)

        setup_params = load_cookies_or_storage()

        if "storage_state" in setup_params:
            context = await browser.new_context(storage_state=setup_params["storage_state"])
        else:
            context = await browser.new_context()
            if "cookies" in setup_params:
                await context.add_cookies(setup_params["cookies"])

        for url in urls:
            items = await crawl_591(context, url)
            for item in items:
                item_id = item["id"]
                if item_id in all_time_seen or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                all_time_seen.add(item_id)
                all_items.append(item)

        if all_items:
            log(f"本次發現 {len(all_items)} 筆新物件，開始抓取詳細資訊...")
            await enrich_with_management_fees(context, all_items)
        else:
            log("未發現任何新物件。")

        # 無論有無新物件，都儲存 state
        await context.storage_state(path="591_storage.json")
        log("已更新瀏覽器狀態至: 591_storage.json")
        save_history(all_time_seen)

        await browser.close()

    output_file = "591_rent_data.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)
    print(f"\n資料已儲存至: {output_file}，共 {len(all_items)} 筆物件")

    if not all_items:
        return

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


if __name__ == "__main__":
    asyncio.run(main())
