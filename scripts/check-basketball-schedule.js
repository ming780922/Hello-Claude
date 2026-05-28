const fs = require('fs');
const path = require('path');

const SNAPSHOT_PATH = process.env.SNAPSHOT_PATH || '/tmp/basketball-schedule.json';
const SPREADSHEET_ID = process.env.SPREADSHEET_ID;
const SHEET_GID = process.env.SHEET_GID;
const MY_TEAM = process.env.MY_TEAM;
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID;

// ─── Google Sheets ────────────────────────────────────────────────────────────

async function fetchSheetData() {
  const url = `https://docs.google.com/spreadsheets/d/${SPREADSHEET_ID}/export?format=csv&gid=${SHEET_GID}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`無法抓取 Sheet：${res.status}`);
  const csv = await res.text();
  return parseCSV(csv);
}

function parseCSV(csv) {
  return csv.split('\n').map(line => {
    // 處理欄位內有逗號的情況（用雙引號包住）
    const cells = [];
    let current = '';
    let inQuotes = false;
    for (const char of line) {
      if (char === '"') {
        inQuotes = !inQuotes;
      } else if (char === ',' && !inQuotes) {
        cells.push(current.trim());
        current = '';
      } else {
        current += char;
      }
    }
    cells.push(current.trim());
    return cells;
  });
}

// ─── Parse ────────────────────────────────────────────────────────────────────

function parseGames(rows) {
  const dateMap = {};

  // 找日期 header rows：同列有 >=2 個符合 yyyy/M/d 格式的格子
  const dateHeaderIdxs = [];
  for (let r = 0; r < rows.length; r++) {
    const dateCount = rows[r].filter(c => /^\d{4}\/\d{1,2}\/\d{1,2}$/.test(c)).length;
    if (dateCount >= 2) dateHeaderIdxs.push(r);
  }

  for (const headerIdx of dateHeaderIdxs) {
    const headerRow = rows[headerIdx];
    const labelRow  = rows[headerIdx + 1] || [];

    // 找「時間」欄的位置 → 每組起始欄
    const groupStartCols = [];
    for (let c = 0; c < labelRow.length; c++) {
      if (labelRow[c] === '時間') groupStartCols.push(c);
    }

    // 每組起始欄對應的日期
    const groupDates = groupStartCols.map(startCol => {
      for (let c = startCol; c < startCol + 5 && c < headerRow.length; c++) {
        if (/^\d{4}\/\d{1,2}\/\d{1,2}$/.test(headerRow[c])) return headerRow[c];
      }
      return null;
    });

    // 讀資料列
    let dataIdx = headerIdx + 2;
    while (dataIdx < rows.length) {
      const row = rows[dataIdx];
      if (!row || row.every(c => !c)) break;  // 空白列 → 結束此區塊

      for (let gi = 0; gi < groupStartCols.length; gi++) {
        const sc      = groupStartCols[gi];
        const dateStr = groupDates[gi];
        if (!dateStr) continue;

        const timeStr  = (row[sc]     || '').trim();
        const location = (row[sc + 1] || '').trim();
        const group    = (row[sc + 2] || '').trim();
        const team1    = (row[sc + 3] || '').trim();
        const team2    = (row[sc + 4] || '').trim();

        // 跳過條件
        if (!team1 || !team2) continue;
        if (['非租用時段', '舊季賽程', ''].includes(team1)) continue;
        if (group.includes('季後賽') || group.includes('冠軍賽')) continue;

        if (!dateMap[dateStr]) dateMap[dateStr] = { dateStr, matches: [] };
        dateMap[dateStr].matches.push({ timeStr, location, group, team1, team2 });
      }
      dataIdx++;
    }
  }

  return Object.values(dateMap).sort((a, b) => a.dateStr.localeCompare(b.dateStr));
}

function getTeamGames(games, teamName) {
  return games.flatMap(day =>
    day.matches
      .filter(m => m.team1.includes(teamName) || m.team2.includes(teamName))
      .map(m => ({ dateStr: day.dateStr, ...m }))
  );
}

// ─── Diff ─────────────────────────────────────────────────────────────────────

function makeUID(g) {
  return `${g.dateStr}_${g.team1}_${g.team2}`;
}

function makeFingerprint(g) {
  return `${g.timeStr}|${g.location}`;
}

function diffGames(prev, curr) {
  const prevMap = Object.fromEntries(prev.map(g => [makeUID(g), g]));
  const currMap = Object.fromEntries(curr.map(g => [makeUID(g), g]));

  const added    = curr.filter(g => !prevMap[makeUID(g)]);
  const removed  = prev.filter(g => !currMap[makeUID(g)]);
  const changed  = curr.filter(g => {
    const p = prevMap[makeUID(g)];
    return p && makeFingerprint(p) !== makeFingerprint(g);
  }).map(g => ({ ...g, _prev: prevMap[makeUID(g)] }));

  return { added, removed, changed };
}

// ─── Calendar link ────────────────────────────────────────────────────────────

function calendarLink(g) {
  const [year, month, day] = g.dateStr.split('/');
  const [hour, minute]     = g.timeStr.split(':');
  const pad = n => String(n).padStart(2, '0');

  const start = `${year}${pad(month)}${pad(day)}T${pad(hour)}${pad(minute)}00`;
  // 加 1 小時
  const endHour = (parseInt(hour) + 1) % 24;
  const end     = `${year}${pad(month)}${pad(day)}T${pad(endHour)}${pad(minute)}00`;

  const title   = encodeURIComponent(`${g.team1} vs ${g.team2}`);
  const loc     = encodeURIComponent(resolveLocation(g.location));
  const details = encodeURIComponent(`${g.group}\n${g.location}`);

  return `https://calendar.google.com/calendar/render?action=TEMPLATE&text=${title}&dates=${start}/${end}&location=${loc}&details=${details}`;
}

