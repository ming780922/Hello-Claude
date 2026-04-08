#!/usr/bin/env python3
"""
591租屋網爬蟲 — Telegram Bot 版
從 GitHub Actions workflow_dispatch input 讀取訂閱清單
爬完後直接推播給對應的 Telegram chat_id
"""
import asyncio
import json
import os
import httpx
from pathlib import Path
from playwright.async_api import async_playwright

SUBSCRIPTIONS: list[dict] = json.loads(os.environ["SUBSCRIPTIONS"])
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

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
            const lineEls = Array.from(item.querySelectorAll('span.line'));
            const updateEl = lineEls.find(el => el.textContent.includes('更新'));
            const updateTime = updateEl ? updateEl.textContent.trim() : '';
            const regionMatch = allText.match(/([^\s]+區)/);
            const region = regionMatch ? regionMatch[1] : '';
            return { id: dataId, title, price, layout, area, floor,
                     update_time: updateTime, image, link, region };
        });
    }
"""


async def crawl_591(browser, url: str) -> list:
    all_page_items = []
    max_pages = 50
    
    for page_idx in range(max_pages):
        first_row = page_idx * 30
        page_url = f"{url}&firstRow={first_row}" if "?" in url else f"{url}?firstRow={first_row}"
        
        page = await browser.new_page()
        print(f"  訪問 (第 {page_idx + 1} 頁): {page_url}")
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
            print(f"    -> 本頁抓到 {len(items)} 筆")
            
            if not items:
                break
                
            all_page_items.extend(items)
            
            if len(items) < 30:
                break
        finally:
            await page.close()
            
    return all_page_items


async def fetch_screenshot(browser, url: str, item_id: str, screenshots_dir: Path) -> str | None:
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until='load', timeout=15000)
        await page.evaluate("window.scrollTo(0, 600)")
        await page.wait_for_timeout(2500)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)
        path = screenshots_dir / f"{item_id}.jpg"
        await page.screenshot(path=str(path), type='jpeg', quality=85)
        return str(path)
    except Exception as e:
        print(f"  截圖失敗 {item_id}: {e}")
        return None
    finally:
        await page.close()


async def enrich_with_screenshots(browser, items: list) -> None:
    screenshots_dir = Path("screenshots")
    screenshots_dir.mkdir(exist_ok=True)
    sem = asyncio.Semaphore(3)

    async def capture(item):
        async with sem:
            link = item.get('link', '')
            if link and not link.startswith('http'):
                link = f"https://rent.591.com.tw{link}"
            item['screenshot_path'] = await fetch_screenshot(
                browser, link, item['id'], screenshots_dir
            ) if link else None

    await asyncio.gather(*[capture(item) for item in items])


def format_item(item: dict) -> str:
    title = item.get('title') or '（無標題）'
    link = item.get('link', '')
    if link and not link.startswith('http'):
        link = f"https://rent.591.com.tw{link}"
    meta_parts = [
        item.get('region', ''),
        item.get('layout', ''),
        item.get('area', ''),
        item.get('floor', ''),
        item.get('price', ''),
        item.get('update_time', ''),
    ]
    meta = ' · '.join(p for p in meta_parts if p)
    return f"🏠 <b>{title}</b>\n{meta}\n{link}"


async def send_telegram_summary(chat_id: str, count: int) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        if count == 0:
            resp = await client.post(f"{TELEGRAM_API}/sendMessage", json={
                "chat_id": chat_id,
                "text": "🔍 本次搜尋沒有發現符合條件的新房屋。",
            })
            return
            
        resp = await client.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": f"🔍 此次掃描共找到 {count} 筆符合條件的新房源。",
            "reply_markup": {
                "inline_keyboard": [
                    [{"text": f"載入所有房屋資料與截圖", "callback_data": "fetch_all"}]
                ]
            }
        })
        print(f"  摘要推播狀態: {resp.status_code} {resp.text}")

async def send_telegram_full(chat_id: str, items: list) -> None:
    if not items:
        print(f"  [chat_id={chat_id}] 無新結果，跳過推播")
        return

    async with httpx.AsyncClient(timeout=30) as client:
        # 每筆獨立推播（無數量限制）
        for item in items:
            caption = format_item(item)
            screenshot_path = item.get('screenshot_path')
            
            inline_keyboard = {"inline_keyboard": [[{"text": "🚫 不要再顯示此物件", "callback_data": f"hide:{item['id']}"}]]}
            reply_markup_json = json.dumps(inline_keyboard)

            if screenshot_path and Path(screenshot_path).exists():
                try:
                    with open(screenshot_path, 'rb') as f:
                        resp = await client.post(
                            f"{TELEGRAM_API}/sendPhoto",
                            data={
                                "chat_id": chat_id, 
                                "caption": caption, 
                                "parse_mode": "HTML", 
                                "reply_markup": reply_markup_json
                            },
                            files={"photo": f},
                        )
                    print(f"  推播狀態(photo): {resp.status_code} | {resp.text[:100]}")
                except Exception as e:
                    print(f"  sendPhoto 失敗，fallback sendMessage: {e}")
                    resp = await client.post(f"{TELEGRAM_API}/sendMessage", json={
                        "chat_id": chat_id,
                        "text": caption,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": False,
                        "reply_markup": inline_keyboard
                    })
                    print(f"  推播狀態(fallback): {resp.status_code} | {resp.text[:100]}")
            else:
                resp = await client.post(f"{TELEGRAM_API}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": caption,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                    "reply_markup": inline_keyboard
                })
                print(f"  推播狀態(text): {resp.status_code} | {resp.text[:100]}")

            await asyncio.sleep(1.0)  # 放慢推播速度避免被擋


async def main():
    print(f"開始處理 {len(SUBSCRIPTIONS)} 個訂閱")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for sub in SUBSCRIPTIONS:
            chat_id = str(sub["chat_id"])
            urls: list[str] = sub["urls"]
            force_send = sub.get("force_send_all", False)
            hidden_items = set(sub.get("hidden_items", []))
            hidden_titles = set(sub.get("hidden_titles", []))
            print(f"\n[chat_id={chat_id}] 共 {len(urls)} 個 URL (force_send={force_send})")

            try:
                all_items = []
                seen_ids: set[str] = set()

                for url in urls:
                    items = await crawl_591(browser, url)
                    for item in items:
                        if item["id"] in hidden_items or item["title"] in hidden_titles:
                            continue
                        if item["id"] not in seen_ids:
                            seen_ids.add(item["id"])
                            all_items.append(item)

                print(f"  合計 {len(all_items)} 筆（去重過濾後）")
                
                if force_send:
                    await enrich_with_screenshots(browser, all_items)
                    await send_telegram_full(chat_id, all_items)
                else:
                    await send_telegram_summary(chat_id, len(all_items))
                    
                print(f"  [OK] 推播完成")

            except Exception as e:
                print(f"  [ERROR] chat_id={chat_id} 失敗，跳過：{e}")
                continue

        await browser.close()

    print("\n全部完成")


if __name__ == "__main__":
    asyncio.run(main())
