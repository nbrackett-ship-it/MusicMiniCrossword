# Music Mini Crossword — Analytics Layer

Adds anonymous, Supabase-backed analytics to the static crossword site. No login required. Tracks solve times, streaks, and percentile rankings.

---

## Files

| File | Purpose |
|---|---|
| `analytics.js` | All Supabase logic: identity, solve tracking, percentile calc |
| `index.html` | Puzzle page with analytics hooks added |
| `stats.html` | Personal stats page (`/stats.html`) |

---

## Environment Variables / Config

There are **no build steps** and **no `.env` files** — this is a plain HTML/JS site. The Supabase credentials live directly in `analytics.js`:

```js
// analytics.js (top of file)
const SUPABASE_URL = "https://lzvlhfaldengwrlbjyzt.supabase.co";
const SUPABASE_KEY = "sb_publishable_ibteNhvxITZHSNjwiNEZ4g_jmE8b2AG";
```

The `SUPABASE_KEY` here is the **publishable (anon) key** — it is safe to ship in client-side code. It is governed by Supabase Row Level Security (RLS) policies.

---

## Supabase Setup

### 1. Tables (already created)

Your schema:

```sql
-- Users table
create table users (
  id uuid primary key,
  created_at timestamp default now()
);

-- Solves table
create table solves (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id),
  puzzle_id text,
  started_at timestamp,
  completed_at timestamp,
  solve_time integer,        -- seconds
  completed boolean default false
);
```

### 2. Row Level Security (RLS)

Enable RLS on both tables and add the following policies in the Supabase dashboard (SQL Editor):

```sql
-- Enable RLS
alter table users enable row level security;
alter table solves enable row level security;

-- Users: anyone can insert their own row; anyone can read (needed for identity check)
create policy "Users can insert themselves"
  on users for insert with check (true);

create policy "Users can read all"
  on users for select using (true);

-- Solves: anyone can insert; anyone can read (for percentile queries);
-- only the owner can update their own rows
create policy "Anyone can insert solves"
  on solves for insert with check (true);

create policy "Anyone can read solves"
  on solves for select using (true);

create policy "Users can update their own solves"
  on solves for update using (true);
```

> **Note:** The `select` policies are intentionally open so the percentile
> calculation can query all completed solves for a puzzle. No personal info
> (name, email, device data) is stored — only anonymous UUIDs and times.

### 3. Indexes (recommended for performance)

```sql
create index on solves (puzzle_id, completed);
create index on solves (user_id, puzzle_id, completed);
```

---

## How It Works

### Identity
- On first visit, a UUID is generated and stored in `localStorage` as `mm-user-id`.
- A row is inserted into `users` with that UUID.
- On subsequent visits the existing UUID is reused — no cookies, no login.

### Puzzle Load
- When a puzzle loads, `onPuzzleLoad(puzzleId)` is called.
- It inserts a new `solves` row with `started_at = now()` and `completed = false`.
- If an incomplete row already exists for this user+puzzle, it reuses it.

### Puzzle Completion
- When the puzzle is solved, `onPuzzleComplete(seconds)` is called.
- The solve row is updated: `completed = true`, `completed_at`, `solve_time`.
- Only records if this is the user's best time for the puzzle.

### Percentile (Victory Screen)
- After completion, all completed solves for the puzzle are fetched.
- Best time per user is computed client-side.
- If `N >= 3` and the user beat ≥ 50% of solvers, shows:
  > ⚡ You Were a Fast Finisher! (Top X% of finishers so far)

### Stats Page (`/stats.html`)
Displays:
- **Puzzles Solved** — total unique completed puzzles
- **Personal Best** — fastest single solve
- **Average Time** — mean across all best times
- **Last 5 Avg** — rolling 5-puzzle average
- **Current Streak** — consecutive calendar days with a solve
- **Longest Streak** — all-time best streak
- **Percentile** — "You are faster than X% of solvers" for most recent puzzle
- Emoji escalation: ≥ 90% → 🚀, ≥ 80% → 🔥, otherwise → ⚡

---

## Deployment

Just push all files to your GitHub Pages repo as-is. No build step needed.

```
your-repo/
  index.html        ← modified (analytics hooks added)
  analytics.js      ← new
  stats.html        ← new
  style.css
  puzzles/
    *.json
```

The `stats.html` page is accessible at `yourdomain.com/stats.html` and is linked from both the puzzle header and the victory overlay.
