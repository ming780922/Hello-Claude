#!/usr/bin/env python3
"""
591租屋網爬蟲 (requests 版)
使用 requests + BeautifulSoup 解析 SSR HTML，不依賴 Playwright
"""
import asyncio
import csv
import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-TW,zh;q=0.9",
}


def log(message: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {message}")


def load_urls_from_sheet():
    sheet_url = os.environ["SHEET_591_URL"]
    resp = requests.get(sheet_url, timeout=10)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    return [row["url"].strip() for row in reader if row.get("url", "").strip()]


def parse_items(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for item in soup.find_all(attrs={"data-id": True}):
        item_id = item.get("data-id", "")
        if not item_id:
            continue

        info = item.find(class_="item-info")
        if not info:
            continue

        # Title & link
        title_a = info.find("a", class_=lambda c: c and "link" in c)
        title = title_a.get_text(strip=True) if title_a else ""
        link = title_a.get("href", "") if title_a else ""

        # Price
        price_strong = info.find("strong", class_=lambda c: c and "text-26px" in c)
        price_span = info.find("span", class_=lambda c: c and "text-14px" in c)
        price = ""
        if price_strong:
            price = price_strong.get_text(strip=True)
            if price_span:
                price += price_span.get_text(strip=True)

        # Layout lines: type, layout, area, floor
        info_txts = info.find_all(class_="item-info-txt")
        layout = area = floor = kind = address = ""
        for txt in info_txts:
            lines = [s.get_text(strip=True) for s in txt.find_all(class_="line")]
            # House type txt has an icon with class house-home
            if txt.find("i", class_=lambda c: c and "house-home" in c):
                spans = [s.get_text(strip=True) for s in txt.find_all("span", recursive=False)]
                kind = spans[0] if spans else ""
                if len(lines) >= 1:
                    layout = lines[0]
                if len(lines) >= 2:
                    area = lines[1]
                if len(lines) >= 3:
                    floor = lines[2]
            # Address txt has icon with class house-place
            elif txt.find("i", class_=lambda c: c and "house-place" in c):
                address = txt.get_text(strip=True)

        # Update time — last span.line in role-name div
        update_time = ""
        role_div = info.find(class_=lambda c: c and "role-name" in c)
        if role_div:
            line_spans = role_div.find_all(class_="line")
            if line_spans:
                update_time = line_spans[0].get_text(strip=True)

        # Image
        img = item.find("img", class_="common-img")
        image = img.get("data-src", "") if img else ""

        # Region from address (e.g. "中山區")
        region_match = re.search(r"([^\s]{2,4}[區鄉鎮])", address)
        region = region_match.group(1) if region_match else ""

        results.append({
            "id": item_id,
            "title": title,
            "price": price,
            "kind": kind,
            "layout": layout,
            "area": area,
            "floor": floor,
            "region": region,
            "address": address,
            "update_time": update_time,
            "image": image,
            "link": link,
        })

    return results


def fetch_page(url: str, page_idx: int) -> list:
    sep = "&" if "?" in url else "?"
    page_url = f"{url}{sep}firstRow={page_idx * 30}"
    log(f"訪問列表 (第 {page_idx + 1} 頁): {page_url}")
    try:
        r = requests.get(page_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        items = parse_items(r.text)
        log(f"  第 {page_idx + 1} 頁抓到 {len(items)} 筆")
        return items
    except Exception as e:
        log(f"  抓取分頁 {page_idx + 1} 失敗: {e}")
        return []


def crawl_591(url: str) -> list:
    all_items = []
    for page_idx in range(50):
        items = fetch_page(url, page_idx)
        if not items:
            log(f"  第 {page_idx + 1} 頁無資料，停止換頁")
            break
        all_items.extend(items)
        if len(items) < 30:
            log("  已到達最後一頁")
            break
    return all_items


def fetch_management_fee(item: dict) -> None:
    url = item.get("link", "")
    item_id = item.get("id", "")
    if not url or not item_id:
        item["management_fee"] = ""
        return
    log(f"    正在抓取詳細資料 [{item_id}]: {item.get('title')}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        match = re.search(r"管理費(無|[\d,]+元/月)", r.text)
        item["management_fee"] = match.group(1) if match else ""
    except Exception:
        item["management_fee"] = ""


def enrich_with_management_fees(items: list) -> None:
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(fetch_management_fee, items))


def load_history() -> set:
    history_file = Path("591_seen_history.json")
    if history_file.exists():
        try:
            with open(history_file) as f:
                history = set(json.load(f))
                log(f"找到歷史記錄，載入 {len(history)} 筆已看過的 ID")
                return history
        except Exception as e:
            log(f"載入歷史記錄失敗: {e}")
    return set()


def save_history(history: set) -> None:
    try:
        with open("591_seen_history.json", "w") as f:
            json.dump(list(history), f)
        log(f"已更新歷史記錄 (目前共 {len(history)} 筆)")
    except Exception as e:
        log(f"儲存歷史記錄失敗: {e}")


def main():
    log("開始執行 591 爬蟲程式 (requests 版)...")

    urls = load_urls_from_sheet()
    log(f"共載入 {len(urls)} 個搜尋 URL")

    all_time_seen = load_history()
    seen_ids: set = set()
    all_items = []

    for url in urls:
        items = crawl_591(url)
        for item in items:
            item_id = item["id"]
            if item_id in all_time_seen or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            all_time_seen.add(item_id)
            all_items.append(item)

    if all_items:
        log(f"本次發現 {len(all_items)} 筆新物件，開始抓取詳細資訊...")
        enrich_with_management_fees(all_items)
    else:
        log("未發現任何新物件。")

    save_history(all_time_seen)

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
        print(f"  地址: {item['address']}")
        print(f"  管理費: {item['management_fee']}")
        print(f"  更新時間: {item['update_time']}")
        print(f"  連結: {item['link']}")


if __name__ == "__main__":
    main()
