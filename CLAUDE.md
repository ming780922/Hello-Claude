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
python yt_channel_monitor.py   # Monitor YouTube channel → Telegram
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
- `fetch()`: Telegram webhook receiver; routes `/echo`, `/donate`, `/591` commands to GitHub dispatch events. Also proxies PTT RSS feed at `GET /rss/LifeIsMoney` (bypasses PTT IP blocks).
- `scheduled()`: Cron triggers (every 5 min and hourly UTC 0–16); dispatches `cron-591-rent` or `cron-ptt-rss` events.

**Python scripts** — each is a standalone script run by GitHub Actions:
- `crawler_591.py`: Uses Playwright (headless Chromium) to scrape rent.591.com.tw across multiple district URLs; deduplicates by item ID; outputs `591_rent_data.json`.
- `notify_telegram.py`: Reads `591_rent_data.json` and sends formatted results to Telegram.
- `donate_notify.py`: Uses Playwright to scrape weekend blood donation activity images from tp.blood.org.tw and sends them via Telegram.
- `ptt_rss_monitor.py`: Fetches PTT LifeIsMoney Atom feed via the Worker proxy, tracks seen article IDs in `/tmp/ptt_rss_state.json`, pushes new posts to Telegram.
- `yt_channel_monitor.py`: Fetches YouTube channel RSS feed, filters by `YT_KEYWORD`, tracks seen video IDs in `/tmp/yt_state.json`, pushes matching new videos to Telegram.
- `telegram_utils.py`: Shared utility with `send_message()`, `send_photo_bytes()`, `send_batched()`. All scripts import from here.

### Required GitHub Secrets

| Secret | Used by |
|---|---|
| `TELEGRAM_BOT_TOKEN` | All workflows |
| `TELEGRAM_DEFAULT_CHAT_ID` | 591-rent, ptt-rss, yt-monitor (fallback when no chat_id in payload) |
| `CHAT_ID` | donate, ptt-rss, yt-monitor workflows |
| `WORKER_URL` | ptt-rss (points to Cloudflare Worker URL for RSS proxy) |
| `YT_CHANNEL_ID` | yt-monitor |
| `YT_KEYWORD` | yt-monitor |

### Cloudflare Worker Environment Variables

Set via `wrangler secret put` (not in `wrangler.toml`):
- `TELEGRAM_BOT_TOKEN`
- `GITHUB_TOKEN` (needs `repo` scope for dispatches)
- `GITHUB_REPO` (set in wrangler.toml as `ming780922/Hello-Claude`)
