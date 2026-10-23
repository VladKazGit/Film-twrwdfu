"""One tracker tick: catalog -> item checks -> data repo -> Google Sheet.

Run:  python -m tracker.tick [--quick] [--force] [--local DIR] [--no-sheets] [--max-requests N]
Logs contain aggregates only: no titles, ids or names.

Schedule (CLAUDE.md): every tick reads catalog pages 1-2, every 4 hours pages
1-10. A tracked item missing from the pages although its id is above the
coverage boundary has "vanished" and its page is opened. Items beyond the
covered pages are checked by age: list items every tick (< 3 h), every 4 h
(3-24 h), daily (1-30 days); 'rest' items only during their first 3 hours.

Quick checks (--quick) run every 5 minutes between ticks: catalog page 1 only, new
items, descriptions of new list cameras and pages of fresh list cameras that
vanished (possible fast sales). The sheet is written only if 'Список' changed.
"""
import argparse
import sys

import gspread
import requests
from dataclasses import dataclass
from datetime import date, timedelta
import tempfile
import time
import traceback
from collections import Counter
from pathlib import Path

from . import ageest, clock, env, models, notify, report
from .store import DataStore
from .vinted import EXTRA_CATEGORY_IDS, MAX_PAGES, PARTS_CATEGORY_ID, BlockedError, VintedClient, VintedError, age_days

WINDOW_START_HOUR = 7  # Berlin; the window ends at midnight
TICK_PAGES = 2
FULL_SCAN_EVERY_MIN = 240
REST_MIN_PRICE = 3.0
REST_TRACK_MIN = 180
LIST_TRACK_MIN = 30 * 1440
MAX_REQUESTS = 115
TICK_TIME_BUDGET_S = 9 * 60  # Vinted traffic per tick; the rest goes to the next tick
QUICK_PAGES, QUICK_TIME_BUDGET_S = 1, 150  # quick checks between ticks (cheap ones end long before)
CHEAP_PRICE = 20.0  # the cheap check and 'До 20 €' (sheets.CHEAP_MAX_PRICE)
# Extra categories: page 1 per check; on full scans (the morning after the night, then every 4 h) 3 pages
EXTRA_FULL_PAGES = 3
# Fresh search: every model of 'Модели' once an hour, newest first in all categories; one more
# page per 35 active cameras of the model (up to 8; the key models per 25, up to 10, and their
# page 1 in every tick too). A page of all categories holds ~40 of the model's cameras: reading
# a little past them catches the sales of popular models within the hour (+~13 pages an hour).
FRESH_EVERY_MIN, FRESH_PER_CHECK, FRESH_HOURS = 60, 16, 24
FRESH_PER_CHEAP = 5  # a cheap check takes a few models too, so the round stays within the hour
FRESH_PAGE_ITEMS, FRESH_MAX_PAGES = 35, 8
FRESH_PRIORITY_PAGE_ITEMS, FRESH_PRIORITY_MAX_PAGES = 25, 10
FRESH_PRIORITY = ("Canon AE-1", "Yashica FX-3 Super 2000", "Olympus OM-10")
PAGE_RECHECK_MIN = 5 * 1440  # a camera the fresh search keeps seeing: its page every 5 days
DAILY_CHECKS_PER_TICK = 25
DESCRIPTION_CHECKS_PER_TICK = 15
BOUNDARY_TAIL = 10



@dataclass(frozen=True)
class Sweep:
    """A search pass for older list cameras (listed before the tracker saw them, never bumped)."""
    key: str              # state key
    queries: tuple        # (search text, model it targets or None)
    max_price: object     # None: any price
    max_pages: int
    pages_per_tick: int
    checks_per_tick: int  # candidate item pages opened per tick (age check)
    daily: bool           # one pass per day; otherwise passes run back to back
    presence: bool        # a tracked 'found' camera missing from its model's results gets checked
    fill_pages_per_tick: int = 0  # faster until the first pass is done (0: no difference)


SEARCH_MAX_PRICE_CHEAP = 20  # enrichment goes first to cameras for 'До 20 €'
# Cheap cameras by brand, refreshed daily for 'До 20 €'.
CHEAP_SWEEP = Sweep("search", tuple((q, None) for q in (
    "zenit", "zenith", "fed", "zorki", "kiev", "praktica", "canon", "nikon", "pentax", "olympus",
    "minolta", "konica", "yashica", "mamiya", "contax", "leica", "hasselblad", "rollei")), 20, 4, 3, 6, True, True)
# Every list model at any price. The first pass runs fast (20 pages per tick; ages come
# from the id, no item page per candidate); afterwards 2 pages per tick.
MODEL_SWEEP = Sweep("model_search", tuple((m.lower(), m) for m in models.MODEL_INFO), None, 10, 2, 60, False, True,
                    fill_pages_per_tick=20)
SWEEPS = (CHEAP_SWEEP, MODEL_SWEEP)
FOUND_MAX_AGE_DAYS = 183  # half a year on Vinted
FOUND_MIN_ID = 8_300_000_000  # older ids are well over half a year old: skipped without opening
OLD_ON_VINTED_DAYS = 30  # cameras listed on Vinted longer ago than this ...
OLD_RECHECK_MIN = 5 * 1440  # ... are checked every 5 days instead of daily
NEW_ROWS_HOURS = 12  # light blue 3: cameras first seen within this many hours
FRESH_ROWS_HOURS = 3  # light green 3, like 'активен' (above the blue): within this many hours
FOUND_CHECKS_PER_TICK = 15
# Labelled ids the tracker never saw: opened this many per tick, given up after a few failed tries.
LABELLED_PER_TICK, LABELLED_MAX_TRIES = 5, 3
# Found cameras are added with an age estimated from the id, then each item page is
# opened once (exact age, description, kit, status): more per tick once the first pass is done.
ENRICH_PER_TICK, ENRICH_PER_TICK_AFTER_FILL = 20, 40

LIST_BRANDS = {brand for brand, *_ in models.MODELS}
SIGNAL_FLAGS = {"accessory?", "digital?", "compact?"}

# Check priorities: catalog -> list -> rest.
P_LIST_VANISHED, P_LIST_DUE, P_LIST_DAILY, P_FOUND, P_ENRICH, P_DESCRIPTION, P_REST_VANISHED, P_REST_DUE = range(8)


# ---------------------------------------------------------------- item updates

def new_item(rec, now, listed_after, extra_flags):
    cls = models.classify(rec["title"], vinted_brand=rec["brand"])
    return {
        "id": rec["id"],
        "url": rec["url"],
        "title": rec["title"],
        "description": None,
        "condition": rec["condition"],
        "brand": cls["brand"],
        "vinted_brand": rec["brand"],
        "model": cls["model"],
        "model_source": cls["model_source"],
        "in_list": cls["in_list"],
        "group": "list" if cls["in_list"] and not SIGNAL_FLAGS & set(cls["flags"]) else "rest",
        "mech_type": cls["mech_type"],
        "region": cls["region"],
        "format": cls["format"],
        "kit": cls["kit"],
        "kit_details": cls["kit_details"],
        "seller_id": rec["seller_id"],
        "price_start": rec["price"],
        "price_final": None,
        "price_history": [{"at": now, "price": rec["price"]}],
        "favourites": rec.get("favourites"),
        "favourites_history": [] if rec.get("favourites") is None else [{"at": now, "count": rec["favourites"]}],
        "photo": rec.get("photo"),
        "listed_after": listed_after,
        "first_seen": now,
        "last_seen_active": now,
        "last_checked_at": now,
        "sold_detected_at": None,
        "closed_at": None,
        "status": "active",
        "time_to_sell_min": None,
        "time_to_sell_max": None,
        "flags": cls["flags"] + extra_flags,
        "description_checked": False,
    }


def _set_price(item, price, now):
    if price is not None and item["price_history"][-1]["price"] != price:
        item["price_history"].append({"at": now, "price": price})


