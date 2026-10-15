"""One tracker tick: catalog -> item checks -> data repo -> Google Sheet.

Run:  python -m tracker.tick [--force] [--local DIR] [--no-sheets] [--max-requests N]
Logs contain aggregates only: no titles, ids or names.

Schedule (CLAUDE.md): every tick reads catalog pages 1-2, every 4 hours pages
1-10. A tracked item missing from the pages although its id is above the
coverage boundary has "vanished" and its page is opened. Items beyond the
covered pages are checked by age: list items every tick (< 3 h), every 4 h
(3-24 h), daily (1-30 days); 'rest' items only during their first 3 hours.
"""
import argparse
import sys
import tempfile
import time
import traceback
from collections import Counter
from pathlib import Path

from . import clock, env, models, report
from .store import DataStore
from .vinted import MAX_PAGES, BlockedError, VintedClient, VintedError

WINDOW_START_HOUR = 7  # Berlin; the window ends at midnight
TICK_PAGES = 2
FULL_SCAN_EVERY_MIN = 240
REST_MIN_PRICE = 3.0
REST_TRACK_MIN = 180
LIST_TRACK_MIN = 30 * 1440
MAX_REQUESTS = 60
DAILY_CHECKS_PER_TICK = 25
DESCRIPTION_CHECKS_PER_TICK = 10
BOUNDARY_TAIL = 10

LIST_BRANDS = {brand for brand, *_ in models.MODELS}
SIGNAL_FLAGS = {"accessory?", "digital?"}

# Check priorities: catalog -> list -> rest.
P_LIST_VANISHED, P_LIST_DUE, P_LIST_DAILY, P_DESCRIPTION, P_REST_VANISHED, P_REST_DUE = range(6)


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
        "group": "list" if cls["in_list"] else "rest",
        "mech_type": cls["mech_type"],
        "region": cls["region"],
        "format": cls["format"],
        "kit": cls["kit"],
        "kit_details": cls["kit_details"],
        "seller_id": rec["seller_id"],
        "price_start": rec["price"],
        "price_final": None,
        "price_history": [{"at": now, "price": rec["price"]}],
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


def mark_seen(item, rec, now):
    """Item is in the catalog: it is active now."""
    item["status"] = "active"
    item["last_seen_active"] = now
    item["last_checked_at"] = now
    _set_price(item, rec["price"], now)


def close(item, status, now, price=None):
    item["status"] = status
    item["closed_at"] = now
    if status == "sold":
        item["sold_detected_at"] = now
        item["price_final"] = price if price is not None else item["price_history"][-1]["price"]
        item["time_to_sell_min"] = max(0, clock.minutes_between(item["first_seen"], item["last_seen_active"]))
        if item.get("listed_after"):
            item["time_to_sell_max"] = clock.minutes_between(item["listed_after"], now)


def set_model(item, model, source):
    """Apply a model (from description or manual labeling) and move the item to its group."""
    info = models.MODEL_INFO.get(model)
    item["model"] = model
    item["model_source"] = source
    item["in_list"] = info is not None
    if info:
        item.update(brand=info["brand"], mech_type=info["mech_type"], format=info["format"], region=info["region"])
    if not item.get("closed_at"):
        item["group"] = "list" if info else "rest"


def apply_page(item, page, now):
    """Update an item from its page. Returns the page status."""
    item["last_checked_at"] = now
    if page["description"] and not item.get("description"):
        item["description"] = page["description"]
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


def wants_description(item):
    """Rest items whose title names only a list brand: the description may name the model."""
    return (item["group"] == "rest" and not item["description_checked"] and item["model"] is None
            and "preexisting" not in item["flags"] and not SIGNAL_FLAGS & set(item["flags"])
            and (item["brand"] in LIST_BRANDS or set(models.brands_in(item.get("vinted_brand") or "")) & LIST_BRANDS))


def check_priority(item, now, vanished):
    """Priority for opening the item page this tick, or None if not due."""
    age = clock.minutes_between(item["first_seen"], now)
    since = clock.minutes_between(item["last_checked_at"], now)
    preexisting = "preexisting" in item["flags"]
    if item["group"] == "rest":
        if vanished:
            return P_REST_VANISHED
        return P_REST_DUE if age < REST_TRACK_MIN and not preexisting else None
    if vanished:
        return P_LIST_VANISHED
    if preexisting or age >= 1440:
        return P_LIST_DAILY if since >= 1440 else None
    if age < 180:
        return P_LIST_DUE
    return P_LIST_DUE if since >= 240 else None


# ---------------------------------------------------------------- tick

