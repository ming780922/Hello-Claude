/**
 * Cloudflare Worker — Telegram Webhook → GitHub Action Trigger
 *
 * Environment Variables (set in Cloudflare Worker settings):
 *   TELEGRAM_BOT_TOKEN  - Your Telegram Bot token (from @BotFather)
 *   GITHUB_TOKEN        - GitHub Personal Access Token (needs repo scope)
 *   GITHUB_REPO         - Target repo, e.g. "ming780922/Hello-Claude"
 */

export default {
  async scheduled(event, env, ctx) {
    await fetch(
      `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/ptt-rss.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
          "User-Agent": "Cloudflare-Worker",
        },
        body: JSON.stringify({ ref: "main" }),
      }
    );
  },

  async fetch(request, env) {
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

    const message = body?.message;
    if (!message) {
      return new Response("OK");
    }

    const chatId = message.chat?.id;
    const text = message.text ?? "";

    // Route commands
    if (text.startsWith("/echo")) {
      // Extract the message after /echo (strip "/echo" prefix and trim)
      const echoText = text.replace(/^\/echo\s*/, "").trim() || "(empty)";

      const githubResponse = await fetch(
        `https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${env.GITHUB_TOKEN}`,
            Accept: "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "Cloudflare-Worker-Telegram-Bot",
          },
          body: JSON.stringify({
            event_type: "telegram-echo",
            client_payload: {
              chat_id: chatId,
              text: echoText,
            },
          }),
        }
      );

      if (!githubResponse.ok) {
        const err = await githubResponse.text();
        console.error("GitHub dispatch failed:", err);
        return new Response("Internal Server Error", { status: 500 });
      }
    } else if (text.startsWith("/donate")) {
      // Trigger blood donation activity image scraper
      const githubResponse = await fetch(
        `https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${env.GITHUB_TOKEN}`,
            Accept: "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "Cloudflare-Worker-Telegram-Bot",
          },
          body: JSON.stringify({
            event_type: "telegram-donate",
            client_payload: {
              chat_id: chatId,
            },
          }),
        }
      );

      if (!githubResponse.ok) {
        const err = await githubResponse.text();
        console.error("GitHub dispatch failed:", err);
        return new Response("Internal Server Error", { status: 500 });
      }
    }

    return new Response("OK");
  },
};