const LOCATION_MAP = {
  '和平暖A':  '臺北市大安區和平實驗國民小學附屬籃球館暖身球場',
  '和平暖B':  '臺北市大安區和平實驗國民小學附屬籃球館暖身球場',
  '和平高中': '臺北市立和平高級中學',
  '金華':     '臺北市立金華國民中學',
  '金華國中': '臺北市立金華國民中學',
  '永春高中': '臺北市立永春高級中學',
  '松山高中': '臺北市立松山高級中學',
  '大安':     '臺北市大安運動中心',
};

function resolveLocation(rawLocation) {
  // 完全比對
  if (LOCATION_MAP[rawLocation]) return LOCATION_MAP[rawLocation];
  // 部分比對（場地名稱可能有變化）
  for (const [key, address] of Object.entries(LOCATION_MAP)) {
    if (rawLocation.includes(key)) return address;
  }
  // 找不到就直接用原始名稱，Google 有時候也認得
  return rawLocation;
}

// ─── Telegram ─────────────────────────────────────────────────────────────────

async function sendTelegram(text, inlineKeyboard) {
  const url = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`;
  const body = {
    chat_id: TELEGRAM_CHAT_ID,
    text,
    parse_mode: 'HTML',
    ...(inlineKeyboard && {
      reply_markup: { inline_keyboard: inlineKeyboard },
    }),
  };
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.text();
    console.error('Telegram error:', err);
  }
}

function formatMatch(g) {
  return `🏀 ${g.team1} vs ${g.team2}\n📅 <b>${g.dateStr} ${g.timeStr}</b>\n📍 ${g.location}\n`;
}

async function notifyDiff({ added, removed, changed }) {
  // 新增
  for (const g of added) {
    await sendTelegram(
      `🆕 <b>新賽程</b>\n${formatMatch(g)}`,
      [[{ text: '📅 加入 Google 日曆', url: calendarLink(g) }]]
    );
  }
  // 修改
  for (const g of changed) {
    const prev = g._prev;
    await sendTelegram(
      `✏️ <b>賽程異動</b>\n${formatMatch(g)}\n\n` +
      `<s>原本：${prev.dateStr} ${prev.timeStr} @ ${prev.location}</s>`,
      [[{ text: '📅 加入 Google 日曆', url: calendarLink(g) }]]
    );
  }
  // 取消
  for (const g of removed) {
    await sendTelegram(
      `❌ <b>賽程取消</b>\n${formatMatch(g)}`
    );
  }
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  // 1. 抓資料
  const rows  = await fetchSheetData();
  const games = parseGames(rows);
  const curr  = getTeamGames(games, MY_TEAM);

  // 2. 讀上次快照
  let prev = [];
  if (fs.existsSync(SNAPSHOT_PATH)) {
    prev = JSON.parse(fs.readFileSync(SNAPSHOT_PATH, 'utf-8'));
  }

  // 3. diff
  const diff = diffGames(prev, curr);
  console.log(`新增 ${diff.added.length}、修改 ${diff.changed.length}、取消 ${diff.removed.length}`);

  // 4. 通知
  if (diff.added.length || diff.changed.length || diff.removed.length) {
    await notifyDiff(diff);
  } else {
    console.log('無異動，跳過通知。');
  }

  // 5. 更新快照
  fs.mkdirSync(path.dirname(SNAPSHOT_PATH), { recursive: true });
  fs.writeFileSync(SNAPSHOT_PATH, JSON.stringify(curr, null, 2));
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});