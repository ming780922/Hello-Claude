# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git Workflow Rules
- 每次實作新功能前，必須先確認目前在 main branch
- 如果不在 main，先問我要不要切回去
- 新功能一定要從 main 開新 branch，命名格式：feature/功能名稱
- PR merge 後，下個任務開始前先切回 main 並 pull

## Commands

### Python Scripts
```bash
pip install -r requirements.txt
playwright install chromium --with-deps   # Required for Playwright-based scripts

python crawler_591.py          # Crawl 591 rent listings → 591_rent_data.json
python notify_telegram.py      # Send 591 results to Telegram (requires env vars)
python donate_notify.py        # Scrape blood donation activity images → Telegram
python ptt_rss_monitor.py      # Monitor PTT RSS feed → Telegram
python ptt_crawler.py          # Playwright-based PTT direct crawler → Telegram
python yt_channel_monitor.py   # Monitor YouTube channel → Telegram
python crawler_fb_group.py     # Scrape public FB group → fb_group_data.json
python notify_fb_group.py      # Send FB group results to Telegram (requires env vars)
# crawler_591_bot.py is triggered only via GitHub Actions with SUBSCRIPTIONS env var
python export_to_sheet.py      # Export saved listings to Google Sheet (triggered via /export Telegram command)
```

### Cloudflare Worker
```bash
npx wrangler deploy            # Deploy worker.js to Cloudflare
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put GITHUB_TOKEN
```

## Architecture

This project is a **Telegram Bot automation system** with the following flow:

```
Telegram Bot commands / Scheduled triggers
    │
    ▼
Cloudflare Worker (worker.js)
    │  Receives Telegram webhook POSTs and cron triggers
    │  Routes to GitHub repository_dispatch events
    ▼
GitHub Actions (.github/workflows/)
    │  Runs Python scripts on ubuntu-latest runners
    ▼
Telegram Bot API  (sends results back to user)
```

### Components

**`worker.js`** — Cloudflare Worker handling two entry points:
- `fetch()`: Telegram webhook receiver; routes `/echo`, `/donate`, `/591`, `/fb` commands to GitHub dispatch events. Also proxies PTT RSS feed at `GET /rss/LifeIsMoney` (bypasses PTT IP blocks).
- `scheduled()`: Three cron schedules (see `wrangler.toml`):
  - `*/5 * * * *` → `cron-ptt-crawler`
  - `0 0-16 * * *` → `cron-591-rent`
  - `0 1 * * *` → `cron-fb-group`

**Python scripts** — each is a standalone script run by GitHub Actions:
- `crawler_591.py`: Uses Playwright to scrape rent.591.com.tw; deduplicates by item ID; persists state in `591_storage.json` / `591_seen_history.json` (GitHub Actions cache); outputs `591_rent_data.json`.
- `crawler_591_bot.py`: Bot-driven variant; reads `SUBSCRIPTIONS` JSON env var (list of `{chat_id, urls, force_send_all, hidden_items, hidden_titles}`); takes per-listing screenshots; sends inline "hide" buttons via Telegram.
- `notify_telegram.py`: Reads `591_rent_data.json` and sends formatted results to Telegram.
- `donate_notify.py`: Uses Playwright to scrape weekend blood donation activity images from tp.blood.org.tw and sends them via Telegram.
- `ptt_rss_monitor.py`: Fetches PTT LifeIsMoney Atom feed via the Worker proxy, tracks seen article IDs in `/tmp/ptt_rss_state.json`, pushes new posts to Telegram.
- `ptt_crawler.py`: Playwright-based direct PTT scraper (no RSS/proxy); monitors LifeIsMoney, creditcard, Rent_apart boards; tracks per-board last timestamp in `/tmp/ptt_crawler_state.json` (GitHub Actions cache); skips first-run notifications.
- `yt_channel_monitor.py`: Fetches YouTube channel RSS feed, filters by `YT_KEYWORD`, tracks seen video IDs in `/tmp/yt_state.json`, pushes matching new videos to Telegram.
- `crawler_fb_group.py`: Scrapes public Facebook group for previous day's posts; tries main site first, falls back to mbasic.facebook.com; outputs `fb_group_data.json`.
- `notify_fb_group.py`: Reads `fb_group_data.json` and sends batched results to Telegram.
- `telegram_utils.py`: Shared utility with `send_message()`, `send_photo_bytes()`, `send_batched()`. All scripts import from here.

### Required GitHub Secrets

| Secret | Used by |
|---|---|
| `TELEGRAM_BOT_TOKEN` | All workflows |
| `TELEGRAM_DEFAULT_CHAT_ID` | 591-rent, ptt-rss, ptt-crawler, yt-monitor (fallback when no chat_id in payload) |
| `CHAT_ID` | donate, ptt-rss, ptt-crawler workflows |
| `TELEGRAM_CHAT_ID` | fb-group workflow |
| `WORKER_URL` | ptt-rss (points to Cloudflare Worker URL for RSS proxy) |
| `YT_CHANNEL_ID` | yt-monitor |
| `YT_KEYWORD` | yt-monitor |
| `SHEET_591_URL` | 591-rent (Google Sheet URL for subscription data) |
| `COOKIES_591_JSON` | 591-rent (session cookies for crawler_591.py, see `591_cookies_template.json`) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | export-to-sheet (GCP service account JSON with Google Sheets API access) |
| `EXPORT_SHEET_ID` | export-to-sheet (Google Sheet ID to export saved listings into; share sheet with service account email) |

### Cloudflare Worker Environment Variables

Set via `wrangler secret put` (not in `wrangler.toml`):
- `TELEGRAM_BOT_TOKEN`
- `GITHUB_TOKEN` (needs `repo` scope for dispatches)
- `GITHUB_REPO` (set in wrangler.toml as `ming780922/Hello-Claude`)
