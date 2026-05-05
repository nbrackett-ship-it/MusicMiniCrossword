import csv
import json
import os
import re
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request


CSV_FILENAME = "Master Music News Source List - Expanded_Music_News_Source_Master_List.csv"
KEYWORD_BANK_FILENAME = "music_source_keywords.csv"
FILL_PREFERENCES_FILENAME = "fill_preferences.json"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
DEFAULT_MAX_ATTEMPTS = int(os.environ.get("ANTHROPIC_MAX_ATTEMPTS", "3"))
DEFAULT_SLOT_CANDIDATES = int(os.environ.get("ANTHROPIC_SLOT_CANDIDATES", "18"))
DEFAULT_MIN_LOCAL_CANDIDATES = int(os.environ.get("ANTHROPIC_MIN_LOCAL_CANDIDATES", "6"))
DEFAULT_GRID_OPTIONS = int(os.environ.get("ANTHROPIC_GRID_OPTIONS", "8"))
DEFAULT_SOLVER_SEARCH_MULTIPLIER = int(os.environ.get("ANTHROPIC_SOLVER_SEARCH_MULTIPLIER", "3"))
DEFAULT_MAX_BRANCH_CANDIDATES = int(os.environ.get("ANTHROPIC_MAX_BRANCH_CANDIDATES", "18"))
DEFAULT_MIN_CANDIDATE_SCORE = int(os.environ.get("ANTHROPIC_MIN_CANDIDATE_SCORE", "0"))
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SYSTEM_WORDLIST_PATH = Path("/usr/share/dict/words")
KEYWORD_HEADER_HINTS = (
    "keyword",
    "source",
    "publication",
    "outlet",
    "label",
    "artist",
    "company",
    "genre",
    "category",
    "tag",
    "theme",
    "beat",
    "column",
    "focus",
    "audience",
)
KEYWORD_TYPE_ORDER = {
    "source_name": 0,
    "content_focus": 1,
    "audience": 2,
}
ENTRY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z&'/.-]*")
VOWELS = set("AEIOUY")
DEFAULT_FILL_PREFERENCES = {
    "preferred": [
        "FADER",
        "STEMS",
        "MERCH",
        "VINYL",
        "LABEL",
        "LABELS",
        "GRAMMY",
        "ALBUM",
        "RADIO",
        "INDIE",
        "BEATS",
        "CHART",
        "TIDAL",
        "SONY",
        "UMG",
        "DSP",
        "TOUR",
        "TOURS",
        "MIXES",
        "REMIX",
        "AUDIO",
        "ARENA",
        "NOTES",
    ],
    "acceptable": [
        "TRACK",
        "CROWD",
        "HOOK",
        "HOOKS",
        "TAPE",
        "TAPES",
        "PRESS",
        "STAFF",
        "MEDIA",
        "SCENE",
        "NIGHT",
        "CABLE",
        "ROSTER",
        "LEASE",
        "LINES",
        "VOICE",
    ],
    "banned": [
        "AKNEE",
        "AMTOO",
        "ANDUP",
        "AROOM",
        "DIALA",
        "IARGA",
        "IBRGA",
        "ICRGA",
        "IGRGA",
        "IMHIT",
        "IRRGA",
        "ITRGA",
        "MDSE",
        "MYMY",
        "ONHIRE",
        "STPAT",
        "TIPPA",
        "YOSTR",
    ],
    "banned_fragments": [
        "ARGA",
        "RRGA",
        "BRGA",
        "CRGA",
        "TRGA",
        "GRGA",
        "YOST",
    ],
}