def run_tick(store, client, labels=None, now=None):
    """Process one tick against the data store. Returns a result dict."""
    started = time.monotonic()
    now = now or clock.stamp()
    today = now[:10]
    state = store.load_state()
    first_run = "first_run_at" not in state
    first_of_day = not first_run and state.get("last_tick_at", "")[:10] != today
    rest_enabled = state.get("rest_disabled_on") != today
    stats, errors = Counter(), []

    active = store.load_active()
    closed = store.load_closed()
    changed = set()

    # Manual labels win over everything and are never overwritten.
    for item_id, text in (labels or {}).items():
        item = active.get(item_id) or closed.get(item_id)
        if item is None:
            continue
        model = models.canonical_model(text) or text
        if item.get("model") != model or item.get("model_source") != "manual":
            set_model(item, model, "manual")
            changed.add(item_id)

    # The model dictionary changed: re-classify active items (manual labels stay).
    if state.get("models_version") != models.VERSION:
        stats["models_version_changed"] = 1
        for item in active.values():
            if item.get("model_source") == "manual":
                continue
            cls = models.classify(item["title"], item.get("description"), item.get("vinted_brand"))
            if cls["model"] != item.get("model"):
                set_model(item, cls["model"], cls["model_source"])
                changed.add(item["id"])
                stats["reclassified"] += 1
        state["models_version"] = models.VERSION

    # ---- catalog
    full_scan = first_run or clock.minutes_between(state.get("last_full_scan_at") or "2000-01-01 00:00", now) >= FULL_SCAN_EVERY_MIN
    seen, last_page, pages_read = {}, [], 0
    for page in range(1, (MAX_PAGES if full_scan else TICK_PAGES) + 1):
        try:
            items = client.catalog_page(page)
        except VintedError as exc:
            errors.append(f"catalog page {page}: {exc}")
            if isinstance(exc, BlockedError):
                rest_enabled = False
            if page <= TICK_PAGES:
                return _finish(store, state, now, started, client, stats, errors, full_scan, pages_read,
                               rest_enabled, today, active, closed, changed, fatal=True)
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

    # ---- seen items: update tracked, create new
    max_seen = state.get("max_seen_id", 0)
    extra = ["preexisting"] if first_run else (["night"] if first_of_day else [])
    listed_after = None if first_run else state.get("last_tick_at")
    for rec_id, rec in seen.items():
        if rec_id in active:
            mark_seen(active[rec_id], rec, now)
            changed.add(rec_id)
        elif rec_id > max_seen:
            item = new_item(rec, now, listed_after, extra)
            if item["group"] == "list" or (rec["price"] or 0) >= REST_MIN_PRICE:
                active[rec_id] = item
                changed.add(rec_id)
                stats[f"new_{item['group']}"] += 1
        elif rec_id not in closed:
            stats["bumped"] += 1
    state["max_seen_id"] = max([max_seen, *seen])

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
        elif wants_description(item):
            queue.append((P_DESCRIPTION, item["first_seen"], item["id"]))
    queue.sort()
    daily = descriptions = 0
    for priority, _, item_id in queue:
        item = active[item_id]
        if priority == P_LIST_DAILY:
            daily += 1
            if daily > DAILY_CHECKS_PER_TICK:
                stats["deferred"] += 1
                continue
        if priority == P_DESCRIPTION:
            descriptions += 1
            if descriptions > DESCRIPTION_CHECKS_PER_TICK:
                stats["deferred"] += 1
                continue
        if priority >= P_REST_VANISHED and not rest_enabled:
            stats["deferred"] += 1
            continue
        if client.requests_made >= MAX_REQUESTS:
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
        if priority == P_DESCRIPTION:
            item["description_checked"] = True
            stats["descriptions"] += 1
        status = apply_page(item, page, now)
        if status == "sold":
            stats[f"sold_{item['group']}"] += 1
        elif status in ("deleted", "reserved", "hidden", "unknown"):
            stats[status] += 1
        if priority == P_DESCRIPTION and item["description"] and item["model"] is None:
            cls = models.classify(item["title"], item["description"], item.get("vinted_brand"))
            if cls["model"]:
                set_model(item, cls["model"], "description")
                stats["description_to_list"] += 1

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
                   rest_enabled, today, active, closed, changed, fatal=False, daily=first_run or first_of_day)


def _finish(store, state, now, started, client, stats, errors, full_scan, pages, rest_enabled, today,
            active, closed, changed, fatal, daily=False):
    if not rest_enabled:
        state["rest_disabled_on"] = today
    for item_id in changed:
        item = active.get(item_id) or closed.get(item_id)
        store.save(item)
        if item.get("closed_at") and item_id in active:
            closed[item_id] = active.pop(item_id)
    run = {
        "at": now, "full_scan": full_scan, "pages": pages, "requests": client.requests_made,
        "mb": round(client.bytes_received / 1e6, 1), "seconds": round(time.monotonic() - started),
        "new_list": stats["new_list"], "new_rest": stats["new_rest"], "bumped": stats["bumped"],
        "checks": stats["checks"], "sold_list": stats["sold_list"], "sold_rest": stats["sold_rest"],
        "deleted": stats["deleted"], "reserved_hidden": stats["reserved"] + stats["hidden"],
        "unknown": stats["unknown"], "closed_3h": stats["closed_3h"], "closed_30d": stats["closed_30d"],
        "descriptions": stats["descriptions"], "description_to_list": stats["description_to_list"],
        "deferred": stats["deferred"], "check_errors": stats["check_errors"],
        "reclassified": stats["reclassified"],
        "rest_enabled": rest_enabled, "errors": [env.redact(e) for e in errors],
    }
    store.save_state(state)
    store.append_run(run)
    all_items = list(active.values()) + list(closed.values())
    summary = report.summarize(all_items, now)
    if daily:
        store.write_exports(all_items, summary, report.readme(summary))
    return {"run": run, "fatal": fatal, "daily": daily, "items": all_items, "summary": summary,
            "models_updated": bool(stats["models_version_changed"])}


