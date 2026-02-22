// analytics.js
// Supabase-backed analytics for Music Mini Crossword
// Handles: user identity, solve tracking, completion recording, percentile display

const SUPABASE_URL = window.CROSSWORD_CONFIG?.SUPABASE_URL;
const SUPABASE_KEY = window.CROSSWORD_CONFIG?.SUPABASE_KEY;
const DEBUG = window.CROSSWORD_CONFIG?.DEBUG ?? false;

function dbg(...args) {
  if (DEBUG) console.log(...args);
}

if (!SUPABASE_URL || !SUPABASE_KEY) {
  console.error("[analytics] missing window.CROSSWORD_CONFIG SUPABASE_URL/SUPABASE_KEY");
}

// ---------------------------------------------------------------------------
// Tiny UUID v4 generator (no dependency needed)
// ---------------------------------------------------------------------------
function generateUUID() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// ---------------------------------------------------------------------------
// Minimal Supabase REST client (no npm required — works in plain HTML)
// ---------------------------------------------------------------------------
const sb = {
  async _req(method, path, body, extraHeaders) {
    const headers = {
      "Content-Type": "application/json",
      apikey: SUPABASE_KEY,
      Authorization: `Bearer ${SUPABASE_KEY}`,
      ...extraHeaders,
    };

    const opts = { method, headers };
    if (body !== undefined) opts.body = JSON.stringify(body);

    const url = `${SUPABASE_URL}${path}`;
    const methodUpper = method.toUpperCase();

    try {
      const res = await fetch(url, opts);
      const data = await res.json().catch(() => res.text());
      if (!res.ok) {
        dbg("[analytics] Supabase request failed", {
          status: res.status,
          statusText: res.statusText,
          method: methodUpper,
          path,
          body,
          data,
        });
        throw new Error(
          `Supabase request failed: ${res.statusText} ${JSON.stringify(data)}`
        );
      }
      return { data, status: res.status };
    } catch (err) {
      dbg("[analytics] Supabase fetch error", {
        method: methodUpper,
        path,
        body,
        err,
      });
      console.error("[analytics] Supabase request failed", err);
      throw err;
    }
  },

  select(table, query) {
    return sb._req("GET", `/rest/v1/${table}?${query}`);
  },

  insert(table, rows, { upsert = false, returning = "representation" } = {}) {
    let prefer = `return=${returning}`;
    if (upsert) prefer += ", resolution=merge-duplicates";
    return sb._req("POST", `/rest/v1/${table}`, rows, { Prefer: prefer });
  },

  update(table, query, patch, { returning = "representation" } = {}) {
    return sb._req("PATCH", `/rest/v1/${table}?${query}`, patch, {
      Prefer: `return=${returning}`,
    });
  },
};

// ---------------------------------------------------------------------------
// Crossword Analytics
// ---------------------------------------------------------------------------
let _userId = null;
let _solveId = null;
let _puzzleId = null;

const STORAGE_USER_ID = "mm-user-id";
const STORAGE_NICKNAME = "mm-user-nickname";

async function getOrCreateUser() {
  let userId = localStorage.getItem(STORAGE_USER_ID);
  if (!userId) {
    userId = generateUUID();
    localStorage.setItem(STORAGE_USER_ID, userId);
  }

  // Check if user exists
  const res = await sb.select("users", `id=eq.${userId}`);
  const existing = Array.isArray(res.data) ? res.data[0] : null;

  if (!existing) {
    await sb.insert("users", [{ id: userId }]);
  }

  return userId;
}

