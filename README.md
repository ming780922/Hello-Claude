# Hello-Claude

透過 **Cloudflare Worker** + **GitHub Actions** 串接 Telegram Bot，實現多項自動化通知功能。

## 功能列表

| 功能 | 觸發方式 | 說明 |
|---|---|---|
| `/echo` | Telegram 指令 | 回傳使用者輸入的訊息 |
| `/donate` | Telegram 指令 | 查詢最新捐血活動資訊並推播 |
| `/591` | Telegram 指令 | 查詢 591 租屋符合條件的物件並推播 |
| PTT LifeIsMoney 監控 | 每 5 分鐘自動 | 有新文章時推播至 Telegram |

---

## 整體架構

```
Telegram Bot
    │  指令（/echo、/donate、/591）
    ▼
Cloudflare Worker  (Webhook 接收 + Cron 排程)
    │  repository_dispatch
    ▼
GitHub Actions
    │  執行 Python 爬蟲 / 推播邏輯
    ▼
Telegram Bot API  (推播結果給使用者)
```

---

## 檔案說明

| 檔案 | 說明 |
|---|---|
| `worker.js` | Cloudflare Worker：接收 Telegram Webhook、處理指令、觸發 GitHub Actions |
| `telegram_utils.py` | Telegram 發送工具庫（`send_message`、`send_photo_bytes`、`send_batched`） |
| `ptt_rss_monitor.py` | PTT LifeIsMoney RSS 監控，有新文章時推播 |
| `notify_telegram.py` | 591 租屋爬蟲結果推播 |
| `crawler_591.py` | 591 租屋網爬蟲（Playwright） |
| `donate_notify.py` | 捐血活動資訊爬蟲（Playwright） |
| `wrangler.toml` | Cloudflare Worker 設定（Cron 排程） |

### GitHub Actions Workflows

| Workflow | 觸發方式 | 說明 |
|---|---|---|
| `echo.yml` | `repository_dispatch: cron-echo` | 回傳 /echo 訊息 |
| `ptt-rss.yml` | `repository_dispatch: cron-ptt-rss` | PTT RSS 監控 |
| `donate.yml` | `repository_dispatch: cron-donate` | 捐血活動爬蟲 |
| `591-rent.yml` | `repository_dispatch: cron-591-rent` | 591 租屋爬蟲 |
| `deploy-worker.yml` | push to main | 自動部署 Cloudflare Worker |

---

## 設定步驟

### 1. GitHub Secrets

前往 **Settings → Secrets and variables → Actions**，新增：

| Secret 名稱 | 說明 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | 從 @BotFather 取得的 Bot Token |
| `TELEGRAM_DEFAULT_CHAT_ID` | 接收通知的 Telegram Chat ID |
| `WORKER_URL` | Cloudflare Worker 網址 |

### 2. 部署 Cloudflare Worker

1. 登入 [Cloudflare Dashboard](https://dash.cloudflare.com/) → **Workers & Pages** → 建立新 Worker
2. 執行 `npx wrangler deploy` 或將 `worker.js` 貼入編輯器儲存
3. 前往 Worker 的 **Settings → Variables**，新增：

| 變數名稱 | 說明 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `GITHUB_TOKEN` | GitHub Personal Access Token（需要 `repo` 權限） |
| `GITHUB_REPO` | 此 Repo 路徑，例如 `ming780922/Hello-Claude` |

### 3. 設定 Telegram Webhook

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -d "url=https://your-worker.your-subdomain.workers.dev"
```

---

## 使用方式

對 Telegram Bot 傳送以下指令：

```
/echo Hello World     → 回傳：Echo: Hello World
/donate               → 推播最新捐血活動
/591                  → 推播 591 租屋符合物件
```

PTT LifeIsMoney 有新文章時會自動推播，無需手動觸發。
