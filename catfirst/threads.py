"""catFirst (not the camera tracker): public Threads posts about cats, by keyword, to reply by hand.

Logged out, in headless Chromium: the search page's HTML holds no posts, its own scripts load
them. For each keyword of the sheet's «Ключевые слова» tab, threads.com/search?q=<keyword>.
Without a login the search shows only its top ~25 posts (no "Recent" tab, nothing more on
scroll), so the run repeats once a day and keeps what is new. A post is kept when it is at most
MAX_AGE_DAYS old and its text talks about cats. New posts go on top of the tab of their keyword's
language (POSTS_TABS; any other language - the English one), with a light green row between them
and the posts of an earlier day. The user's columns (Ответил, Комментарий) are never rewritten,
and a post the user deleted does not come back (the hidden «threads_seen» tab remembers every
post added).

A login wall or a challenge page stops the run: nothing is worked around.
Logs hold counts only - no authors, texts or links (the repository is public).
"""
import hashlib
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

import gspread
from gspread.utils import ValueRenderOption

from tracker import env

# sha256 of the catFirst spreadsheet key: the key itself stays out of this public repository,
# the run finds the sheet among the ones shared with the service account.
# CATFIRST_SHEET_ID, when set, is used instead.
SHEET_KEY_SHA256 = "98dafd11118df5b9cad590b7ce8806293a2937496970d3d849633a076131e1d1"

POSTS_TABS = {"EN": "Threads — английский", "DE": "Threads — немецкий"}
OLD_POSTS_TAB = "Threads"  # all languages in one tab, first run of 2026-11-01: split once
KEYWORDS_TAB = "Ключевые слова"
SEEN_TAB = "threads_seen"
POSTS_HEADER = ["Найден", "Дата поста", "Ключевые слова", "Автор", "Текст",
                "Лайки", "Ответы", "Ссылка", "Ответил", "Комментарий"]
POSTS_WIDTHS = [120, 120, 150, 140, 460, 60, 60, 300, 70, 220]
ANSWERED_COL = 8  # 0-based index of «Ответил»: a checkbox
DAY_COLOR = {"red": 0.851, "green": 0.918, "blue": 0.827}  # light green 3
WHITE = {"red": 1, "green": 1, "blue": 1}
DAY = re.compile(r"^\d\d\.\d\d\.\d{4}")
KEYWORDS_HEADER = ["Слово", "Язык", "Постов в выдаче", "Свежих о кошках", "Новых", "Проверено"]

# Checked logged out on 2026-11-01: each gives a page of posts, mostly from the last two weeks.
# "cat vet", "adopted a cat", "first time cat owner", "indoor cat", "Tierschutz", "Katzenbaby",
# "Wohnungskatze", "Katzenhaltung", "Katze Tierarzt" gave nothing at all; "Kater" is a hangover too.
DEFAULT_KEYWORDS = [
    ("kitten", "EN"), ("new kitten", "EN"), ("rescue cat", "EN"), ("shelter cat", "EN"),
    ("cat shelter", "EN"), ("foster kittens", "EN"), ("cat adoption", "EN"), ("sick cat", "EN"),
    ("senior cat", "EN"), ("cat health", "EN"), ("cat food", "EN"), ("cat mom", "EN"),
    ("cats of threads", "EN"), ("vet", "EN"),
    ("Katze", "DE"), ("Katzen", "DE"), ("Katzenfutter", "DE"), ("Tierarzt", "DE"),
    ("Tierheim", "DE"), ("Katzenleben", "DE"), ("Katzenliebe", "DE"), ("Katzenmama", "DE"),
    ("Pflegestelle", "DE"),
]

MAX_AGE_DAYS = 14
TEXT_MAX = 500
PAUSE_S = (20, 40)
WAIT_S = 20
NO_ANSWER_STOP = 3  # keywords in a row with neither posts nor "no results": stop
SEEN_MAX = 20000