function resolvePuzzleIdFromUrl() {
  const params = new URLSearchParams(window.location.search);
  // Stems URLs are like "?puzzle=italian-disco" etc.
  // If we ever change query param name, update here.
  const puzzleId = params.get("puzzle");
  // Fallback: use pathname as puzzle id in case query param isn't present.
  return puzzleId || window.location.pathname.replace(/^\//, "") || "index";
}

async function ensurePuzzleSolveStarted(puzzleId) {
  // Check for any existing solve row for this user+puzzle (completed or not)
  const res = await sb.select(
    "solves",
    `user_id=eq.${_userId}&puzzle_id=eq.${encodeURIComponent(
      puzzleId
    )}&order=started_at.desc&limit=1`
  );

  const latest = Array.isArray(res.data) ? res.data[0] : null;

  // If already completed, reuse that row — don't create a new one
  if (latest && latest.completed === true) {
    _solveId = latest.id;
    return;
  }

  // If in-progress, resume it
  if (latest && latest.completed === false) {
    _solveId = latest.id;
    return;
  }

  // Otherwise start a new solve
  const started_at = new Date().toISOString();
  const insertRes = await sb.insert("solves", [
    { user_id: _userId, puzzle_id: puzzleId, started_at },
  ]);

  // Supabase return format for insert is an array
  const inserted = Array.isArray(insertRes.data) ? insertRes.data[0] : null;
  _solveId = inserted?.id;
}

async function calcPercentile(puzzleId, userTime) {
  const res = await sb.select(
    "solves",
    `puzzle_id=eq.${encodeURIComponent(puzzleId)}&completed=eq.true&select=user_id,solve_time`
  );

  const rows = Array.isArray(res.data) ? res.data : [];
  if (!rows.length) return { fasterPercent: 0, sampleSize: 0 };

  // we only compare best time per user for consistency
  const bestPerUser = new Map();
  for (const row of rows) {
    const existing = bestPerUser.get(row.user_id);
    if (existing == null || row.solve_time < existing) bestPerUser.set(row.user_id, row.solve_time);
  }

  const leaderboard = Array.from(bestPerUser.values()).sort((a, b) => a - b);
  const N = leaderboard.length;

  // Percentile: fraction of solvers slower than you
  const slowerCount = leaderboard.filter((t) => t > userTime).length;
  const fasterPercent = slowerCount / N;

  return { fasterPercent, sampleSize: N };
}

function renderFastFinisher(fasterPercent, sampleSize) {
  const banner = document.getElementById("fast-finisher-banner");
  if (!banner) return;

  if (sampleSize >= 3 && fasterPercent >= 0.5) {
    banner.textContent = "⚡ You Were a Fast Finisher! (Top 50% of finishers so far)";
    banner.style.display = "block";
  } else {
    banner.style.display = "none";
  }
}

function renderUserStats(stats) {
  const el = document.getElementById("user-stats");
  if (!el) return;

  const pad = (s) => String(s).padStart(2, "0");
  const formatTime = (seconds) => `${pad(Math.floor(seconds / 60))}:${pad(seconds % 60)}`;

  const nickname = localStorage.getItem(STORAGE_NICKNAME) || "";

  let lineNickname = nickname ? `${nickname} — ` : "";
  let lineSolved = `Solved: ${stats.totalSolved || 0}`;
  let lineStreak = `Current streak: ${stats.currentStreak || 0}`;
  let lineBest = `Personal best: ${
    stats.personalBest != null ? formatTime(stats.personalBest) : "—"
  }`;
  let lineAvg = `Avg time: ${stats.averageTime != null ? formatTime(stats.averageTime) : "—"}`;
  let lineRolling = `Rolling avg (last 5): ${
    stats.rolling5Avg != null ? formatTime(stats.rolling5Avg) : "—"
  }`;
  let linePercent = `You are faster than ${stats.percentDisplay || 0}% of solvers. ${stats.badge || ""}`;

  el.innerHTML = `
    <p>${lineNickname}${lineSolved}</p>
    <p>${lineStreak}</p>
    <p>${lineBest}</p>
    <p>${lineAvg}</p>
    <p>${lineRolling}</p>
    <p>${linePercent}</p>
  `;
}

function deriveBadge(fasterPercent) {
  const percent = Math.round(fasterPercent * 100);

  // Dashboard badge escalation
  if (percent >= 90) return { percentDisplay: percent, badge: "🚀" };
  if (percent >= 80) return { percentDisplay: percent, badge: "🔥" };
  return { percentDisplay: percent, badge: "" };
}

function deriveStreaks(rows) {
  // Given an array of solves (completed) for this user with completed_at timestamps
  // compute current streak and longest streak (daily streak)
  const completedAt = rows
    .map((r) => r.completed_at)
    .filter(Boolean)
    .map((ts) => new Date(ts))
    .sort((a, b) => b - a);

  if (!completedAt.length) return { currentStreak: 0, longestStreak: 0 };

  const normalizeDateKey = (d) => `${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}`;

  let longest = 1;
  let current = 1;

  // current streak is anchored at most recent date
  for (let i = 1; i < completedAt.length; i++) {
    const prev = completedAt[i - 1];
    const cur = completedAt[i];

    const diffDays = Math.floor((prev - cur) / (1000 * 60 * 60 * 24));

    if (diffDays === 1) {
      current += 1;
      if (current > longest) longest = current;
    } else if (diffDays > 1) {
      current = 1;
    }
  }

  // longest streak isn't perfectly computed above for non-consecutive duplicates; fix with a set-based approach
  const uniqueDates = Array.from(
    new Set(completedAt.map((d) => normalizeDateKey(d)))
  ).map((key) => new Date(key));

  uniqueDates.sort((a, b) => a - b); // ascending

  longest = 0;
  let run = 0;
  for (let i = 0; i < uniqueDates.length; i++) {
    if (i === 0) {
      run = 1;
      longest = 1;
    } else {
      const prev = uniqueDates[i - 1];
      const cur = uniqueDates[i];
      const diffDays = Math.floor((cur - prev) / (1000 * 60 * 60 * 24));
      if (diffDays === 1) {
        run += 1;
      } else {
        run = 1;
      }
      if (run > longest) longest = run;
    }
  }

  // current streak recomputation: count backwards from latest date
  const todayKey = normalizeDateKey(completedAt[0]);
  current = 1;
  for (let i = 1; i < completedAt.length; i++) {
    const prev = completedAt[i - 1];
    const cur = completedAt[i];
    const prevKey = normalizeDateKey(prev);
    const curKey = normalizeDateKey(cur);

    if (prevKey === curKey) continue;

    const diffDays = Math.floor((prev - cur) / (1000 * 60 * 60 * 24));
    if (diffDays === 1) current += 1;
    else break;
  }

  return { currentStreak: current, longestStreak: longest };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

// called when the puzzle page loads (before solve)
async function onPuzzleLoad(puzzleId) {
  try {
    _puzzleId = puzzleId || resolvePuzzleIdFromUrl();
    _userId = await getOrCreateUser();
    await ensurePuzzleSolveStarted(_puzzleId);
  } catch (err) {
    dbg("[analytics] onPuzzleLoad failed", { err, puzzleId: _puzzleId });
    console.warn("[analytics] onPuzzleLoad failed:", err);
  }
}

// called when the user completes the puzzle (elapsed seconds)
async function onPuzzleComplete(seconds) {
  try {
    // ensure user/solve exists even if page reload occurred
    if (!_userId) _userId = await getOrCreateUser();
    if (!_puzzleId) _puzzleId = resolvePuzzleIdFromUrl();
    if (!_solveId) await ensurePuzzleSolveStarted(_puzzleId);

    if (!_solveId || !_userId || !_puzzleId) return;

    // We only want to write if this completion improves their best time for this puzzle.
    // But we need to update the "completed" flag no matter what; otherwise stats never count it.
    const completed_at = new Date().toISOString();

    const bestRes = await sb.select(
      "solves",
      `user_id=eq.${_userId}&puzzle_id=eq.${encodeURIComponent(
        _puzzleId
      )}&completed=eq.true&order=solve_time.asc&limit=1`
    );

    const best = Array.isArray(bestRes.data) ? bestRes.data[0] : null;

    const shouldUpdate =
      !best?.solve_time || best.solve_time > seconds || best?.id === _solveId;

    if (shouldUpdate) {
      await sb.update("solves", `id=eq.${_solveId}`, {
        completed: true,
        completed_at,
        solve_time: seconds,
      });
    } else {
      // user completed but didn't beat best time: still mark solve as completed
      await sb.update("solves", `id=eq.${_solveId}`, {
        completed: true,
        completed_at,
      });
    }

    // update completion screen banner
    const { fasterPercent, sampleSize } = await calcPercentile(_puzzleId, seconds);
    renderFastFinisher(fasterPercent, sampleSize);
  } catch (err) {
    dbg("[analytics] onPuzzleComplete failed", { err, solveId: _solveId, puzzleId: _puzzleId });
    console.warn("[analytics] onPuzzleComplete failed:", err);
  }
}

// loads stats for /stats.html
async function loadUserStats() {
  try {
    _userId = await getOrCreateUser();

    const res = await sb.select(
      "solves",
      `user_id=eq.${_userId}&completed=eq.true&order=completed_at.desc`
    );
    const completedRows = Array.isArray(res.data) ? res.data : [];

    const totalSolved = completedRows.length;
    let personalBest = null;
    let averageTime = null;
    let rolling5Avg = null;

    if (completedRows.length) {
      const times = completedRows
        .map((r) => r.solve_time)
        .filter((v) => typeof v === "number");

      if (times.length) {
        personalBest = Math.min(...times);
        averageTime = Math.floor(times.reduce((a, b) => a + b, 0) / times.length);

        const rolling = times.slice(0, 5);
        rolling5Avg = Math.floor(rolling.reduce((a, b) => a + b, 0) / rolling.length);
      }
    }

    const streaks = deriveStreaks(completedRows);
    const mostRecent = completedRows[0] || null;
    const { fasterPercent: recentFaster, sampleSize } = mostRecent
      ? await calcPercentile(mostRecent.puzzle_id, mostRecent.solve_time)
      : { fasterPercent: 0, sampleSize: 0 };

    return {
      totalSolved,
      personalBest,
      avgTime: averageTime,
      rolling5: rolling5Avg,
      currentStreak: streaks.currentStreak,
      longestStreak: streaks.longestStreak,
      mostRecentPuzzle: mostRecent?.puzzle_id || null,
      mostRecentTime: mostRecent?.solve_time || null,
      recentPercentile: sampleSize >= 3 ? Math.round(recentFaster * 100) : null,
    };
  } catch (err) {
    dbg("[analytics] loadUserStats failed", { err });
    console.warn("[analytics] loadUserStats failed:", err);
    return null;
  }
}

window.CrosswordAnalytics = {
  onPuzzleLoad,
  onPuzzleComplete,
  loadUserStats,
};