def _set_favourites(item, count, now):
    """Users' saves: keep the latest count and every change."""
    if count is not None and item.get("favourites") != count:
        item["favourites"] = count
        item.setdefault("favourites_history", []).append({"at": now, "count": count})


def mark_seen(item, rec, now, checked=True):
    """Item is in the catalog (or in search results): it is active now.

    A search sighting is not a check (checked=False): it must not postpone the
    scheduled page check of an old camera.
    """
    item["status"] = "active"
    item["last_seen_active"] = now
    if checked:
        item["last_checked_at"] = now
    _set_price(item, rec["price"], now)
    _set_favourites(item, rec.get("favourites"), now)
    if rec.get("photo") and not item.get("photo"):
        item["photo"] = rec["photo"]


def close(item, status, now, price=None):
    item["status"] = status
    item["closed_at"] = now
    if status == "sold":
        item["sold_detected_at"] = now
        item["price_final"] = price if price is not None else item["price_history"][-1]["price"]
        item["time_to_sell_min"] = max(0, clock.minutes_between(item["first_seen"], item["last_seen_active"]))
        if item.get("listed_after"):
            item["time_to_sell_max"] = clock.minutes_between(item["listed_after"], now)
        item["days_to_sell"] = report.days_to_sell(item)


def group_of(item):
    """'list' for list cameras; accessories and digital cameras go to the rest even with a model."""
    return "list" if item.get("in_list") and not SIGNAL_FLAGS & set(item.get("flags") or []) else "rest"


def is_junk(item):
    """A listing outside the list not worth keeping: an accessory, digital or compact camera, or a
    kind of no interest (instant, APS, toys, movie cameras, flashes, modern autofocus, ...)."""
    if item.get("group") == "list" or item.get("model_source") == "manual":
        return False
    return bool(SIGNAL_FLAGS & set(item.get("flags") or [])) or bool(
        models.junk_reason(item.get("title") or "", item.get("vinted_brand")))


def worth_tracking(item):
    """List cameras; other cameras from REST_MIN_PRICE up that are not junk."""
    return item["group"] == "list" or ((item.get("price_start") or 0) >= REST_MIN_PRICE and not is_junk(item))


def _refresh_signal_flags(item):
    """Accessory/digital flags again, now with the description (manual labels stay)."""
    if item.get("model_source") == "manual":
        return
    cls = models.classify(item["title"], item.get("description"), item.get("vinted_brand"))
    item["flags"] = [f for f in item["flags"] if f not in SIGNAL_FLAGS] + sorted(SIGNAL_FLAGS & set(cls["flags"]))
    item["group"] = group_of(item)


def set_model(item, model, source):
    """Apply a model (from description or manual labeling) and move the item to its group."""
    info = models.MODEL_INFO.get(model)
    item["model"] = model
    item["model_source"] = source
    item["in_list"] = info is not None
    if info:
        item.update(brand=info["brand"], mech_type=info["mech_type"], format=info["format"], region=info["region"])
    if not item.get("closed_at"):
        item["group"] = group_of(item)


def apply_page(item, page, now):
    """Update an item from its page. Returns the page status."""
    item["last_checked_at"] = now
    item.pop("needs_check", None)
    _remember_vinted_age(item, page.get("uploaded_ago"), now)
    _set_favourites(item, page.get("favourites"), now)
    if page.get("photo") and not item.get("photo"):
        item["photo"] = page["photo"]
    if page["description"] and not item.get("description"):
        item["description"] = page["description"]
        _refresh_signal_flags(item)
        kit, details = models.kit_of(f"{item['title']} {page['description']}")
        item["kit"], item["kit_details"] = kit, details
    status = page["status"]
    if status == "active":
        item["status"] = "active"
        item["last_seen_active"] = now
        _set_price(item, page["price"], now)
    elif status in ("reserved", "hidden"):
        item["status"] = status
    elif status == "sold":
        close(item, "sold", now, page["price"])
    elif status == "deleted":
        close(item, "deleted", now)
    return status


def _remember_vinted_age(item, uploaded_ago, now):
    """Keep the first known Vinted upload age ('Hochgeladen') as the listing date; it
    replaces an estimate by id. A found camera older than half a year is marked too old."""
    days = age_days(uploaded_ago)
    if days is None or (item.get("vinted_listed_est") and item.get("age_source") != "id"):
        return
    item["uploaded_ago"] = uploaded_ago
    item["vinted_listed_est"] = (clock.parse(now) - timedelta(days=days)).strftime("%Y-%m-%d")
    if item.get("age_source") == "id":
        item["age_source"] = "vinted"
        item["age_days_at_discovery"] = days - clock.minutes_between(item["first_seen"], now) // 1440
        if "found" in item["flags"] and days > FOUND_MAX_AGE_DAYS:
            item["too_old"] = True


def add_labelled(item_id, model, page, now):
    """A card for a camera from 'Ручная разметка' the tracker never saw. Its listing time is
    unknown, so it is flagged 'found' (out of the speed statistics)."""
    rec = {"id": item_id, "url": f"https://www.vinted.de/items/{item_id}", "title": page.get("title") or "",
           "brand": page.get("brand"), "condition": page.get("condition"), "seller_id": None,
           "price": page.get("price"), "favourites": page.get("favourites")}
    item = new_item(rec, now, None, [])
    item["flags"] = ["found"]  # labelled: it is a camera
    set_model(item, model, "manual")
    item["description_checked"] = True
    apply_page(item, page, now)
    return item


def needs_enrich(item):
    """A found camera added with an id-estimated age and no item page yet."""
    return "found" in item["flags"] and (item.get("age_source") == "id" or not item.get("description_checked"))


def recheck_minutes(item, now):
    """Daily check, or every 5 days for cameras over a month old on Vinted."""
    listed = item.get("vinted_listed_est")
    if listed and clock.minutes_between(f"{listed} 00:00", now) > OLD_ON_VINTED_DAYS * 1440:
        return OLD_RECHECK_MIN
    return 1440


def wants_description(item):
    """Fetch the description early: for new list cameras (manuals and brochures hide there,
    and it fills the kit), and for rest items whose title names only a list brand."""
    if item.get("description_checked") or item.get("description"):
        return False
    flags = set(item["flags"])
    if "preexisting" in flags or "found" in flags or SIGNAL_FLAGS & flags:  # found: enrichment
        return False
    if item["group"] == "list":
        return True
    if item["model"] is None and (report.current_price(item) or CHEAP_PRICE + 1) <= CHEAP_PRICE:
        return True  # cheap listings are titled carelessly ('Kamera alt'): the model may be in the text
    return item["model"] is None and (
        item["brand"] in LIST_BRANDS or bool(set(models.brands_in(item.get("vinted_brand") or "")) & LIST_BRANDS))


def check_priority(item, now, vanished):
    """Priority for opening the item page this tick, or None if not due.

    A sighting in the fresh search counts as a check, but the page is opened at least every 5 days."""
    since = clock.minutes_between(max(item["last_checked_at"], item.get("fresh_seen_at") or ""), now)
    if clock.minutes_between(item["last_checked_at"], now) >= PAGE_RECHECK_MIN and item["group"] == "list":
        since = max(since, PAGE_RECHECK_MIN)
    if item.get("needs_check") and item["group"] == "list" and "found" not in item["flags"]:
        return P_LIST_DUE
    if "found" in item["flags"]:  # old listing: its model's search results show it is still there
        return P_FOUND if item.get("needs_check") or since >= recheck_minutes(item, now) else None
    age = clock.minutes_between(item["first_seen"], now)
    preexisting = "preexisting" in item["flags"]
    if item["group"] == "rest":
        if vanished:
            return P_REST_VANISHED
        return P_REST_DUE if age < REST_TRACK_MIN and not preexisting else None
    if vanished:
        return P_LIST_VANISHED
    if preexisting or age >= 1440:
        return P_LIST_DAILY if since >= recheck_minutes(item, now) else None
    if age < 180:
        return P_LIST_DUE
    return P_LIST_DUE if since >= 240 else None