# "vet", "Tierarzt", "Tierheim" are about dogs just as often: the text must name a cat.
CAT_WORDS = re.compile(
    r"\bcats?\b|#cat|kitten|kitty|kitties|feline|\bmeow|katz|kätzchen|\bkater\b|mieze|"
    r"stubentiger|samtpfote", re.I)

# Top-level posts of the search page (a quoted post sits inside its post's container).
EXTRACT_JS = r"""() => {
  const top = [...document.querySelectorAll('div[data-pressable-container="true"]')]
    .filter(c => !c.parentElement.closest('div[data-pressable-container="true"]'));
  const posts = [];
  for (const c of top) {
    const href = [...c.querySelectorAll('a[href*="/post/"]')].map(a => a.getAttribute('href'))
      .find(h => /^\/@[^/]+\/post\/[^/?#]+$/.test(h));
    const time = c.querySelector('time[datetime]');
    if (!href || !time) continue;
    const author = href.split('/')[1].slice(1);
    const buttons = new Set([...c.querySelectorAll('[role="button"]')].map(b => b.innerText.trim()));
    const skip = new Set([author, time.innerText.trim()]);
    const text = [];
    for (const line of c.innerText.split('\n').map(s => s.trim()).filter(Boolean)) {
      if (skip.has(line)) { skip.delete(line); continue; }
      if (!buttons.has(line)) text.push(line);
    }
    const label = s => (s.querySelector('title')?.textContent || s.getAttribute('aria-label') || '').trim();
    const icons = [...c.querySelectorAll('svg')].filter(s => s.closest('[role="button"]') && label(s));
    // like, reply, repost, share are the last four icons
    const count = (re, fromEnd) => {
      const s = icons.find(s => re.test(label(s))) || (icons.length >= 4 ? icons[icons.length - fromEnd] : null);
      return s ? s.closest('[role="button"]').innerText.trim() : '';
    };
    posts.push({href, author, at: time.getAttribute('datetime'), text: text.join('\n'),
                likes: count(/^like$/i, 4), replies: count(/^(reply|comment)$/i, 3)});
  }
  return {posts, empty: /No results|Ничего не найдено/.test(document.body.innerText)};
}"""


class Blocked(RuntimeError):
    pass


def count_label(label):
    """'1.2K' -> 1200, '8,098' -> 8098, '' -> 0."""
    s = re.sub(r"[\s, ]", "", label or "").upper()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([KM]?)", s)
    if not m:
        return 0
    return round(float(m.group(1)) * {"": 1, "K": 1000, "M": 1000000}[m.group(2)])


def post_code(href):
    return href.rsplit("/post/", 1)[1]


def about_cats(text):
    return bool(CAT_WORDS.search(text or ""))


def open_sheet(client):
    key = os.environ.get("CATFIRST_SHEET_ID", "").strip()
    if key:
        return client.open_by_key(key)
    for f in client.list_spreadsheet_files():
        if hashlib.sha256(f["id"].encode()).hexdigest() == SHEET_KEY_SHA256:
            return client.open_by_key(f["id"])
    raise env.ConfigError("the catFirst sheet is not shared with the service account")


def _tab(sh, title, header, rows=1000):
    """The tab `title`, created with a bold frozen header when missing. Returns (ws, created)."""
    try:
        return sh.worksheet(title), False
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=rows, cols=len(header))
        ws.update(values=[header], range_name="A1", value_input_option="RAW")
        ws.format("1:1", {"textFormat": {"bold": True}})
        ws.freeze(rows=1)
        return ws, True


def keyword_rows(ws, created):
    if created:
        ws.update(values=[list(k) for k in DEFAULT_KEYWORDS], range_name="A2",
                  value_input_option="RAW")
    keywords = []
    for r in ws.get_values("A2:F"):
        r = r + [""] * (6 - len(r))
        if r[0].strip():
            keywords.append((r[0].strip(), r[1].strip(), r[2:6]))
    return keywords


def tab_lang(lang):
    lang = (lang or "").strip().upper()
    return lang if lang in POSTS_TABS else "EN"


