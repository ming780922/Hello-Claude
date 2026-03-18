/**
 * Cloudflare Worker — Telegram Webhook → GitHub Action Trigger
 *                   + PTT RSS Feed Proxy (with KV Cache)
 *
 * Environment Variables (set in Cloudflare Worker settings):
 *   TELEGRAM_BOT_TOKEN  - Your Telegram Bot token (from @BotFather)
 *   GITHUB_TOKEN        - GitHub Personal Access Token (needs repo scope)
 *   GITHUB_REPO         - Target repo, e.g. "ming780922/Hello-Claude"
 *
 * KV Namespace Binding (set in wrangler.toml):
 *   PTT_RSS_CACHE       - KV namespace for caching PTT RSS feeds (TTL=5min)
 */

const PTT_BASE = "https://www.ptt.cc";
const PTT_HEADERS = { "User-Agent": "Mozilla/5.0", Cookie: "over18=1" };
const XML_CONTENT_TYPE = { "Content-Type": "application/atom+xml; charset=utf-8" };
const CACHE_TTL = 300; // 5 minutes

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // GET routes: PTT RSS Feed
    if (request.method === "GET") {
      if (url.pathname === "/rss/hotboards") {
        return handleHotboards(env);
      }
      const boardMatch = url.pathname.match(/^\/rss\/boards\/([A-Za-z0-9_-]+)$/);
      if (boardMatch) {
        return handleBoard(boardMatch[1], env);
      }
      return new Response("Not Found", { status: 404 });
    }

    // POST route: Telegram Webhook
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

/**
 * GET /rss/hotboards
 * Returns an Atom feed listing current PTT hot boards.
 * Each entry links to the board page and its RSS feed.
 */
async function handleHotboards(env) {
  const cacheKey = "hotboards";
  const cached = await env.PTT_RSS_CACHE.get(cacheKey);
  if (cached) return new Response(cached, { headers: XML_CONTENT_TYPE });

  const resp = await fetch(`${PTT_BASE}/bbs/hotboards.html`, { headers: PTT_HEADERS });
  if (!resp.ok) return new Response("Failed to fetch PTT hotboards", { status: 502 });

  // Use HTMLRewriter to extract board names and titles
  const boards = [];
  let currentBoard = null;
  await new HTMLRewriter()
    .on(".board", {
      element() {
        currentBoard = {};
        boards.push(currentBoard);
      },
    })
    .on(".board-name", {
      text({ text }) {
        if (currentBoard && text.trim()) {
          currentBoard.name = (currentBoard.name ?? "") + text.trim();
        }
      },
    })
    .on(".board-title", {
      text({ text }) {
        if (currentBoard && text.trim()) {
          currentBoard.title = (currentBoard.title ?? "") + text.trim();
        }
      },
    })
    .transform(resp)
    .arrayBuffer(); // consume response body

  const now = new Date().toISOString();
  const entries = boards
    .filter((b) => b.name)
    .map(
      (b) => `
  <entry>
    <id>${PTT_BASE}/bbs/${b.name}/</id>
    <title>${escapeXml(b.name)}${b.title ? " " + escapeXml(b.title) : ""}</title>
    <link href="${PTT_BASE}/bbs/${b.name}/"/>
    <link rel="alternate" type="application/atom+xml" href="${PTT_BASE}/atom/${b.name}.xml"/>
    <updated>${now}</updated>
  </entry>`
    )
    .join("");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>${PTT_BASE}/bbs/hotboards.html</id>
  <title>PTT 熱門看板</title>
  <updated>${now}</updated>
  <link href="${PTT_BASE}/bbs/hotboards.html"/>
  ${entries}
</feed>`;

  await env.PTT_RSS_CACHE.put(cacheKey, xml, { expirationTtl: CACHE_TTL });
  return new Response(xml, { headers: XML_CONTENT_TYPE });
}

/**
 * GET /rss/boards/:board
 * Proxies PTT's official Atom feed for a board, cached for 5 minutes.
 */
async function handleBoard(board, env) {
  const cacheKey = `board:${board}`;
  const cached = await env.PTT_RSS_CACHE.get(cacheKey);
  if (cached) return new Response(cached, { headers: XML_CONTENT_TYPE });

  const resp = await fetch(`${PTT_BASE}/atom/${board}.xml`, { headers: PTT_HEADERS });
  if (!resp.ok) return new Response("Board not found", { status: 404 });

  const xml = await resp.text();
  await env.PTT_RSS_CACHE.put(cacheKey, xml, { expirationTtl: CACHE_TTL });
  return new Response(xml, { headers: XML_CONTENT_TYPE });
}

function escapeXml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}
