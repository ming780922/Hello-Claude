# Hello-Claude

透過 **Cloudflare Worker** + **GitHub Actions** 串接 Telegram Bot，實現 `/echo` 指令回傳訊息。

## 架構流程

```
Telegram Bot
    │  /echo <訊息>
    ▼
Cloudflare Worker  (Webhook 接收)
    │  POST /repos/.../dispatches
    ▼
GitHub Actions  (repository_dispatch 觸發)
    │  sendMessage
    ▼
Telegram Bot API  (回傳 echo 給使用者)
```

---

## 設定步驟

### 1. GitHub Secrets

前往 **Settings → Secrets and variables → Actions**，新增：

| Secret 名稱 | 說明 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | 從 @BotFather 取得的 Bot Token |

---

### 2. 部署 Cloudflare Worker

1. 登入 [Cloudflare Dashboard](https://dash.cloudflare.com/) → **Workers & Pages** → 建立新 Worker
2. 將 `worker.js` 的內容貼入編輯器並儲存
3. 前往 Worker 的 **Settings → Variables**，新增以下環境變數：

| 變數名稱 | 說明 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `GITHUB_TOKEN` | GitHub Personal Access Token（需要 `repo` 權限） |
| `GITHUB_REPO` | 此 Repo 路徑，例如 `ming780922/Hello-Claude` |

4. 複製 Worker 的網址，例如：`https://your-worker.your-subdomain.workers.dev`

---

### 3. 設定 Telegram Webhook

執行以下指令，將 Telegram 的 Webhook 指向你的 Cloudflare Worker：

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -d "url=https://your-worker.your-subdomain.workers.dev"
```

成功後會收到：
```json
{"ok": true, "result": true, "description": "Webhook was set"}
```

---

### 4. 測試

對你的 Telegram Bot 傳送：

```
/echo Hello World
```

Bot 將回傳：

```
Echo: Hello World
```

---

## 檔案說明

| 檔案 | 說明 |
|---|---|
| `worker.js` | Cloudflare Worker，接收 Telegram Webhook 並觸發 GitHub Action |
| `.github/workflows/echo.yml` | GitHub Action，呼叫 Telegram API 回傳 echo 訊息 |