def posts_tab(sh, lang):
    ws, created = _tab(sh, POSTS_TABS[tab_lang(lang)], POSTS_HEADER)
    if created:
        sh.batch_update({"requests": [
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                "properties": {"pixelSize": w}, "fields": "pixelSize"}}
            for i, w in enumerate(POSTS_WIDTHS)]})
    return ws


def insert_block(sh, ws, rows, day=None):
    """`rows` on top of `ws`, and under them a light green row when the posts below were found on
    an earlier day than `day` (a second run of the same day adds to its block)."""
    top = ws.get_values("A2:A2")
    below = DAY.match(top[0][0]) if top and top[0] else None
    split = bool(day and below and below.group(0) != day)
    values = [list(r) for r in rows]
    if split:
        values.append([f"Выше — {day}, ниже — {below.group(0)}"] + [""] * (len(POSTS_HEADER) - 1))
    ws.insert_rows(values, row=2, value_input_option="RAW")

    def cells(r0, r1, c0=0, c1=len(POSTS_HEADER)):
        return {"sheetId": ws.id, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    n = len(rows)
    # inserted rows take the format of the row under them: set it explicitly
    requests = [
        {"repeatCell": {"range": cells(1, 1 + n),
                        "cell": {"userEnteredFormat": {"backgroundColor": WHITE, "textFormat": {"bold": False}}},
                        "fields": "userEnteredFormat(backgroundColor,textFormat.bold)"}},
        {"setDataValidation": {"range": cells(1, 1 + n, ANSWERED_COL, ANSWERED_COL + 1),
                               "rule": {"condition": {"type": "BOOLEAN"}}}},
    ]
    if split:
        requests += [
            {"repeatCell": {"range": cells(1 + n, 2 + n),
                            "cell": {"userEnteredFormat": {"backgroundColor": DAY_COLOR, "textFormat": {"bold": True}}},
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold)"}},
            {"setDataValidation": {"range": cells(1 + n, 2 + n)}},  # no rule: no checkbox
        ]
    sh.batch_update({"requests": requests})


def split_old_tab(sh):
    """Rows of the one «Threads» tab of the first run, moved to the tabs of their language (its
    column C) with the user's ticks and comments; the tab is deleted. Returns the rows moved."""
    try:
        old = sh.worksheet(OLD_POSTS_TAB)
    except gspread.WorksheetNotFound:
        return 0
    by_lang = {}
    for r in old.get_values("A2:K", value_render_option=ValueRenderOption.unformatted):
        r = list(r) + [""] * (11 - len(r))
        if str(r[0]).strip():
            by_lang.setdefault(tab_lang(str(r[2])), []).append(r[:2] + r[3:])
    for lang, rows in by_lang.items():
        insert_block(sh, posts_tab(sh, lang), rows)
    sh.del_worksheet(old)
    return sum(len(rows) for rows in by_lang.values())


def seen_tab(sh):
    ws, created = _tab(sh, SEEN_TAB, ["post", "added"], rows=100)
    if created:
        ws.hide()
    return ws


def search(page, keyword):
    """{'posts': [...], 'empty': bool} of the logged-out search page; posts=[] and empty=False
    when the page gave neither within WAIT_S."""
    page.goto(f"https://www.threads.com/search?q={quote(keyword)}&serp_type=default",
              wait_until="domcontentloaded", timeout=60000)
    deadline = time.monotonic() + WAIT_S
    result, last = {"posts": [], "empty": False}, -1
    while time.monotonic() < deadline:
        path = urlparse(page.url).path
        if path.startswith("/login") or "challenge" in path or "checkpoint" in path:
            raise Blocked("login wall")
        result = page.evaluate(EXTRACT_JS)
        n = len(result["posts"])
        if result["empty"] or (n and n == last):  # posts stopped coming in
            break
        last = n
        page.wait_for_timeout(2000)
    return result


def collect(keywords, seen, now):
    """New fresh cat posts by post code, and per keyword (posts on page, fresh cat posts, new)."""
    from playwright.sync_api import sync_playwright

    new, stats, no_answer = {}, {}, 0
    order = list(keywords)
    random.shuffle(order)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(locale="en-US", timezone_id="Europe/Berlin",
                                   viewport={"width": 1280, "height": 1800}).new_page()
        try:
            for i, (word, lang, _) in enumerate(order):
                if i:
                    time.sleep(random.uniform(*PAUSE_S))
                try:
                    result = search(page, word)
                except Blocked as e:
                    print(f"threads: stopped after {i} keywords: {e}")
                    break
                posts = result["posts"]
                if posts or result["empty"]:
                    no_answer = 0
                else:
                    no_answer += 1
                    if no_answer >= NO_ANSWER_STOP:
                        print(f"threads: stopped after {i + 1} keywords: {no_answer} pages in a row gave nothing")
                        break
                fresh = added = 0
                for post in posts:
                    at = datetime.fromisoformat(post["at"].replace("Z", "+00:00"))
                    if now - at > timedelta(days=MAX_AGE_DAYS) or not about_cats(post["text"]):
                        continue
                    fresh += 1
                    code = post_code(post["href"])
                    if code in seen:
                        continue
                    if code in new:
                        new[code]["keywords"].append(word)
                        continue
                    new[code] = {**post, "at": at, "lang": lang, "keywords": [word]}
                    added += 1
                stats[word] = (len(posts), fresh, added)
        finally:
            browser.close()
    return new, stats


def post_row(post, found):
    return [
        found,
        post["at"].astimezone(env.BERLIN).strftime("%d.%m.%Y %H:%M"),
        ", ".join(post["keywords"]),
        post["author"],
        post["text"][:TEXT_MAX],
        count_label(post["likes"]),
        count_label(post["replies"]),
        "https://www.threads.com" + post["href"],
        "",
        "",
    ]


def write(sh, ws_seen, seen_count, ws_keywords, keywords, new, stats, found):
    if new:
        by_lang = {}
        for p in sorted(new.values(), key=lambda p: p["at"], reverse=True):
            by_lang.setdefault(tab_lang(p["lang"]), []).append(post_row(p, found))
        for lang, rows in by_lang.items():
            insert_block(sh, posts_tab(sh, lang), rows, day=found[:10])
        ws_seen.append_rows([[code, found] for code in new], value_input_option="RAW")
        total = seen_count + len(new)
        if total > SEEN_MAX + 1000:  # oldest first
            ws_seen.delete_rows(2, 1 + total - SEEN_MAX)
    # keywords left unsearched (a stopped run) keep their last numbers
    rows = [[*stats[word], found] if word in stats else old for word, _, old in keywords]
    if rows:
        ws_keywords.update(values=rows, range_name=f"C2:F{1 + len(rows)}", value_input_option="RAW")


def main():
    client = gspread.service_account_from_dict(env.google_sa_info())
    sh = open_sheet(client)
    ws_keywords, created = _tab(sh, KEYWORDS_TAB, KEYWORDS_HEADER)
    keywords = keyword_rows(ws_keywords, created)
    moved = split_old_tab(sh)
    if moved:
        print(f"threads: {moved} posts of the old tab moved to the language tabs")
    ws_seen = seen_tab(sh)
    seen = {r[0] for r in ws_seen.get_values("A2:A") if r and r[0]}
    if not keywords:
        print("threads: no keywords")
        return 0
    now = datetime.now(timezone.utc)
    new, stats = collect(keywords, seen, now)
    found = env.now_berlin().strftime("%d.%m.%Y %H:%M")
    write(sh, ws_seen, len(seen), ws_keywords, keywords, new, stats, found)
    on_page = sum(s[0] for s in stats.values())
    fresh = sum(s[1] for s in stats.values())
    empty = sum(1 for s in stats.values() if not s[0])
    print(f"threads: keywords {len(keywords)}, searched {len(stats)}, empty {empty}, "
          f"posts {on_page}, fresh cat posts {fresh}, new {len(new)}")
    # nothing at all: the search does not answer this machine
    return 0 if on_page else 1


if __name__ == "__main__":
    sys.exit(main())