def load_local_env():
    env_path = PROJECT_ROOT / ".env.local"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def json_response(handler, status, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def normalize_whitespace(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_grid_size(payload):
    grid_size = payload.get("gridSize")
    if isinstance(grid_size, dict):
        rows = int(grid_size.get("rows", 0))
        cols = int(grid_size.get("cols", 0))
    elif isinstance(grid_size, int):
        rows = cols = grid_size
    else:
        rows = cols = int(payload.get("size", 0))

    if rows not in (5, 6) or cols not in (5, 6) or rows != cols:
        raise ApiError("gridSize must describe a square 5x5 or 6x6 grid.")

    return rows, cols


def validate_pattern(pattern, rows, cols):
    expected_length = rows * cols
    if not isinstance(pattern, str) or len(pattern) != expected_length:
        raise ApiError(f"Pattern must be a {expected_length}-character string of '.' and '#'.")
    if re.search(r"[^.#]", pattern):
        raise ApiError("Pattern may only contain '.' and '#'.")


def pattern_to_matrix(pattern, size):
    return [list(pattern[row * size:(row + 1) * size]) for row in range(size)]


def count_run(matrix, row, col, row_step, col_step):
    size = len(matrix)
    length = 0
    current_row = row
    current_col = col
    while 0 <= current_row < size and 0 <= current_col < size and matrix[current_row][current_col] != "#":
        length += 1
        current_row += row_step
        current_col += col_step
    return length


def detect_slots(pattern, size):
    matrix = pattern_to_matrix(pattern, size)
    slots = []
    numbered_cells = {}
    next_number = 1

    for row in range(size):
        for col in range(size):
            if matrix[row][col] == "#":
                continue

            starts_across = col == 0 or matrix[row][col - 1] == "#"
            starts_down = row == 0 or matrix[row - 1][col] == "#"
            across_length = count_run(matrix, row, col, 0, 1) if starts_across else 0
            down_length = count_run(matrix, row, col, 1, 0) if starts_down else 0

            if starts_across or starts_down:
                numbered_cells[(row, col)] = next_number
                next_number += 1

            if starts_across and across_length > 1:
                slots.append({
                    "number": numbered_cells[(row, col)],
                    "row": row,
                    "col": col,
                    "direction": "across",
                    "length": across_length,
                })

            if starts_down and down_length > 1:
                slots.append({
                    "number": numbered_cells[(row, col)],
                    "row": row,
                    "col": col,
                    "direction": "down",
                    "length": down_length,
                })

    return slots


def find_orphan_white_cells(pattern, size):
    matrix = pattern_to_matrix(pattern, size)
    covered = set()
    for slot in detect_slots(pattern, size):
        row = slot["row"]
        col = slot["col"]
        for _ in range(slot["length"]):
            covered.add((row, col))
            if slot["direction"] == "across":
                col += 1
            else:
                row += 1

    orphans = []
    for row in range(size):
        for col in range(size):
            if matrix[row][col] == "." and (row, col) not in covered:
                orphans.append([row, col])
    return orphans


def resolve_csv_path():
    configured = os.environ.get("MUSIC_SOURCE_CSV")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend([
        PROJECT_ROOT / CSV_FILENAME,
        PROJECT_ROOT / "data" / CSV_FILENAME,
        PROJECT_ROOT / "assets" / CSV_FILENAME,
    ])

    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise ApiError(
        f"Keyword CSV not found. Add '{CSV_FILENAME}' to the repo root or set MUSIC_SOURCE_CSV.",
        status=500,
    )


def resolve_keyword_bank_path():
    configured = os.environ.get("MUSIC_SOURCE_KEYWORDS_CSV")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend([
        PROJECT_ROOT / KEYWORD_BANK_FILENAME,
        PROJECT_ROOT / "data" / KEYWORD_BANK_FILENAME,
        PROJECT_ROOT / "assets" / KEYWORD_BANK_FILENAME,
    ])

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def resolve_fill_preferences_path():
    configured = os.environ.get("FILL_PREFERENCES_JSON")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend([
        PROJECT_ROOT / FILL_PREFERENCES_FILENAME,
        PROJECT_ROOT / "data" / FILL_PREFERENCES_FILENAME,
        PROJECT_ROOT / "assets" / FILL_PREFERENCES_FILENAME,
    ])

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def add_keyword(raw_value, seen, output):
    cleaned = normalize_whitespace(raw_value)
    if len(cleaned) < 2 or len(cleaned) > 80:
        return
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return
    key = cleaned.lower()
    if key in seen:
        return
    seen.add(key)
    output.append(cleaned)


def load_keyword_bank(extra_keywords):
    seen = set()
    output = []

    for keyword in extra_keywords:
        add_keyword(keyword, seen, output)

    keyword_bank_path = resolve_keyword_bank_path()
    if keyword_bank_path:
        with keyword_bank_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = sorted(
                list(reader),
                key=lambda row: (
                    (row.get("priority_source") or "").strip().upper() != "TRUE",
                    KEYWORD_TYPE_ORDER.get((row.get("keyword_type") or "").strip(), 99),
                    normalize_whitespace(row.get("keyword")).lower(),
                ),
            )
            for row in rows:
                add_keyword(row.get("keyword"), seen, output)
                if len(output) >= 220:
                    return output

    csv_path = resolve_csv_path()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames:
            preferred_headers = [
                header
                for header in reader.fieldnames
                if any(hint in header.lower() for hint in KEYWORD_HEADER_HINTS)
            ]
            headers_to_use = preferred_headers or reader.fieldnames
            for row in reader:
                for header in headers_to_use:
                    add_keyword(row.get(header), seen, output)
                    if len(output) >= 220:
                        return output
        else:
            handle.seek(0)
            raw_reader = csv.reader(handle)
            for row in raw_reader:
                for value in row:
                    add_keyword(value, seen, output)
                    if len(output) >= 220:
                        return output

    return output


def normalize_word_list(values, max_length=6):
    output = []
    seen = set()
    for value in values or []:
        cleaned = sanitize_candidate(value)
        if 3 <= len(cleaned) <= max_length and cleaned not in seen:
            seen.add(cleaned)
            output.append(cleaned)
    return output


def load_fill_preferences(max_length):
    payload = dict(DEFAULT_FILL_PREFERENCES)
    path = resolve_fill_preferences_path()
    if path:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                payload.update({key: raw.get(key, payload.get(key, [])) for key in payload})
        except Exception:
            pass

    return {
        "preferred": set(normalize_word_list(payload.get("preferred"), max_length=max_length)),
        "acceptable": set(normalize_word_list(payload.get("acceptable"), max_length=max_length)),
        "banned": set(normalize_word_list(payload.get("banned"), max_length=max_length)),
        "banned_fragments": [
            sanitize_candidate(fragment)
            for fragment in payload.get("banned_fragments", [])
            if len(sanitize_candidate(fragment)) >= 3
        ],
    }


COMMON_WORD_CACHE = {}


def load_common_words(max_length):
    cached = COMMON_WORD_CACHE.get(max_length)
    if cached is not None:
        return cached

    words = set()
    if SYSTEM_WORDLIST_PATH.exists():
        for raw_line in SYSTEM_WORDLIST_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            candidate = raw_line.strip()
            if re.fullmatch(r"[a-z]{3,%d}" % max_length, candidate):
                words.add(candidate.upper())

    COMMON_WORD_CACHE[max_length] = words
    return words


def slot_key(slot):
    return f'{slot["number"]}-{slot["direction"]}'


def slot_label(slot):
    return f'{slot["number"]} {slot["direction"]}'


def annotate_slots(slots):
    annotated = []
    for slot in slots:
        cells = []
        row = slot["row"]
        col = slot["col"]
        for _ in range(slot["length"]):
            cells.append((row, col))
            if slot["direction"] == "across":
                col += 1
            else:
                row += 1

        enriched = dict(slot)
        enriched["key"] = slot_key(slot)
        enriched["cells"] = cells
        annotated.append(enriched)
    return annotated


def sanitize_candidate(raw_value):
    cleaned = normalize_whitespace(raw_value).upper()
    cleaned = re.sub(r"[^A-Z]", "", cleaned)
    return cleaned


def iter_text_fragments(raw_value):
    text = normalize_whitespace(raw_value)
    if not text:
        return []

    fragments = []
    compact = sanitize_candidate(text)
    if compact:
        fragments.append(compact)

    for token in ENTRY_TOKEN_RE.findall(text):
        cleaned = sanitize_candidate(token)
        if cleaned:
            fragments.append(cleaned)

    return fragments


def add_candidate(pool, word, score):
    if len(word) < 3:
        return

    bucket = pool.setdefault(len(word), {})
    bucket[word] = max(score, bucket.get(word, 0))


def load_seed_answer_pool():
    pool = {}
    for path in sorted((PROJECT_ROOT / "puzzles").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in data.get("words", []):
            word = sanitize_candidate(item.get("word"))
            if word:
                add_candidate(pool, word, 6)
    return pool


def build_fill_lexicon(user_keywords, keyword_bank, max_length):
    preferences = load_fill_preferences(max_length)
    seed_words = set()
    for length, bucket in load_seed_answer_pool().items():
        if length <= max_length:
            seed_words.update(bucket.keys())

    user_words = set()
    for keyword in user_keywords:
        for fragment in iter_text_fragments(keyword):
            if len(fragment) <= max_length:
                user_words.add(fragment)

    keyword_words = set()
    priority_keyword_words = set()
    for index, keyword in enumerate(keyword_bank):
        for fragment in iter_text_fragments(keyword):
            if len(fragment) <= max_length:
                keyword_words.add(fragment)
                if index < 60:
                    priority_keyword_words.add(fragment)

    common_words = load_common_words(max_length)
    known_words = (
        preferences["preferred"]
        | preferences["acceptable"]
        | seed_words
        | user_words
        | keyword_words
        | common_words
    ) - preferences["banned"]

    return {
        "preferred_words": preferences["preferred"],
        "acceptable_words": preferences["acceptable"],
        "banned_words": preferences["banned"],
        "banned_fragments": preferences["banned_fragments"],
        "seed_words": seed_words,
        "user_words": user_words,
        "keyword_words": keyword_words,
        "priority_keyword_words": priority_keyword_words,
        "common_words": common_words,
        "known_words": known_words,
    }


def candidate_quality(word, lexicon, base_score=0):
    word = sanitize_candidate(word)
    score = base_score
    flags = []

    if word in lexicon["banned_words"]:
        return -999, ["blocked"]

    if word in lexicon["preferred_words"]:
        score += 28
        flags.append("preferred")
    elif word in lexicon["user_words"]:
        score += 24
        flags.append("theme")
    elif word in lexicon["priority_keyword_words"]:
        score += 20
        flags.append("music")
    elif word in lexicon["keyword_words"]:
        score += 14
        flags.append("music")

    if word in lexicon["seed_words"]:
        score += 6
        flags.append("published")

    if word in lexicon["acceptable_words"]:
        score += 7
    if word in lexicon["common_words"]:
        score += 5

    if word not in lexicon["known_words"]:
        score -= 22
        flags.append("unverified")

    for fragment in lexicon["banned_fragments"]:
        if fragment and fragment in word:
            score -= 18
            flags.append("awkward")
            break

    vowel_count = sum(letter in VOWELS for letter in word)
    if vowel_count == 0:
        score -= 18
        flags.append("no-vowels")
    elif len(word) >= 5 and vowel_count == 1 and word not in lexicon["known_words"]:
        score -= 10
        flags.append("dry")

    if re.search(r"[^AEIOUY]{4,}", word) and word not in lexicon["known_words"]:
        score -= 12
        flags.append("cluster")

    if re.search(r"(.)\1\1", word):
        score -= 8
        flags.append("repeat")

    if sum(letter in "JQXZ" for letter in word) >= 2 and word not in lexicon["known_words"]:
        score -= 6
        flags.append("spiky")

    deduped_flags = []
    seen = set()
    for flag in flags:
        if flag not in seen:
            seen.add(flag)
            deduped_flags.append(flag)

    return score, deduped_flags


def build_local_candidate_pool(user_keywords, keyword_bank, max_length, lexicon):
    pool = load_seed_answer_pool()

    for word in sorted(lexicon["preferred_words"]):
        add_candidate(pool, word, 18)
    for word in sorted(lexicon["acceptable_words"]):
        add_candidate(pool, word, 8)

    for keyword in user_keywords:
        for fragment in iter_text_fragments(keyword):
            if len(fragment) <= max_length:
                add_candidate(pool, fragment, 18)

    for index, keyword in enumerate(keyword_bank):
        score = 14 if index < 40 else 10 if index < 120 else 7
        for fragment in iter_text_fragments(keyword):
            if len(fragment) <= max_length:
                add_candidate(pool, fragment, score)

    return pool


def build_grid_from_assignment(pattern, size, slots, assignment):
    matrix = pattern_to_matrix(pattern, size)
    grid = [[None if matrix[row][col] == "#" else "" for col in range(size)] for row in range(size)]
    for slot in slots:
        word = assignment.get(slot["key"])
        if not word:
            continue
        for (row, col), letter in zip(slot["cells"], word):
            grid[row][col] = letter
    return grid


def pattern_for_slot(slot, grid):
    letters = []
    for row, col in slot["cells"]:
        value = grid[row][col]
        letters.append(value if value else "?")
    return "".join(letters)


def matches_pattern(word, pattern):
    return len(word) == len(pattern) and all(p == "?" or p == c for p, c in zip(pattern, word))


def extract_candidate_json(raw_text):
    raw_object = json.loads(extract_json_object(raw_text))
    candidates = raw_object.get("candidates", [])
    if not isinstance(candidates, list):
        raise ApiError("Candidate response must include a candidates array.", status=502)
    return candidates


def fallback_extract_candidates(raw_text, length):
    seen = set()
    output = []
    for token in ENTRY_TOKEN_RE.findall(raw_text):
        cleaned = sanitize_candidate(token)
        if len(cleaned) == length and cleaned not in seen:
            seen.add(cleaned)
            output.append(cleaned)
    return output


def request_slot_candidates(slot, letter_pattern, request_payload, keyword_bank, used_words):
    title_hint = normalize_whitespace(request_payload.get("title"))
    keyword_lines = ", ".join(keyword_bank[:80])
    used_line = ", ".join(sorted(used_words)) if used_words else "None yet"

    prompt = f"""
You are helping fill a single slot in a 5x5 or 6x6 music-industry mini crossword.

Return exactly one JSON object with this shape:
{{
  "candidates": ["WORDONE", "WORDTWO"]
}}

Rules:
- Return JSON only.
- Provide up to {DEFAULT_SLOT_CANDIDATES} candidates.
- Every candidate must be uppercase ASCII letters only.
- Every candidate must be exactly {slot["length"]} letters long.
- Every candidate must match the pattern `{letter_pattern}` where `?` means unknown.
- Prefer music-industry answers: artists, companies, genres, trade terms, titles, outlets, acronyms.
- Standard dictionary fill is acceptable if needed to make the crossword solvable.
- Do not invent clipped fragments, partial phrases, or letter salad.
- If only two or three strong candidates fit, return only those.
- Avoid any answer already used elsewhere in the grid.

Slot:
- number: {slot["number"]}
- direction: {slot["direction"]}
- row: {slot["row"]}
- col: {slot["col"]}
- length: {slot["length"]}
- pattern: {letter_pattern}

Context:
- title hint: {title_hint or "(none)"}
- user keywords and source-bank highlights: {keyword_lines}
- answers already used: {used_line}
""".strip()

    try:
        raw_text = call_anthropic(prompt)
        candidates = extract_candidate_json(raw_text)
    except ApiError:
        raw_text = locals().get("raw_text", "")
        candidates = fallback_extract_candidates(raw_text, slot["length"])

    normalized = []
    seen = set()
    for candidate in candidates:
        cleaned = sanitize_candidate(candidate)
        if (
            len(cleaned) == slot["length"]
            and matches_pattern(cleaned, letter_pattern)
            and cleaned not in used_words
            and cleaned not in seen
        ):
            seen.add(cleaned)
            normalized.append(cleaned)

    return normalized


def get_slot_candidates(slot, grid, assignment, pool, request_payload, keyword_bank, ai_cache, lexicon):
    letter_pattern = pattern_for_slot(slot, grid)
    used_words = set(assignment.values())
    bucket = pool.get(slot["length"], {})

    local_matches = []
    for word, base_score in bucket.items():
        if word in used_words or not matches_pattern(word, letter_pattern):
            continue
        score, _flags = candidate_quality(word, lexicon, base_score)
        if score >= DEFAULT_MIN_CANDIDATE_SCORE:
            local_matches.append((score, word))

    cache_key = (slot["key"], letter_pattern)
    if cache_key not in ai_cache and len(local_matches) < DEFAULT_MIN_LOCAL_CANDIDATES:
        ai_matches = request_slot_candidates(slot, letter_pattern, request_payload, keyword_bank, used_words)
        ai_cache[cache_key] = ai_matches
        for index, word in enumerate(ai_matches):
            add_candidate(pool, word, 20 - index)

    scored_matches = []
    seen = set()
    for word, base_score in pool.get(slot["length"], {}).items():
        if word in used_words or word in seen or not matches_pattern(word, letter_pattern):
            continue
        score, _flags = candidate_quality(word, lexicon, base_score)
        if score < DEFAULT_MIN_CANDIDATE_SCORE:
            continue
        seen.add(word)
        scored_matches.append((score, word))

    scored_matches.sort(key=lambda item: (-item[0], item[1]))
    return [word for _score, word in scored_matches[:DEFAULT_MAX_BRANCH_CANDIDATES]]


def solve_slots(pattern, rows, slots, pool, request_payload, keyword_bank, lexicon, limit=1):
    ai_cache = {}
    solutions = []
    seen_signatures = set()

    def backtrack(assignment):
        if len(solutions) >= limit:
            return True
        if len(assignment) == len(slots):
            signature = tuple((slot["key"], assignment[slot["key"]]) for slot in slots)
            if signature not in seen_signatures:
                seen_signatures.add(signature)
                solutions.append(dict(assignment))
            return len(solutions) >= limit

        grid = build_grid_from_assignment(pattern, rows, slots, assignment)
        ranked = []
        for slot in slots:
            if slot["key"] in assignment:
                continue
            candidates = get_slot_candidates(
                slot,
                grid,
                assignment,
                pool,
                request_payload,
                keyword_bank,
                ai_cache,
                lexicon,
            )
            if not candidates:
                return False
            ranked.append((len(candidates), -slot["length"], slot["key"], slot, candidates))

        ranked.sort()
        _count, _neg_length, _slot_key, chosen_slot, candidates = ranked[0]
        for word in candidates:
            assignment[chosen_slot["key"]] = word
            should_stop = backtrack(assignment)
            assignment.pop(chosen_slot["key"], None)
            if should_stop:
                return True

        return False

    backtrack({})
    if not solutions:
        raise ApiError(
            "Solver could not find a valid fill from the current candidate pool. Try a simpler pattern or stronger theme hints.",
            status=502,
        )
    return solutions


def summarize_solution(words, lexicon):
    total_score = 0
    weak_entries = []
    music_entries = []
    entry_notes = []

    for item in words:
        score, flags = candidate_quality(item["word"], lexicon)
        total_score += score
        note = {
            "word": item["word"],
            "score": score,
            "flags": flags,
        }
        entry_notes.append(note)

        if any(flag in {"preferred", "theme", "music"} for flag in flags):
            music_entries.append(item["word"])

        if score < 0 or any(flag in {"unverified", "awkward", "cluster", "dry", "no-vowels"} for flag in flags):
            weak_entries.append(item["word"])

    quality_flags = []
    if weak_entries:
        label = "weak entry" if len(weak_entries) == 1 else "weak entries"
        quality_flags.append(f"{len(weak_entries)} {label}")
    else:
        quality_flags.append("clean fill")

    if len(music_entries) >= max(2, len(words) // 3):
        quality_flags.append("music-heavy")
    elif music_entries:
        quality_flags.append("has theme entries")

    return {
        "score": total_score,
        "qualityFlags": quality_flags,
        "weakEntries": weak_entries,
        "musicEntries": music_entries,
        "entryNotes": entry_notes,
    }


def build_words_from_assignment(slots, assignment):
    words = []
    for slot in slots:
        words.append({
            "number": slot["number"],
            "row": slot["row"],
            "col": slot["col"],
            "direction": slot["direction"],
            "word": assignment[slot["key"]],
        })
    return words


def assess_pattern(pattern, rows, slots):
    notes = []
    black_count = pattern.count("#")
    full_length_slots = sum(1 for slot in slots if slot["length"] == rows)

    if black_count <= 1:
        notes.append("Wide-open grid: tougher to keep the fill elegant.")
    elif black_count < rows - 1:
        notes.append("Low black-square count raises the odds of crosswordese.")

    if full_length_slots >= rows + 1:
        notes.append("Many full-length slots mean every entry forces a lot of crossings.")

    return notes[:2]


def fallback_clue_text(answer, direction):
    if direction == "across":
        return f"Generated entry built around {answer[0]}..."
    return f"Generated down entry ending in {answer[-1]}"


def build_clue_prompt(words, request_payload, rows, cols):
    entries = [
        {
            "number": word["number"],
            "direction": word["direction"],
            "answer": word["word"],
        }
        for word in words
    ]

    return f"""
Write clues for a music-industry mini crossword.

Return exactly one JSON object with this shape:
{{
  "title": "Title",
  "info": "Sub-header",
  "clues": {{
    "across": [{{"number": 1, "text": "Clue text"}}],
    "down": [{{"number": 1, "text": "Clue text"}}]
  }}
}}

Rules:
- JSON only.
- Keep the clue voice informed, savvy, and occasionally contrarian.
- Be specific to music, media, streaming, touring, labels, fandom, or culture when appropriate.
- Avoid repeating the answer directly inside the clue.

Requested title hint: {normalize_whitespace(request_payload.get("title")) or "(none)"}
Requested info hint: {normalize_whitespace(request_payload.get("info")) or "(none)"}
Grid size: {rows}x{cols}
Entries:
{json.dumps(entries, ensure_ascii=True)}
""".strip()


def parse_clue_response(raw_text, words, request_payload, rows, cols):
    raw_object = json.loads(extract_json_object(raw_text))
    clue_map = clue_map_from_payload(raw_object.get("clues", {}))

    clues = {"across": [], "down": []}
    for word in words:
        direction = word["direction"]
        text = clue_map.get(direction, {}).get(word["number"])
        if not text:
            text = fallback_clue_text(word["word"], direction)
        clues[direction].append({
            "number": word["number"],
            "text": text,
        })

    title = normalize_whitespace(request_payload.get("title") or raw_object.get("title") or "Untitled")
    info = normalize_whitespace(
        request_payload.get("info")
        or raw_object.get("info")
        or f"{rows}×{cols}"
    )
    return title, info, clues


def generate_clues(words, request_payload, rows, cols):
    prompt = build_clue_prompt(words, request_payload, rows, cols)
    try:
        raw_text = call_anthropic(prompt)
        return parse_clue_response(raw_text, words, request_payload, rows, cols)
    except Exception:
        clues = {"across": [], "down": []}
        for word in words:
            clues[word["direction"]].append({
                "number": word["number"],
                "text": fallback_clue_text(word["word"], word["direction"]),
            })
        title = normalize_whitespace(request_payload.get("title") or "Untitled")
        info = normalize_whitespace(request_payload.get("info") or f"{rows}×{cols}")
        return title, info, clues


def normalize_word_entries(raw_words, slots):
    if not isinstance(raw_words, list):
        raise ApiError("Selected option must include a words array.", status=400)

    lookup = {}
    for item in raw_words:
        direction = normalize_whitespace(item.get("direction")).lower()
        if direction not in ("across", "down"):
            continue
        try:
            number = int(item.get("number"))
        except Exception as error:
            raise ApiError("Each selected word needs a numeric number.", status=400) from error
        lookup[(direction, number)] = item

    normalized = []
    placed = {}
    for slot in slots:
        source = lookup.get((slot["direction"], slot["number"]))
        if source is None:
            raise ApiError(f'Missing {slot_label(slot)} in selected option.', status=400)
        word = sanitize_candidate(source.get("word"))
        if len(word) != slot["length"]:
            raise ApiError(
                f'{slot_label(slot)} must be {slot["length"]} letters.',
                status=400,
            )

        for (row, col), letter in zip(slot["cells"], word):
            key = (row, col)
            current = placed.get(key)
            if current not in (None, letter):
                raise ApiError(
                    f"Selected option has a crossing mismatch at row {row}, col {col}.",
                    status=400,
                )
            placed[key] = letter

        normalized.append({
            "number": slot["number"],
            "row": slot["row"],
            "col": slot["col"],
            "direction": slot["direction"],
            "word": word,
        })

    return normalized


def build_puzzle_document(request_payload, words, clues, rows, cols, title=None, info=None):
    resolved_title = normalize_whitespace(request_payload.get("title") or title or "Untitled")
    resolved_info = normalize_whitespace(request_payload.get("info") or info or f"{rows}×{cols}")
    base_slug = normalize_whitespace(request_payload.get("slug") or resolved_title)
    puzzle_id = slugify(base_slug or resolved_title)
    if not puzzle_id:
        raise ApiError("Unable to derive a puzzle id.", status=502)

    return {
        "id": puzzle_id,
        "title": resolved_title,
        "info": resolved_info,
        "gridSize": {
            "rows": rows,
            "cols": cols,
        },
        "words": words,
        "clues": clues,
    }


def build_prompt(request_payload, slots, keyword_bank, rows, cols):
    slot_lines = [
        f'{slot["number"]} {slot["direction"]} starts at row {slot["row"]}, col {slot["col"]}, length {slot["length"]}'
        for slot in slots
    ]

    title_hint = normalize_whitespace(request_payload.get("title"))
    info_hint = normalize_whitespace(request_payload.get("info"))
    slug_hint = normalize_whitespace(request_payload.get("slug"))
    keyword_lines = ", ".join(keyword_bank[:180])

    return f"""
You are filling a music-industry mini crossword for the Stems newsletter.

Requirements:
- Return exactly one JSON object and nothing else.
- Start your response with `{{` and end it with `}}`.
- Do not include prose, explanations, markdown fences, or preambles.
- The JSON schema must be:
  {{
    "id": "slug-name",
    "title": "Title",
    "info": "Sub-header",
    "gridSize": {{"rows": {rows}, "cols": {cols}}},
    "words": [
      {{"number": 1, "row": 0, "col": 0, "direction": "across", "word": "STEMS"}}
    ],
    "clues": {{
      "across": [{{"number": 1, "text": "Newsletter name"}}],
      "down": []
    }}
  }}
- Answers must be uppercase ASCII letters only. No spaces, apostrophes, punctuation, accents, or hyphens in answers.
- Every slot listed below must be filled exactly once.
- Every clue must match its answer.
- Clue voice: informed, savvy, occasionally contrarian, and specific to music/media culture when appropriate.
- Avoid generic crosswordese whenever you can.
- Keep the requested slug if it is usable.

Pattern:
- grid size: {rows}x{cols}
- pattern string: {request_payload["pattern"]}

Slots:
{chr(10).join(slot_lines)}

Requested metadata:
- title hint: {title_hint or "(you decide)"}
- info hint: {info_hint or "(you decide, but include the grid size)"}
- slug hint: {slug_hint or "(you decide)"}

Keyword bank from the newsroom CSV plus user notes:
{keyword_lines}
""".strip()


def build_retry_prompt(base_prompt, previous_error, attempt_number):
    return (
        f"{base_prompt}\n\n"
        f"Previous attempt {attempt_number - 1} failed validation with this exact error:\n"
        f"{previous_error}\n\n"
        "Try again from scratch. Double-check every crossing before returning JSON. "
        "Do not reuse the invalid grid. Your reply must be raw JSON only."
    )


def preview_text(value, limit=280):
    compact = " ".join(str(value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def extract_text_blocks(response_payload):
    parts = []
    for block in response_payload.get("content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts).strip()


def strip_code_fences(raw_text):
    fenced = re.match(r"^```(?:json)?\s*(.*)\s*```$", raw_text, flags=re.DOTALL)
    return fenced.group(1).strip() if fenced else raw_text.strip()


def extract_json_object(raw_text):
    candidate = strip_code_fences(raw_text)
    start = candidate.find("{")
    if start == -1:
        raise ApiError("Claude response did not include a JSON object.", status=502)

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(candidate)):
        char = candidate[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return candidate[start:index + 1]

    raise ApiError("Claude returned malformed JSON.", status=502)


def call_anthropic(prompt_text):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ApiError("ANTHROPIC_API_KEY is not configured.", status=500)

    payload = json.dumps({
        "model": DEFAULT_MODEL,
        "max_tokens": 3200,
        "temperature": 0.35,
        "system": "You are an expert crossword constructor. Return JSON only.",
        "messages": [{"role": "user", "content": prompt_text}],
    }).encode("utf-8")

    request = urllib_request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise ApiError(f"Anthropic API error: {details}", status=502) from error
    except urllib_error.URLError as error:
        raise ApiError(f"Anthropic API network error: {error.reason}", status=502) from error

    return extract_text_blocks(body)


def sanitize_answer(raw_value):
    cleaned = normalize_whitespace(raw_value).upper()
    cleaned = re.sub(r"[^A-Z]", "", cleaned)
    return cleaned


def clue_map_from_payload(clues_payload):
    if not isinstance(clues_payload, dict):
        raise ApiError("Claude response must include a clues object.", status=502)

    output = {"across": {}, "down": {}}
    for direction in ("across", "down"):
        entries = clues_payload.get(direction, [])
        if not isinstance(entries, list):
            raise ApiError(f"clues.{direction} must be an array.", status=502)
        for entry in entries:
            try:
                number = int(entry.get("number"))
            except Exception as error:
                raise ApiError(f"Each {direction} clue needs a numeric number.", status=502) from error
            text = normalize_whitespace(entry.get("text"))
            if not text:
                raise ApiError(f"Missing text for {direction} clue {number}.", status=502)
            output[direction][number] = text
    return output


def normalize_puzzle(raw_puzzle, request_payload, slots, rows, cols):
    if not isinstance(raw_puzzle, dict):
        raise ApiError("Claude output was not a JSON object.", status=502)

    raw_words = raw_puzzle.get("words")
    if not isinstance(raw_words, list):
        raise ApiError("Claude output must include a words array.", status=502)

    word_lookup = {}
    for raw_word in raw_words:
        direction = normalize_whitespace(raw_word.get("direction")).lower()
        if direction not in ("across", "down"):
            continue

        number_value = raw_word.get("number")
        row_value = raw_word.get("row")
        col_value = raw_word.get("col")

        try:
            number = int(number_value)
        except Exception:
            number = None

        key = (direction, number)
        if number is not None:
            word_lookup[key] = raw_word
            continue

        try:
            row = int(row_value)
            col = int(col_value)
        except Exception:
            continue
        word_lookup[(direction, row, col)] = raw_word

    clues = clue_map_from_payload(raw_puzzle.get("clues", {}))
    matrix = pattern_to_matrix(request_payload["pattern"], rows)
    filled = [[None if cell == "#" else "" for cell in row] for row in matrix]
    normalized_words = []

    for slot in slots:
        source = word_lookup.get((slot["direction"], slot["number"]))
        if source is None:
            source = word_lookup.get((slot["direction"], slot["row"], slot["col"]))
        if source is None:
            raise ApiError(
                f'Claude did not supply {slot["number"]} {slot["direction"]}.',
                status=502,
            )

        answer = sanitize_answer(source.get("word"))
        if len(answer) != slot["length"]:
            raise ApiError(
                f'{slot["number"]} {slot["direction"]} should be {slot["length"]} letters, got "{answer}".',
                status=502,
            )

        row = slot["row"]
        col = slot["col"]
        for letter in answer:
            current = filled[row][col]
            if current not in ("", letter):
                raise ApiError(
                    f'Crossing mismatch at row {row}, col {col} for {slot["number"]} {slot["direction"]}.',
                    status=502,
                )
            filled[row][col] = letter
            if slot["direction"] == "across":
                col += 1
            else:
                row += 1

        normalized_words.append({
            "number": slot["number"],
            "row": slot["row"],
            "col": slot["col"],
            "direction": slot["direction"],
            "word": answer,
        })

    normalized_clues = {"across": [], "down": []}
    for slot in slots:
        clue_text = clues[slot["direction"]].get(slot["number"])
        if not clue_text:
            raise ApiError(
                f'Missing clue text for {slot["number"]} {slot["direction"]}.',
                status=502,
            )
        normalized_clues[slot["direction"]].append({
            "number": slot["number"],
            "text": clue_text,
        })

    title = normalize_whitespace(request_payload.get("title") or raw_puzzle.get("title") or "Untitled")
    info = normalize_whitespace(
        request_payload.get("info")
        or raw_puzzle.get("info")
        or f"{rows}×{cols}"
    )
    base_slug = normalize_whitespace(request_payload.get("slug") or raw_puzzle.get("id") or title)
    puzzle_id = slugify(base_slug or title)
    if not puzzle_id:
        raise ApiError("Unable to derive a puzzle id.", status=502)

    return {
        "id": puzzle_id,
        "title": title,
        "info": info,
        "gridSize": {
            "rows": rows,
            "cols": cols,
        },
        "words": normalized_words,
        "clues": normalized_clues,
    }


def build_option_set(request_payload):
    rows, cols = parse_grid_size(request_payload)
    pattern = request_payload.get("pattern")
    validate_pattern(pattern, rows, cols)

    orphans = find_orphan_white_cells(pattern, rows)
    if orphans:
        rendered = ", ".join(f"[{row},{col}]" for row, col in orphans[:8])
        raise ApiError(
            f"Pattern contains isolated white cells that do not belong to valid across/down answers: {rendered}.",
            status=400,
        )

    slots = annotate_slots(detect_slots(pattern, rows))
    if not slots:
        raise ApiError("Pattern does not contain any valid answer slots.", status=400)

    incoming_keywords = request_payload.get("keywords", [])
    if isinstance(incoming_keywords, str):
        incoming_keywords = [incoming_keywords]
    if not isinstance(incoming_keywords, list):
        raise ApiError("keywords must be an array or a string.", status=400)

    keyword_bank = load_keyword_bank(incoming_keywords)
    lexicon = build_fill_lexicon(incoming_keywords, keyword_bank, max(rows, cols))
    candidate_pool = build_local_candidate_pool(incoming_keywords, keyword_bank, max(rows, cols), lexicon)
    pattern_notes = assess_pattern(pattern, rows, slots)
    search_limit = max(DEFAULT_GRID_OPTIONS * DEFAULT_SOLVER_SEARCH_MULTIPLIER, DEFAULT_GRID_OPTIONS)
    assignments = solve_slots(
        pattern,
        rows,
        slots,
        candidate_pool,
        request_payload,
        keyword_bank,
        lexicon,
        limit=search_limit,
    )

    options = []
    for assignment in assignments:
        words = build_words_from_assignment(slots, assignment)
        summary = summarize_solution(words, lexicon)
        options.append({
            "gridSize": {
                "rows": rows,
                "cols": cols,
            },
            "qualityScore": summary["score"],
            "qualityFlags": summary["qualityFlags"],
            "weakEntries": summary["weakEntries"],
            "musicEntries": summary["musicEntries"],
            "entryNotes": summary["entryNotes"],
            "words": words,
        })

    options.sort(
        key=lambda option: (
            -option["qualityScore"],
            len(option["weakEntries"]),
            -len(option["musicEntries"]),
        )
    )
    options = options[:DEFAULT_GRID_OPTIONS]

    for index, option in enumerate(options, start=1):
        option["optionId"] = f"option-{index}"
        option["label"] = f"Option {index}"

    return {
        "mode": "options",
        "title": normalize_whitespace(request_payload.get("title") or "Untitled"),
        "info": normalize_whitespace(request_payload.get("info") or f"{rows}×{cols}"),
        "gridSize": {
            "rows": rows,
            "cols": cols,
        },
        "patternNotes": pattern_notes,
        "options": options,
    }


def build_clued_puzzle(request_payload):
    rows, cols = parse_grid_size(request_payload)
    pattern = request_payload.get("pattern")
    validate_pattern(pattern, rows, cols)
    slots = annotate_slots(detect_slots(pattern, rows))
    words = normalize_word_entries(request_payload.get("words", []), slots)
    title, info, clues = generate_clues(words, request_payload, rows, cols)
    return build_puzzle_document(request_payload, words, clues, rows, cols, title=title, info=info)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        json_response(self, 200, {"ok": True})

    def do_GET(self):
        json_response(self, 200, {"ok": True, "route": "api/generate"})

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8") or "{}")
            mode = normalize_whitespace(payload.get("mode") or "options").lower()
            if mode == "clues":
                response = build_clued_puzzle(payload)
            else:
                response = build_option_set(payload)
            json_response(self, 200, response)
        except ApiError as error:
            json_response(self, error.status, {"error": error.message})
        except json.JSONDecodeError:
            json_response(self, 400, {"error": "Request body must be valid JSON."})
        except Exception as error:
            json_response(self, 500, {"error": f"Unexpected server error: {error}"})