def _can_request(client):
    """Within the request and time budget of this tick."""
    return client.requests_made < MAX_REQUESTS and getattr(client, "has_time", lambda: True)()


def fresh_search(state, client, active, closed, now, stats, changed, quick=False, limit=FRESH_PER_CHECK):
    """Newest listings of the 'Модели' models in all categories: each model about once an hour
    (the longest-waiting first, FRESH_PER_CHECK per tick or quick check), as many pages as its
    active cameras need; the key models' page 1 in every tick as well.

    - A list camera the tracker does not know, listed within a day (its id between the catalog's
      top a day ago and now) but not in the catalog, was put in another category: it is tracked,
      listed after this model's previous query (or 'found' on the first).
    - A tracked camera in the results is active: a sighting counts as a check (its page is then
      opened every 5 days only). One that was seen in its model's results before and is missing
      now, although its id is within the pages read, may be sold: its page is opened next tick.
    """
    st = state.setdefault("fresh_search", {"last_run": {}})
    names = state.get("models_sheet") or [m for _, m in MODEL_SWEEP.queries]
    last_run = st["last_run"]
    due = sorted((n for n in names if not last_run.get(n) or clock.minutes_between(last_run[n], now) >= FRESH_EVERY_MIN - 5),
                 key=lambda n: last_run.get(n) or "")[:limit]
    live = Counter(i["model"] for i in active.values() if i.get("group") == "list" and i["status"] == "active")
    queries = [(n, min(FRESH_PRIORITY_MAX_PAGES, 1 + live[n] // FRESH_PRIORITY_PAGE_ITEMS) if n in FRESH_PRIORITY
                else min(FRESH_MAX_PAGES, 1 + live[n] // FRESH_PAGE_ITEMS)) for n in due]
    if not quick:
        queries += [(n, 1) for n in FRESH_PRIORITY if n in names and n not in due]
    history = state.get("max_seen_history") or []
    # The catalog's top a day ago: the oldest of the history, or of the new cards of the last day.
    day_ago = clock.stamp(clock.parse(now) - timedelta(hours=FRESH_HOURS))
    new_ids = [i["id"] for i in active.values()
               if i["first_seen"] >= day_ago and not {"found", "bumped", "preexisting"} & set(i["flags"])]
    floor = min(new_ids + [h[1] for h in history[:1]], default=0)
    top = state.get("max_seen_id", 0)
    skipped = set(state.get(MODEL_SWEEP.key, {}).get("skipped", []))
    for model, pages in queries:
        results, last = [], []
        for page in range(1, pages + 1):
            if not _can_request(client):
                return
            last = client.fresh_page(model.lower(), page)
            stats["fresh_pages"] += 1
            results += last
            if len(last) < 96:
                break
        previous = last_run.get(model)
        ids = {rec["id"] for rec in results}
        for rec in results:
            rec_id = rec["id"]
            if rec_id in active:
                item = active[rec_id]
                mark_seen(item, rec, now, checked=False)
                item["fresh_seen_at"] = now
                if item.get("model") == model:
                    item["fresh_query"] = model
                changed.add(rec_id)
            # Newer than the catalog's top: the next catalog read takes it (if it is a film camera).
            elif rec_id in closed or rec_id in skipped or not floor <= rec_id <= top:
                continue
            else:
                # Listed after this model's previous query only if its id is above the catalog's top
                # then; older ones were missed (e.g. under the day floor): listing time unknown.
                after_previous = previous and rec_id > _top_at(history, previous)
                item = new_item(rec, now, previous if after_previous else None, [] if after_previous else ["found"])
                if item["group"] == "list":
                    item["fresh_seen_at"] = now
                    if item.get("model") == model:
                        item["fresh_query"] = model
                    active[rec_id] = item
                    changed.add(rec_id)
                    stats["fresh_found"] += 1
        # Below the last page's tail the listings go on: absence there says nothing.
        tail = [r["id"] for r in last[-BOUNDARY_TAIL:] if not r["promoted"]]
        boundary = max(tail) if len(last) == 96 and tail else 0
        for item in active.values():
            if (item.get("fresh_query") == model and item["id"] not in ids and item["id"] >= boundary
                    and item["status"] == "active" and not item.get("needs_check")):
                item["needs_check"] = True
                changed.add(item["id"])
                stats["fresh_missing"] += 1
        if (model, pages) in queries[:len(due)]:
            last_run[model] = now


def _top_at(history, stamp):
    """The catalog's top id at a moment (the last history entry not after it), or 0."""
    tops = [h[1] for h in history if h[0] <= stamp]
    return tops[-1] if tops else 0


def sweep_state(state, sweep, now):
    st = state.setdefault(sweep.key, {"query": 0, "page": 1, "done_on": None, "pending": {}, "skipped": []})
    st.setdefault("seen", [])
    st.setdefault("query_started", now)
    return st


def queue_priority_models(state, now):
    """Put newly added models at the head of the model search, once each."""
    st = sweep_state(state, MODEL_SWEEP, now)
    done = st.setdefault("prioritized", [])
    for model in models.PRIORITY_SEARCH:
        if model in models.MODEL_INFO and model not in done:
            st.setdefault("priority", []).append([model.lower(), model])
            done.append(model)


def search_sweep(sweep, state, client, active, closed, now, today, stats, changed, estimate=None):
    """Advance one search pass by a slice: candidate age checks, then result pages.

    A list camera from the results that is not tracked yet becomes a candidate;
    its item page decides: active and at most half a year on Vinted -> tracked
    with the 'found' flag, otherwise remembered and skipped. With `presence`,
    a tracked 'found' camera missing from its model's results is checked next.
    """
    st = sweep_state(state, sweep, now)
    skipped = set(st["skipped"])

    for key in list(st["pending"])[:sweep.checks_per_tick]:
        if not _can_request(client):
            return
        rec = st["pending"][key]
        if rec["id"] in active or rec["id"] in closed:
            del st["pending"][key]
            continue
        page = client.item_page(rec["id"])
        del st["pending"][key]
        stats["checks"] += 1
        age = age_days(page["uploaded_ago"])
        item = new_item(rec, now, None, ["found"])
        if page["status"] != "active" or item["group"] != "list" or (age is not None and age > FOUND_MAX_AGE_DAYS):
            st["skipped"].append(rec["id"])
            stats["search_skipped"] += 1
            continue
        item["age_days_at_discovery"] = age
        apply_page(item, page, now)
        active[rec["id"]] = item
        changed.add(rec["id"])
        stats["found"] += 1

    if sweep.daily and st["done_on"] == today:
        return
    pages = sweep.fill_pages_per_tick if sweep.fill_pages_per_tick and not st.get("passes") else sweep.pages_per_tick
    for _ in range(pages):
        if not _can_request(client):
            return
        priority = st.get("priority") or []
        if priority and (st.get("prio_cursor") or st["page"] == 1):  # never split a regular query
            query, model = priority[0]
            cur = st.setdefault("prio_cursor", {"page": 1, "seen": [], "query_started": now})
        else:
            query, model = sweep.queries[st["query"] % len(sweep.queries)]
            cur = st
        if cur["page"] == 1:
            cur["query_started"], cur["seen"] = now, []
        results = client.search_page(query, cur["page"], sweep.max_price)
        stats["search_pages"] += 1
        hits = 0
        for rec in results:
            cls = models.classify(rec["title"], vinted_brand=rec["brand"])
            if not cls["model"] or SIGNAL_FLAGS & set(cls["flags"]):
                continue
            hits += model is None or cls["model"] == model
            rec_id = rec["id"]
            if rec_id in active:
                mark_seen(active[rec_id], rec, now, checked=False)
                changed.add(rec_id)
                cur["seen"].append(rec_id)
            elif rec_id in closed or rec_id in skipped or str(rec_id) in st["pending"]:
                continue
            elif state.get("max_seen_id") and rec_id > state["max_seen_id"]:
                continue  # newer than the catalog pages: a new listing, the next catalog read takes it
            elif rec_id < FOUND_MIN_ID:
                st["skipped"].append(rec_id)
                skipped.add(rec_id)
                stats["search_skipped"] += 1
            elif estimate is not None:
                # Age from the id: no item page now; the card is enriched later.
                stats["search_candidates"] += 1
                listed = estimate(rec_id)
                age = (date.fromisoformat(today) - listed).days
                if age > FOUND_MAX_AGE_DAYS:
                    st["skipped"].append(rec_id)
                    skipped.add(rec_id)
                    stats["search_skipped"] += 1
                    continue
                item = new_item(rec, now, None, ["found"])
                item.update(age_source="id", vinted_listed_est=listed.isoformat(), age_days_at_discovery=age)
                active[rec_id] = item
                changed.add(rec_id)
                cur["seen"].append(rec_id)
                stats["found"] += 1
            else:
                st["pending"][str(rec_id)] = rec
                stats["search_candidates"] += 1
        if len(results) == 96 and cur["page"] < sweep.max_pages and hits:
            cur["page"] += 1
            continue
        if sweep.presence:
            if model:
                belongs = lambda i, m=model: i["model"] == m
            else:  # brand query with a price cap: cheap cameras of that brand
                brands = set(models.brands_in(query))
                belongs = lambda i, b=brands, p=sweep.max_price: (
                    i.get("brand") in b and (i["price_history"][-1]["price"] or 0) <= p)
            _mark_missing(belongs, set(cur["seen"]), cur["query_started"], active, stats, changed)
        if cur is not st:  # priority query done
            st["priority"] = priority[1:]
            del st["prio_cursor"]
            continue
        st["query"], st["page"] = st["query"] + 1, 1
        if st["query"] >= len(sweep.queries):
            st["query"], st["done_on"] = 0, today
            st["passes"] = st.get("passes", 0) + 1
            if sweep.daily:
                return


def _mark_missing(belongs, seen, since, active, stats, changed):
    """Tracked 'found' cameras that belong to a finished query but are absent from its
    results (and not seen anywhere since it started) may be sold: open their page next."""
    for item in active.values():
        if ("found" in item["flags"] and belongs(item) and item["id"] not in seen
                and item["last_seen_active"] < since and not item.get("needs_check")):
            item["needs_check"] = True
            changed.add(item["id"])
            stats["found_missing"] += 1


# ---------------------------------------------------------------- tick

def run_tick(store, client, labels=None, now=None, quick=False):
    """Process one tick against the data store (quick: page 1, new and vanished fresh items
    only). Returns a result dict."""
    started = time.monotonic()
    now = now or clock.stamp()
    today = now[:10]
    state = store.load_state()
    first_run = "first_run_at" not in state
    quick = quick and not first_run
    first_of_day = not first_run and state.get("last_tick_at", "")[:10] != today
    rest_enabled = state.get("rest_disabled_on") != today
    stats, errors = Counter(), []

    active = store.load_active()
    closed = store.load_closed()
    changed = set()

    # Manual labels win over everything and are never overwritten.
    unknown_labelled = []
    for item_id, text in (labels or {}).items():
        item = active.get(item_id) or closed.get(item_id)
        model = models.canonical_model(text) or text
        if item is None:
            if model in models.MODEL_INFO:
                unknown_labelled.append((item_id, model))
            continue
        if item.get("model") != model or item.get("model_source") != "manual":
            item["flags"] = [f for f in item["flags"] if f not in SIGNAL_FLAGS]  # labelled: it is a camera
            set_model(item, model, "manual")
            if item.get("closed_at"):
                item["group"] = group_of(item)
            changed.add(item_id)

    # The model dictionary changed: re-classify all items (manual labels stay);
    # closed ones move between 'Список' and the rest too.
    if state.get("models_version") != models.VERSION:
        stats["models_version_changed"] = 1
        for item in [*active.values(), *closed.values()]:
            if item.get("model_source") == "manual":
                continue
            cls = models.classify(item["title"], item.get("description"), item.get("vinted_brand"))
            signal = sorted(SIGNAL_FLAGS & set(cls["flags"]))
            flags = [f for f in item["flags"] if f not in SIGNAL_FLAGS] + signal
            before = (item.get("model"), list(item["flags"]), item.get("group"))
            if cls["model"] != item.get("model") or flags != item["flags"]:
                item["flags"] = flags
                set_model(item, cls["model"], cls["model_source"])
            # Group rules changed too (accessories left 'Список'): apply them to old cards.
            item["group"] = group_of(item)
            if (item.get("model"), item["flags"], item["group"]) != before:
                changed.add(item["id"])
                stats["reclassified"] += 1
        state["models_version"] = models.VERSION
        # The rules of what is worth keeping may have changed too: drop the junk, rewrite 'Остальные'.
        for item in [i for i in [*active.values(), *closed.values()] if is_junk(i)]:
            active.pop(item["id"], None)
            closed.pop(item["id"], None)
            changed.discard(item["id"])
            store.discard(item["id"])
            stats["junk_dropped"] += 1
        state["rest_rewrite"] = True

    # 'Unsold in 3 h' is a rule of the rest group. A list camera closed that way
    # (it became a list camera later, e.g. after a dictionary update) is reopened
    # and checked: it is then tracked like any list camera, up to 30 days.
    for item_id, item in list(closed.items()):
        if item.get("group") == "list" and item.get("status") == "unsold_3h":
            item.update(status="active", closed_at=None, needs_check=True)
            active[item_id] = closed.pop(item_id)
            changed.add(item_id)
            stats["reopened"] += 1

    # ---- catalog
    full_scan = not quick and (
        first_run or clock.minutes_between(state.get("last_full_scan_at") or "2000-01-01 00:00", now) >= FULL_SCAN_EVERY_MIN)
    seen, last_page, pages_read = {}, [], 0
    for page in range(1, (MAX_PAGES if full_scan else QUICK_PAGES if quick else TICK_PAGES) + 1):
        try:
            items = client.catalog_page(page)
        except VintedError as exc:
            errors.append(f"catalog page {page}: {exc}")
            if isinstance(exc, BlockedError):
                rest_enabled = False
            if page <= TICK_PAGES:
                return _finish(store, state, now, started, client, stats, errors, full_scan, pages_read,
                               rest_enabled, today, active, closed, changed, fatal=True, quick=quick)
            full_scan = False  # partial: do not reset the 4-hour timer
            break
        if not items:
            break
        last_page = items
        pages_read += 1
        for rec in items:
            seen.setdefault(rec["id"], rec)
    tail = [r["id"] for r in last_page[-BOUNDARY_TAIL:] if not r["promoted"]] or [r["id"] for r in last_page]
    boundary = max(tail)
    # List cameras listed as instant cameras, other cameras or spare parts (Polaroids, parts and
    # the like stay out): seen like catalog items.
    misplaced, parts_ids = set(), set()
    extra_pages = [(category, page) for category in EXTRA_CATEGORY_IDS
                   for page in range(1, (EXTRA_FULL_PAGES if full_scan else 1) + 1)]
    for category, page in extra_pages:
        try:
            for rec in client.catalog_page(page, category):
                cls = models.classify(rec["title"], vinted_brand=rec["brand"])
                if category == PARTS_CATEGORY_ID and not models.names_camera(rec["title"]):
                    continue  # 'Manivelle rembobinage Olympus OM10'
                if cls["in_list"] and not SIGNAL_FLAGS & set(cls["flags"]) and rec["id"] not in seen:
                    seen[rec["id"]] = rec
                    misplaced.add(rec["id"])
                    if category == PARTS_CATEGORY_ID:
                        parts_ids.add(rec["id"])
        except VintedError:
            stats["check_errors"] += 1

    # ---- seen items: update tracked, create new
    max_seen = state.get("max_seen_id", 0)
    extra = ["preexisting"] if first_run else (["night"] if first_of_day else [])
    listed_after = None if first_run else state.get("last_tick_at")
    # A cheap one (outside the parts) would have shown in the last cheap check: listed after it.
    cheap_after = listed_after and max(listed_after, state.get("last_cheap_at") or "")
    for rec_id, rec in seen.items():
        if rec_id in active:
            mark_seen(active[rec_id], rec, now)
            changed.add(rec_id)
        elif rec_id > max_seen:
            cheap = (rec["price"] or CHEAP_PRICE + 1) <= CHEAP_PRICE and rec_id not in parts_ids
            item = new_item(rec, now, cheap_after if cheap else listed_after, extra)
            if worth_tracking(item):
                active[rec_id] = item
                changed.add(rec_id)
                stats[f"new_{item['group']}"] += 1
            elif is_junk(item):
                stats["junk_skipped"] += 1
        elif rec_id in misplaced and rec_id not in closed:
            # An older list camera under 'Sofortbildkameras', never seen: listing time unknown.
            if not first_run:
                active[rec_id] = new_item(rec, now, None, ["found"])
                changed.add(rec_id)
                stats["found"] += 1
        elif rec_id not in closed:
            # An old listing pushed back to the top. List cameras are tracked
            # from the bump on: it happened between the previous tick and now.
            item = new_item(rec, now, listed_after, ["bumped"] + (["night"] if first_of_day else []))
            if is_junk(item):
                continue  # kept out of the data, seen again on the next pages
            stats["bumped"] += 1
            if item["group"] == "list" and not first_run:
                active[rec_id] = item
                changed.add(rec_id)
                stats["bumped_list"] += 1
    state["max_seen_id"] = max([max_seen, *seen])
    # The catalog's top id over the last day: the floor of 'fresh' for the fresh search.
    since = clock.stamp(clock.parse(now) - timedelta(hours=FRESH_HOURS))
    history = [h for h in state.get("max_seen_history", []) if h[0] >= since] + [[now, state["max_seen_id"]]]
    state["max_seen_history"] = history

    # ---- item page checks, in priority order within the request budget
    queue = []
    for item in active.values():
        if item["id"] in seen and item["status"] == "active":
            if wants_description(item):
                queue.append((P_DESCRIPTION, item["first_seen"], item["id"]))
            continue
        priority = check_priority(item, now, vanished=item["id"] >= boundary and item["id"] not in seen)
        if priority is not None:
            queue.append((priority, item["last_checked_at"], item["id"]))
        elif needs_enrich(item):
            cheap = (report.current_price(item) or 0) <= SEARCH_MAX_PRICE_CHEAP
            queue.append((P_ENRICH, ("0" if cheap else "1") + item["first_seen"], item["id"]))
        elif wants_description(item):
            queue.append((P_DESCRIPTION, item["first_seen"], item["id"]))
    queue.sort()
    if quick:  # new cameras' descriptions and fresh list cameras gone from page 1 (fast sales)
        queue = [q for q in queue if q[0] in (P_LIST_VANISHED, P_DESCRIPTION)]
    daily = descriptions = found_checks = enriched = 0
    enrich_cap = ENRICH_PER_TICK_AFTER_FILL if state.get(MODEL_SWEEP.key, {}).get("passes") else ENRICH_PER_TICK
    promoted = []  # rest items that became list cameras through their description
    for priority, _, item_id in queue:
        item = active[item_id]
        if priority == P_LIST_DAILY:
            daily += 1
            if daily > DAILY_CHECKS_PER_TICK:
                stats["deferred"] += 1
                continue
        if priority == P_FOUND:
            found_checks += 1
            if found_checks > FOUND_CHECKS_PER_TICK:
                stats["deferred"] += 1
                continue
        if priority == P_DESCRIPTION:
            descriptions += 1
            if descriptions > DESCRIPTION_CHECKS_PER_TICK:
                stats["deferred"] += 1
                continue
        if priority == P_ENRICH:
            enriched += 1
            if enriched > enrich_cap:
                stats["deferred"] += 1
                continue
        if priority >= P_REST_VANISHED and not rest_enabled:
            stats["deferred"] += 1
            continue
        if not _can_request(client):
            stats["deferred"] += 1
            continue
        try:
            page = client.item_page(item_id)
        except BlockedError as exc:
            errors.append(f"item page: {exc}")
            rest_enabled = False
            break
        except VintedError:
            stats["check_errors"] += 1
            continue
        stats["checks"] += 1
        changed.add(item_id)
        if priority in (P_DESCRIPTION, P_ENRICH):
            item["description_checked"] = True
            stats["descriptions" if priority == P_DESCRIPTION else "enriched"] += 1
        status = apply_page(item, page, now)
        if item["group"] == "list" and status in ("sold", "deleted", "reserved", "hidden"):
            stats["list_status_changed"] += 1
        if status == "sold":
            stats[f"sold_{item['group']}"] += 1
        elif status in ("deleted", "reserved", "hidden", "unknown"):
            stats[status] += 1
        if priority == P_DESCRIPTION and item["description"] and item["model"] is None:
            cls = models.classify(item["title"], item["description"], item.get("vinted_brand"))
            if cls["model"]:
                set_model(item, cls["model"], "description")
                stats["description_to_list"] += 1
                promoted.append(item_id)

    # ---- newest listings of the 'Модели' models in all categories (cameras listed elsewhere)
    if rest_enabled and not first_run and not full_scan:
        try:
            fresh_search(state, client, active, closed, now, stats, changed, quick)
        except BlockedError as exc:
            errors.append(f"fresh search: {exc}")
            rest_enabled = False
        except VintedError:
            stats["check_errors"] += 1

    # Found cameras that turned out older than half a year: not tracked at all.
    for item_id in [i for i, it in active.items() if it.get("too_old")]:
        del active[item_id]
        changed.discard(item_id)
        store.discard(item_id)
        state.setdefault(MODEL_SWEEP.key, {}).setdefault("skipped", []).append(item_id)
        stats["too_old"] += 1
    # A description can show a compact or an accessory later: out of the data too.
    for item_id in [i for i, it in active.items() if is_junk(it)]:
        del active[item_id]
        changed.discard(item_id)
        store.discard(item_id)
        stats["junk_dropped"] += 1

    # ---- cameras the user labelled that the tracker never saw (the model only in the photos,
    # or never on the scanned pages): opened once and tracked like found ones
    tries = state.setdefault("labelled_tries", {})
    pending = [] if quick else [(i, m) for i, m in unknown_labelled if tries.get(str(i), 0) < LABELLED_MAX_TRIES]
    for item_id, model in pending[:LABELLED_PER_TICK]:
        if not rest_enabled or not _can_request(client):
            break
        try:
            page = client.item_page(item_id)
        except BlockedError as exc:
            errors.append(f"item page: {exc}")
            rest_enabled = False
            break
        except VintedError:
            page = {"status": "unknown"}
        stats["checks"] += 1
        if page["status"] == "unknown" or not page.get("title"):
            tries[str(item_id)] = tries.get(str(item_id), 0) + 1
            stats["unknown"] += 1
            continue
        tries.pop(str(item_id), None)
        active[item_id] = add_labelled(item_id, model, page, now)
        changed.add(item_id)
        stats["labelled"] += 1

    # ---- searches for older list cameras (lowest priority; skipped on full-scan ticks to avoid peaks)
    if rest_enabled and not first_run and not full_scan and not quick:
        estimate = ageest.build_estimator([*active.values(), *closed.values()], state.get("max_seen_id"),
                                          date.fromisoformat(today))
        queue_priority_models(state, now)
        for sweep in SWEEPS:
            try:
                search_sweep(sweep, state, client, active, closed, now, today, stats, changed, estimate)
            except BlockedError as exc:
                errors.append(f"search: {exc}")
                rest_enabled = False
                break
            except VintedError:
                stats["check_errors"] += 1

    # ---- close items whose tracking period is over
    for item in active.values():
        if item.get("closed_at"):
            continue
        age = clock.minutes_between(item["first_seen"], now)
        if item["group"] == "rest" and age >= REST_TRACK_MIN:
            close(item, "unsold_3h", now)
        elif item["group"] == "list" and age >= LIST_TRACK_MIN:
            close(item, "unsold_30d", now)
        else:
            continue
        stats["closed_3h" if item["status"] == "unsold_3h" else "closed_30d"] += 1
        changed.add(item["id"])

    if full_scan:
        state["last_full_scan_at"] = now
    state["last_tick_at"] = now
    state.setdefault("first_run_at", now)
    return _finish(store, state, now, started, client, stats, errors, full_scan, pages_read,
                   rest_enabled, today, active, closed, changed, fatal=False,
                   daily=not quick and bool(first_run or first_of_day or state.pop("rest_rewrite", False)), promoted=promoted, quick=quick)


def run_cheap(store, client, labels=None, now=None):
    """Cheap check between ticks: page 1 of the newest listings at 20 EUR or less (Filmkameras,
    Sofortbildkameras, Andere Kameras). New ones are carded and their descriptions read at once,
    so a cheap list camera reaches 'До 20 €' (and the letter) within minutes. Nothing else: a
    price-filtered page says nothing about vanished items, and the catalog's top id and tick
    time stay as they are (the next catalog read still judges the other listings)."""
    started = time.monotonic()
    now = now or clock.stamp()
    state = store.load_state()
    if "first_run_at" not in state:
        return run_tick(store, client, labels, now, quick=True)
    today = now[:10]
    active, closed = store.load_active(), store.load_closed()
    changed, stats, errors, promoted = set(), Counter(), [], []
    try:
        recs = client.cheap_page(CHEAP_PRICE)
    except VintedError as exc:
        errors.append(f"cheap page: {exc}")
        return _finish(store, state, now, started, client, stats, errors, False, 0, True, today,
                       active, closed, changed, fatal=True, quick=True, cheap=True)
    max_seen = state.get("max_seen_id", 0)
    listed_after = max(state.get("last_tick_at") or "", state.get("last_cheap_at") or "") or None
    fresh = []
    for rec in recs:
        rec_id = rec["id"]
        if rec_id in active:
            mark_seen(active[rec_id], rec, now)
            changed.add(rec_id)
        elif rec_id in closed:
            continue
        elif rec_id > max_seen:
            item = new_item(rec, now, listed_after, [])
            if worth_tracking(item):
                active[rec_id] = item
                changed.add(rec_id)
                stats[f"new_{item['group']}"] += 1
                fresh.append(item)
        else:
            # Older and never seen (in another category, or cheaper now): listing time unknown.
            item = new_item(rec, now, None, ["found"])
            if item["group"] == "list":
                active[rec_id] = item
                changed.add(rec_id)
                stats["found"] += 1
                fresh.append(item)
    for item in fresh:
        if not wants_description(item) or not _can_request(client):
            continue
        try:
            page = client.item_page(item["id"])
        except BlockedError as exc:
            errors.append(f"item page: {exc}")
            break
        except VintedError:
            stats["check_errors"] += 1
            continue
        stats["checks"] += 1
        stats["descriptions"] += 1
        item["description_checked"] = True
        apply_page(item, page, now)
        if item["description"] and item["model"] is None:
            cls = models.classify(item["title"], item["description"], item.get("vinted_brand"))
            if cls["model"]:
                set_model(item, cls["model"], "description")
                stats["description_to_list"] += 1
                promoted.append(item["id"])
    try:
        fresh_search(state, client, active, closed, now, stats, changed, quick=True, limit=FRESH_PER_CHEAP)
    except BlockedError as exc:
        errors.append(f"fresh search: {exc}")
    except VintedError:
        stats["check_errors"] += 1
    state["last_cheap_at"] = now
    return _finish(store, state, now, started, client, stats, errors, False, 1, True, today,
                   active, closed, changed, fatal=False, quick=True, promoted=promoted, cheap=True)


def _camera_label(item):
    """'Canon AE-1 — 120 €' (+ how it came in) for the 'Запуски' comment."""
    flags = set(item.get("flags") or [])
    origin = (" (разметка)" if item.get("model_source") == "manual" and "found" in flags
              else " (найдено)" if "found" in flags else " (поднято)" if "bumped" in flags else "")
    price = report.current_price(item)
    price_text = f" — {report._price_text(price)} €" if price is not None else ""
    # The id finds the row in 'Список' (Ctrl+F); the sheet is private, logs never print it.
    return f"{item.get('model') or (item.get('title') or '')[:40]}{price_text}{origin}, id {item['id']}"


def _finish(store, state, now, started, client, stats, errors, full_scan, pages, rest_enabled, today,
            active, closed, changed, fatal, daily=False, promoted=(), quick=False, cheap=False):
    if not rest_enabled:
        state["rest_disabled_on"] = today
    for item_id in changed:
        item = active.get(item_id) or closed.get(item_id)
        store.save(item)
        if item.get("closed_at") and item_id in active:
            closed[item_id] = active.pop(item_id)
    added = [i for i in active.values() if i.get("group") == "list" and (i.get("first_seen") == now or i["id"] in promoted)]
    sold = [i for i in closed.values()
            if i.get("group") == "list" and i.get("status") == "sold" and i.get("sold_detected_at") == now]
    run = {
        "at": now, "quick": quick, "cheap": cheap, "full_scan": full_scan, "pages": pages, "requests": client.requests_made,
        "mb": round(client.bytes_received / 1e6, 1), "seconds": round(time.monotonic() - started),
        "new_list": stats["new_list"], "new_rest": stats["new_rest"], "bumped": stats["bumped"],
        "bumped_list": stats["bumped_list"],
        "checks": stats["checks"], "sold_list": stats["sold_list"], "sold_rest": stats["sold_rest"],
        "deleted": stats["deleted"], "reserved_hidden": stats["reserved"] + stats["hidden"],
        "unknown": stats["unknown"], "closed_3h": stats["closed_3h"], "closed_30d": stats["closed_30d"],
        "descriptions": stats["descriptions"], "description_to_list": stats["description_to_list"],
        "deferred": stats["deferred"], "check_errors": stats["check_errors"],
        "reclassified": stats["reclassified"], "reopened": stats["reopened"],
        "search_pages": stats["search_pages"], "search_candidates": stats["search_candidates"],
        "found": stats["found"], "search_skipped": stats["search_skipped"], "found_missing": stats["found_missing"],
        "enriched": stats["enriched"], "too_old": stats["too_old"], "labelled": stats["labelled"],
        "junk_skipped": stats["junk_skipped"], "junk_dropped": stats["junk_dropped"],
        "fresh_pages": stats["fresh_pages"], "fresh_found": stats["fresh_found"], "fresh_missing": stats["fresh_missing"],
        "rest_enabled": rest_enabled, "errors": [env.redact(e) for e in errors],
        # Names stay in the private data repo and sheet; log_line() never prints them.
        "added": [_camera_label(i) for i in added], "sold_names": [_camera_label(i) for i in sold],
        "list_changed": bool(added or sold or stats["list_status_changed"]),
    }
    # Quick and cheap checks write a 'Запуски' row only when 'Список' changed: the next tick's
    # row says how many ran in between.
    between = state.setdefault("checks_since_tick", {"quick": 0, "cheap": 0})
    if cheap or quick:
        between["cheap" if cheap else "quick"] += 1
    elif not fatal:
        run["between"] = dict(between)
        state["checks_since_tick"] = {"quick": 0, "cheap": 0}
    store.save_state(state)
    store.append_run(run)
    all_items = list(active.values()) + list(closed.values())
    summary = report.summarize(all_items, now)
    if daily:
        store.write_exports(all_items, summary, report.readme(summary))
    return {"run": run, "fatal": fatal, "daily": daily, "items": all_items, "summary": summary,
            "models_updated": bool(stats["models_version_changed"])}


def log_line(run):
    kind = "cheap " if run.get("cheap") else "quick " if run.get("quick") else ""
    return (f"{kind}tick {run['at'][11:]} | pages {run['pages']}"
            f"{' (full)' if run['full_scan'] else ''}"
            f" | requests {run['requests']} ({run['mb']} MB, {run['seconds']} s)"
            f" | new: list {run['new_list']}, rest {run['new_rest']}"
            f" | bumped {run['bumped']} (list tracked {run.get('bumped_list', 0)})"
            f" | checks {run['checks']}: sold list {run['sold_list']}, rest {run['sold_rest']},"
            f" deleted {run['deleted']}, reserved/hidden {run['reserved_hidden']}, unknown {run['unknown']}"
            f" | closed 3h {run['closed_3h']}, 30d {run['closed_30d']}"
            f" | descriptions {run['descriptions']} (-> list {run['description_to_list']})"
            f" | deferred {run['deferred']}, check errors {run['check_errors']}"
            f"{' | reclassified ' + str(run['reclassified']) if run.get('reclassified') else ''}"
            f"{' | reopened ' + str(run['reopened']) if run.get('reopened') else ''}"
            f" | search: pages {run.get('search_pages', 0)}, candidates {run.get('search_candidates', 0)},"
            f" found {run.get('found', 0)}, too old/gone {run.get('search_skipped', 0)},"
            f" missing from search {run.get('found_missing', 0)}"
            f" | enriched {run.get('enriched', 0)}, too old {run.get('too_old', 0)}"
            f" | junk skipped {run.get('junk_skipped', 0)}, dropped {run.get('junk_dropped', 0)}"
            f"{' | from labels ' + str(run['labelled']) if run.get('labelled') else ''}"
            f" | fresh search: pages {run.get('fresh_pages', 0)}, found {run.get('fresh_found', 0)},"
            f" missing {run.get('fresh_missing', 0)}"
            f"{'' if run['rest_enabled'] else ' | rest disabled today'}"
            f" | errors: {'; '.join(run['errors']) or 'none'}")


def runs_row(run, cheap_added=()):
    """One 'Запуски' row; cheap_added: cameras that entered 'До 20 €' in this tick."""
    kind = "да" if run["full_scan"] else "до 20 €" if run.get("cheap") else "быстрая" if run.get("quick") else ""
    return [run["at"], len(cheap_added), runs_comment(run, cheap=[_camera_label(i) for i in cheap_added]),
            kind, run["pages"], run["requests"], run["mb"], run["seconds"],
            run["new_list"], run["new_rest"], run["bumped"], run["checks"], run["sold_list"], run["sold_rest"],
            run["deleted"], run["reserved_hidden"], run["closed_3h"], run["closed_30d"], run["descriptions"],
            run["description_to_list"], run["deferred"], "; ".join(run["errors"]), between_text(run)]


def between_text(run):
    """'быстрых 2, до 20 € 3' for a tick's row; empty for the checks' own rows."""
    between = run.get("between")
    return f"быстрых {between['quick']}, до 20 € {between['cheap']}" if between else ""


def runs_comment(run, limit=40, cheap=()):
    """'Добавлены (3): Canon AE-1 — 120 €, … | Проданы (1): … | В «До 20 €» (1): Zenit E — 15 €'."""
    parts = []
    for title, names in (("Добавлены", run.get("added") or []), ("Проданы", run.get("sold_names") or []),
                         ("В «До 20 €»", list(cheap))):
        if names:
            more = f" … и ещё {len(names) - limit}" if len(names) > limit else ""
            parts.append(f"{title} ({len(names)}): " + ", ".join(names[:limit]) + more)
    return " | ".join(parts)


# ---------------------------------------------------------------- sheets and entry point

def write_sheets(writer, result, state_flags):
    """Write all sheets. Returns state keys to remember (runs header, offered models)."""
    from . import sheets

    updates = {}
    items = result["items"]
    offered = state_flags.get("models_offered")
    if offered is None:  # the sheet was filled before offers were tracked
        offered = sorted(models.MODEL_INFO)
        updates["models_offered"] = offered
    names, allowed = writer.sync_models(set(offered))
    sheet_models = sorted({models.canonical_model(n) or n for n in names} & set(models.MODEL_INFO))
    if sheet_models and sheet_models != state_flags.get("models_sheet"):
        updates["models_sheet"] = sheet_models  # the fresh search follows 'Модели' 
    if set(names) - set(offered):
        updates["models_offered"] = sorted(set(offered) | set(names))

    new_since = clock.stamp(clock.parse(result["run"]["at"]) - timedelta(hours=NEW_ROWS_HOURS))
    fresh_since = clock.stamp(clock.parse(result["run"]["at"]) - timedelta(hours=FRESH_ROWS_HOURS))
    writer.replace(sheets.LIST_SHEET, report.item_rows([i for i in items if i.get("group") == "list"],
                                                       new_since=new_since, fresh_since=fresh_since), links=True)
    candidates = report.cheap_cameras(items, sheets.CHEAP_MAX_PRICE)
    cheap = [i for i in candidates if i.get("model") and sheets.model_key(i["model"]) in allowed]
    print(f"sheets: cheap sheet {len(cheap)} of {len(candidates)} list cameras at <= 20 EUR"
          f" (the others have models missing from the models sheet)")
    # 'До 20 €' is mostly old cheap cameras found by search: mark what entered the sheet in 12 h.
    # The link right after 'Сохранений' (column H): the status column and the flag columns stay where they were.
    cheap_rows = report.item_rows(cheap, with_group=True, new_since=new_since, new_old_listings=True,
                                  fresh_since=fresh_since)
    writer.replace(sheets.CHEAP_SHEET, report.move_column(cheap_rows, "Ссылка", CHEAP_LINK_COLUMN), links=True)
    # Cameras that entered 'До 20 €' since the previous tick (none counted on the very first one).
    cheap_ids = sorted(i["id"] for i in cheap)
    previous = state_flags.get("cheap_ids")
    cheap_added = [] if previous is None else [i for i in cheap if i["id"] not in set(previous)]
    if cheap_ids != previous:
        updates["cheap_ids"] = cheap_ids
    writer.replace(sheets.FAST_SHEET, report.fast_rows(items), links=True)
    writer.replace(sheets.SALES_SHEET, report.sales_rows(items), links=True)
    writer.replace(sheets.CHECK_SHEET, report.check_rows(items), links=True)
    writer.replace(sheets.SUMMARY_SHEET, report.summary_rows(result["summary"]))
    writer.replace(sheets.TOP_SHEET, report.top_rows(items, result["run"]["at"]), links=True)
    writer.replace(sheets.ANALYTICS_SHEET, report.analytics_rows(items, result["run"]["at"]))
    if any(i.get("photo_label") for i in items):
        writer.replace(sheets.PHOTO_SHEET, report.photo_rows(items), links=True)
        try:  # cosmetic: room for the photos (rows added by the rewrite are short again)
            writer.set_row_height(sheets.PHOTO_SHEET, PHOTO_ROW_PX)
        except Exception as exc:
            print(f"sheets: photo rows not resized: {type(exc).__name__}")
    if not state_flags.get("runs_header_v5"):  # v5: 'Новых в «До 20 €»' and 'Комментарий' right after the time
        writer.ensure_runs_header()
        updates["runs_header_v5"] = True
    writer.append_run(runs_row(result["run"], cheap_added))
    if result["daily"]:
        writer.replace(sheets.REST_SHEET, report.item_rows([i for i in items if i.get("group") == "rest"]), links=True)
    colored = set(state_flags.get("status_colors") or [])
    todo = [t for t in (sheets.LIST_SHEET, sheets.REST_SHEET, sheets.CHEAP_SHEET, sheets.FAST_SHEET)
            if t not in colored and writer.has(t)]
    if todo:
        try:  # cosmetic: a failure must not fail the tick; retried next tick
            writer.color_active_status(todo, report.ITEM_HEADER.index("Статус"))
            updates["status_colors"] = sorted(colored | set(todo))
        except Exception as exc:
            print(f"sheets: status colours not applied: {type(exc).__name__}: {env.redact(exc)}")
    # Rows of new cameras: light blue 3 (12 h), light green 3 (3 h) above it,
    # both below the status rule.
    blue = set(state_flags.get("new_rows_colors") or [])
    if state_flags.get("new_rows_color"):  # earlier flag: only 'Список' had the rule
        blue.add(sheets.LIST_SHEET)
    yellow = set(state_flags.get("fresh_rows_colors") or [])
    green = set(updates.get("status_colors") or colored)
    n = len(report.ITEM_HEADER)
    columns = {sheets.LIST_SHEET: (n, n + 1), sheets.CHEAP_SHEET: (n + 1, n + 2)}  # 12 h flag, 3 h flag
    for title, (col_12h, col_3h) in columns.items():
        if not writer.has(title):
            continue
        index = 1 if title in green else 0
        try:
            if title not in blue:
                writer.color_new_rows(title, col_12h, col_3h + 1, index, sheets.LIGHT_BLUE_3)
                blue.add(title)
                updates["new_rows_colors"] = sorted(blue)
            if title not in yellow:
                writer.color_new_rows(title, col_3h, col_3h + 1, index, sheets.LIGHT_GREEN_3)
                yellow.add(title)
                updates["fresh_rows_colors"] = sorted(yellow)
        except Exception as exc:
            print(f"sheets: new-row colours not applied: {type(exc).__name__}: {env.redact(exc)}")
    # The 3-hour rule was light yellow 3 for a while: recolour it once.
    if not state_flags.get("fresh_rows_green"):
        try:
            if state_flags.get("fresh_rows_colors"):
                writer.recolor_rules(state_flags["fresh_rows_colors"], sheets.LIGHT_YELLOW_3, sheets.LIGHT_GREEN_3)
            updates["fresh_rows_green"] = True
        except Exception as exc:
            print(f"sheets: 3-hour colour not changed: {type(exc).__name__}: {env.redact(exc)}")
    return updates


def main():
    parser = argparse.ArgumentParser(description="One tracker tick.")
    parser.add_argument("--quick", action="store_true", help="quick check: catalog page 1, new and vanished items")
    parser.add_argument("--cheap", action="store_true", help="cheap check: newest listings at 20 EUR or less")
    parser.add_argument("--force", action="store_true", help="run outside the 07:00-00:00 Berlin window")
    parser.add_argument("--local", help="use a local folder as the data store (no git)")
    parser.add_argument("--no-sheets", action="store_true", help="skip Google Sheets")
    parser.add_argument("--max-requests", type=int, default=MAX_REQUESTS + 15)  # hard cap above the plan
    args = parser.parse_args()
    args.quick = args.quick or args.cheap  # a cheap check is handled like a quick one (sheet only if changed)

    if not args.force and env.now_berlin().hour < WINDOW_START_HOUR:
        print("outside the 07:00-00:00 Berlin window, nothing to do")
        return 0
    try:
        return _main(args)
    except Exception as exc:  # keep logs free of data: type, redacted message, code locations
        frames = traceback.extract_tb(exc.__traceback__)
        where = " <- ".join(f"{Path(f.filename).name}:{f.lineno}" for f in reversed(frames[-4:]))
        print(f"tick failed: {type(exc).__name__}: {env.redact(exc)} at {where}")
        return 1


CHEAP_LINK_COLUMN = 7  # 'До 20 €': the link in column H, right after G ('Сохранений')
PHOTO_TIME_BUDGET_S = 90   # photo labeling of new 'Остальные' per full tick (trial)
PHOTO_START_LIMIT_S = 9 * 60  # a tick that already ran this long skips it
PHOTO_ROW_PX = 110


def photo_step(store, result, started):
    """Trial mode: label new cards of 'Остальные' by photo and take the archive verdicts in.
    Only records 'photo_label'; a failure never fails the tick. Counts only in the log."""
    from . import photos

    if time.monotonic() - started > PHOTO_START_LIMIT_S or not photos.available(store.root):
        return
    try:
        state = store.load_state()
        archive = photos.apply_backfill(store.root, result["items"], state)
        store.save_state(state)
        fresh, stats = photos.run(store.root, result["items"], PHOTO_TIME_BUDGET_S)
        for item in archive + fresh:
            store.save(item)
        print(f"photos: labelled {stats['labelled']} (drop {stats['drop']}, list {stats['list']}, keep {stats['keep']},"
              f" gone {stats['gone']}), archive {len(archive)}, errors {stats['errors']}")
    except Exception as exc:
        print(f"photos failed: {type(exc).__name__}: {env.redact(exc)}")


def _main(args):
    from . import datarepo, sheets

    started = time.monotonic()
    writer, labels, code = None, {}, 0
    if not args.no_sheets and not args.quick:  # a quick check opens the sheet only if 'Список' changed
        try:
            writer = sheets.SheetWriter(sheets.open_spreadsheet())
            labels = writer.manual_labels()
        except Exception as exc:
            print(f"sheets unavailable: {type(exc).__name__}: {env.redact(exc)}")
            writer, code = None, 1
    client = VintedClient(max_requests=args.max_requests,
                          time_budget=QUICK_TIME_BUDGET_S if args.quick else TICK_TIME_BUDGET_S)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(args.local) if args.local else datarepo.clone(Path(tmp) / "data")
        store = DataStore(root)
        state_flags = store.load_state()
        result = run_cheap(store, client, labels) if args.cheap else run_tick(store, client, labels, quick=args.quick)
        print(log_line(result["run"]))
        if not (args.quick or args.cheap or result["fatal"]):
            photo_step(store, result, started)
        if not result["fatal"]:
            try:  # e-mail alerts: a failure must not fail the tick
                state = store.load_state()
                before = (state.get("mail_welcome"), len(state.get("notified") or []))
                mailed = notify.run(result["items"], state, result["run"]["at"])
                if (state.get("mail_welcome"), len(state.get("notified") or [])) != before:
                    store.save_state(state)  # sent: remember what, before the data commit
                if mailed:
                    print(f"notify: mailed {mailed} camera(s)")
            except Exception as exc:
                print(f"notify failed: {type(exc).__name__}: {env.redact(exc)}")
        if not args.local:
            kind = "cheap " if args.cheap else "quick " if args.quick else ""
            datarepo.commit_and_push(root, f"{kind}tick {result['run']['at']}")
        if args.quick and not args.no_sheets and result["run"]["list_changed"]:
            try:
                writer = sheets.SheetWriter(sheets.open_spreadsheet())
            except Exception as exc:
                print(f"sheets unavailable: {type(exc).__name__}: {env.redact(exc)}")
                code = 1
        if writer:
            try:
                try:
                    updates = write_sheets(writer, result, state_flags)
                except (requests.RequestException, gspread.exceptions.APIError) as exc:
                    # Google dropped the connection now and then: one more try.
                    print(f"sheets write retry after {type(exc).__name__}")
                    time.sleep(15)
                    updates = write_sheets(writer, result, state_flags)
                if updates:
                    state = store.load_state()
                    state.update(updates)
                    store.save_state(state)
                    if not args.local:
                        datarepo.commit_and_push(root, "sheets state")
            except Exception as exc:
                print(f"sheets write failed: {type(exc).__name__}: {env.redact(exc)}")
                code = 1
    if result["fatal"] and not args.quick:
        code = 1  # broken catalog: GitHub sends an e-mail (the next tick tells, not a quick check)
    return code


if __name__ == "__main__":
    sys.exit(main())