def log_line(run):
    return (f"tick {run['at'][11:]} | pages {run['pages']}{' (full)' if run['full_scan'] else ''}"
            f" | requests {run['requests']} ({run['mb']} MB, {run['seconds']} s)"
            f" | new: list {run['new_list']}, rest {run['new_rest']} | bumped {run['bumped']}"
            f" | checks {run['checks']}: sold list {run['sold_list']}, rest {run['sold_rest']},"
            f" deleted {run['deleted']}, reserved/hidden {run['reserved_hidden']}, unknown {run['unknown']}"
            f" | closed 3h {run['closed_3h']}, 30d {run['closed_30d']}"
            f" | descriptions {run['descriptions']} (-> list {run['description_to_list']})"
            f" | deferred {run['deferred']}, check errors {run['check_errors']}"
            f"{' | reclassified ' + str(run['reclassified']) if run.get('reclassified') else ''}"
            f"{'' if run['rest_enabled'] else ' | rest disabled today'}"
            f" | errors: {'; '.join(run['errors']) or 'none'}")


def runs_row(run):
    return [run["at"], "да" if run["full_scan"] else "", run["pages"], run["requests"], run["mb"], run["seconds"],
            run["new_list"], run["new_rest"], run["bumped"], run["checks"], run["sold_list"], run["sold_rest"],
            run["deleted"], run["reserved_hidden"], run["closed_3h"], run["closed_30d"], run["descriptions"],
            run["description_to_list"], run["deferred"], "; ".join(run["errors"])]


# ---------------------------------------------------------------- sheets and entry point

def write_sheets(writer, result, state_flags):
    from . import sheets

    items = result["items"]
    writer.replace(sheets.LIST_SHEET, report.item_rows([i for i in items if i.get("group") == "list"]))
    writer.replace(sheets.CHEAP_SHEET,
                   report.item_rows(report.cheap_cameras(items, sheets.CHEAP_MAX_PRICE), with_group=True))
    writer.replace(sheets.SUMMARY_SHEET, report.summary_rows(result["summary"]))
    if not state_flags.get("runs_header"):
        writer.ensure_runs_header()
    writer.append_run(runs_row(result["run"]))
    if result["daily"]:
        writer.replace(sheets.REST_SHEET, report.item_rows([i for i in items if i.get("group") == "rest"]))
    if result["daily"] or result.get("models_updated"):
        writer.ensure_models()


def main():
    parser = argparse.ArgumentParser(description="One tracker tick.")
    parser.add_argument("--force", action="store_true", help="run outside the 07:00-00:00 Berlin window")
    parser.add_argument("--local", help="use a local folder as the data store (no git)")
    parser.add_argument("--no-sheets", action="store_true", help="skip Google Sheets")
    parser.add_argument("--max-requests", type=int, default=MAX_REQUESTS + 15)
    args = parser.parse_args()

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


def _main(args):
    from . import datarepo, sheets

    writer, labels, code = None, {}, 0
    if not args.no_sheets:
        try:
            writer = sheets.SheetWriter(sheets.open_spreadsheet())
            labels = writer.manual_labels()
        except Exception as exc:
            print(f"sheets unavailable: {type(exc).__name__}: {env.redact(exc)}")
            writer, code = None, 1
    client = VintedClient(max_requests=args.max_requests)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(args.local) if args.local else datarepo.clone(Path(tmp) / "data")
        store = DataStore(root)
        state_flags = store.load_state()
        result = run_tick(store, client, labels)
        print(log_line(result["run"]))
        if not args.local:
            datarepo.commit_and_push(root, f"tick {result['run']['at']}")
        if writer:
            try:
                write_sheets(writer, result, state_flags)
                if not state_flags.get("runs_header"):
                    state = store.load_state()
                    state["runs_header"] = True
                    store.save_state(state)
                    if not args.local:
                        datarepo.commit_and_push(root, "sheets header ready")
            except Exception as exc:
                print(f"sheets write failed: {type(exc).__name__}: {env.redact(exc)}")
                code = 1
    if result["fatal"]:
        code = 1  # broken catalog: GitHub sends an e-mail
    return code


if __name__ == "__main__":
    sys.exit(main())
