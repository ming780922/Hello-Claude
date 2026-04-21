/**
 * Cloudflare Worker — Telegram Webhook → GitHub Action Trigger
 *
 * Environment Variables (set in Cloudflare Worker settings):
 *   TELEGRAM_BOT_TOKEN  - Your Telegram Bot token (from @BotFather)
 *   GITHUB_TOKEN        - GitHub Personal Access Token (needs repo scope)
 *   GITHUB_REPO         - Target repo, e.g. "ming780922/Hello-Claude"
 *
 * D1 Binding (set in wrangler.toml):
 *   DB  - D1 database for saved listings
 */

// ── Telegram helpers ──────────────────────────────────────────────────────────

function tgApi(token, method, payload) {
  return fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function tgSend(token, chatId, text) {
  return tgApi(token, "sendMessage", { chat_id: chatId, text, parse_mode: "HTML" });
}

function tgSendWithMarkup(token, chatId, caption, itemId) {
  return tgApi(token, "sendMessage", {
    chat_id: chatId,
    text: caption,
    parse_mode: "HTML",
    disable_web_page_preview: true,
    reply_markup: {
      inline_keyboard: [[{ text: "🗑️ 移除", callback_data: `unsave:${itemId}` }]],
    },
  });
}

// ── GitHub dispatch helper ────────────────────────────────────────────────────

async function dispatch(env, eventType, payload = {}) {
  console.log(`[dispatch] event_type=${eventType} repo=${env.GITHUB_REPO} token_set=${!!env.GITHUB_TOKEN}`);
  const resp = await fetch(
    `https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "Cloudflare-Worker-Telegram-Bot",
      },
      body: JSON.stringify({ event_type: eventType, client_payload: payload }),
    }
  );
  console.log(`[dispatch] response status=${resp.status} event_type=${eventType}`);
  if (!resp.ok) {
    const err = await resp.text();
    console.error(`[dispatch] FAILED status=${resp.status} event_type=${eventType} body=${err}`);
  }
  return resp;
}

// ── Callback query handler ────────────────────────────────────────────────────

async function handleCallback(cq, env) {
  const chatId = String(cq.message.chat.id);
  const messageId = cq.message.message_id;
  const data = cq.data ?? "";
  const token = env.TELEGRAM_BOT_TOKEN;

  if (data.startsWith("save:")) {
    const itemId = data.slice(5);
    const caption = cq.message.caption || cq.message.text || "";

    const existing = await env.DB.prepare(
      "SELECT 1 FROM saved_listings WHERE item_id = ? AND chat_id = ?"
    ).bind(itemId, chatId).first();

    if (!existing) {
      await env.DB.prepare(
        "INSERT INTO saved_listings (item_id, chat_id, caption, saved_at) VALUES (?, ?, ?, ?)"
      ).bind(itemId, chatId, caption, new Date().toISOString()).run();
    }

    await tgApi(token, "editMessageReplyMarkup", {
      chat_id: chatId,
      message_id: messageId,
      reply_markup: {
        inline_keyboard: [[{ text: "🗑️ 取消儲存", callback_data: `unsave:${itemId}` }]],
      },
    });
    await tgApi(token, "answerCallbackQuery", {
      callback_query_id: cq.id,
      text: existing ? "已儲存過了" : "✅ 已儲存！",
    });

  } else if (data.startsWith("unsave:")) {
    const itemId = data.slice(7);

    await env.DB.prepare(
      "DELETE FROM saved_listings WHERE item_id = ? AND chat_id = ?"
    ).bind(itemId, chatId).run();

    await tgApi(token, "editMessageReplyMarkup", {
      chat_id: chatId,
      message_id: messageId,
      reply_markup: {
        inline_keyboard: [[{ text: "⭐ 儲存", callback_data: `save:${itemId}` }]],
      },
    });
    await tgApi(token, "answerCallbackQuery", {
      callback_query_id: cq.id,
      text: "🗑️ 已移除",
    });
  }
}

// ── Main export ───────────────────────────────────────────────────────────────

export default {
  async scheduled(event, env, ctx) {
    console.log(`[scheduled] cron="${event.cron}" scheduledTime=${event.scheduledTime}`);
    try {
      if (event.cron === "0 0-16 * * *") {
        await dispatch(env, "cron-591-rent");
      } else if (event.cron === "0 1 * * *") {
        await dispatch(env, "cron-fb-group");
      } else {
        await dispatch(env, "cron-ptt-crawler");
      }
      console.log(`[scheduled] done cron="${event.cron}"`);
    } catch (err) {
      console.error(`[scheduled] ERROR cron="${event.cron}"`, err);
    }
  },

  async fetch(request, env, ctx) {
    // GET 路由：RSS Feed 代理（繞過 PTT IP 封鎖）
    if (request.method === "GET") {
      const { pathname } = new URL(request.url);
      if (pathname === "/rss/LifeIsMoney") {
        const resp = await fetch("https://www.ptt.cc/atom/LifeIsMoney.xml", {
          headers: { Cookie: "over18=1", "User-Agent": "Mozilla/5.0" },
        });
        if (!resp.ok) return new Response("Bad Gateway", { status: 502 });
        const xml = await resp.text();
        return new Response(xml, {
          headers: { "Content-Type": "application/atom+xml; charset=utf-8" },
        });
      }
      return new Response("Not Found", { status: 404 });
    }

    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return new Response("Bad Request", { status: 400 });
    }

    // callback_query：處理 inline button 點擊
    if (body?.callback_query) {
      await handleCallback(body.callback_query, env);
      return new Response("OK");
    }

    const message = body?.message;
    if (!message) {
      return new Response("OK");
    }

    const chatId = message.chat?.id;
    const text = message.text ?? "";

    if (text.startsWith("/echo")) {
      const echoText = text.replace(/^\/echo\s*/, "").trim() || "(empty)";
      await dispatch(env, "telegram-echo", { chat_id: chatId, text: echoText });

    } else if (text.startsWith("/donate")) {
      await dispatch(env, "telegram-donate", { chat_id: chatId });

    } else if (text.startsWith("/591")) {
      await dispatch(env, "telegram-591", { chat_id: chatId });

    } else if (text.startsWith("/fb")) {
      await dispatch(env, "telegram-fb", { chat_id: chatId });

    } else if (text.startsWith("/saved")) {
      ctx.waitUntil(
        (async () => {
          const { results } = await env.DB.prepare(
            "SELECT item_id, caption FROM saved_listings WHERE chat_id = ? ORDER BY saved_at DESC"
          ).bind(String(chatId)).all();

          if (!results.length) {
            await tgSend(env.TELEGRAM_BOT_TOKEN, chatId, "目前沒有儲存的物件。");
            return;
          }

          await dispatch(env, "telegram-saved", {
            chat_id: String(chatId),
            listings: results,
          });
        })()
      );
    }

    return new Response("OK");
  },
};
