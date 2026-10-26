"""One lens check: the models of the lens sheet ('Лист1', see tracker.lenses) in Vinted's 'Objektive'.
Started by tracker.lens_loop, 10 times a day (one right after another while the first collection runs).

- New listings: the category's newest pages, down to the newest id of the previous check.
- The first collection (about two days): every search of the list, page by page while a page still
  has lenses of the list, as far as each check's budget goes; what it finds was listed before the
  tracker saw it ('preexisting': Vinted's upload date from the listing's page instead).
- Item pages: every lens once (description, upload date, photo, status), then again by its age -
  every check up to 3 days, daily up to 2 weeks, then weekly. A lens gone from Vinted is sold
  (its page says 'Verkauft') or deleted.

Only lenses of the list: a camera with the lens (the camera tracker counts it), a cap, hood, adapter,
box or manual for one is left out. Data in lenses/ of the private data repo, the same layout as the
cameras'; the lens sheet gets 'Объективы', 'Продажи', 'Сводка', 'Модели', 'Запуски' ('Лист1' stays
the user's). Logs show counts only. Exit code 10: the first collection is not done yet.

    python -m tracker.lens_tick [--local DIR] [--no-sheets]
    python -m tracker.lens_tick --sheets-only   # the sheets from the data as it is, no Vinted requests
"""
import argparse
import sys
import tempfile
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

from . import clock, env, lenses, report
from .store import DataStore
from .vinted import BlockedError, VintedClient, VintedError, age_days

CHECK_BUDGET_S = 25 * 60   # Vinted traffic per check
NEW_PAGES_MAX = 6          # ~100 new lenses of every kind per check; 6 pages cover a night too
SEARCH_PAGES_MAX = 10      # a search shows 960 listings at most
ITEM_PAGES_MAX = 220       # item pages per check (new ones first)
# Item page checks by the lens's age on Vinted: (up to days, minutes between checks)
RECHECK = ((3, 90), (14, 24 * 60), (None, 7 * 24 * 60))
BACKFILL_DONE = 0
BACKFILL_PENDING = 10       # exit code: the first collection goes on


def _listed(card):
    """The listing's start: Vinted's upload date when known, else its first sighting."""
    return f"{card['vinted_listed_est']} 00:00" if card.get("vinted_listed_est") else card["first_seen"]


def new_card(rec, cls, now, listed_after, flags):
    price = rec.get("price")
    return {
        "id": rec["id"], "url": rec["url"], "title": rec["title"], "description": None,
        "model": cls["model"], "kind": cls["kind"], "unclear_reason": cls.get("reason"), "mount": cls["mount"],
        "brand": rec.get("brand"),
        "condition": rec.get("condition"),
        "seller_id": rec.get("seller_id"), "photo": rec.get("photo"),
        "price_start": price, "price_final": None,
        "price_history": [{"at": now, "price": price}] if price is not None else [],
        "favourites": rec.get("favourites"),
        "listed_after": listed_after, "first_seen": now, "last_seen_active": now, "last_checked_at": None,
        "vinted_listed_est": None, "uploaded_ago": None,
        "sold_detected_at": None, "closed_at": None, "status": "active", "flags": list(flags) + cls["flags"],
    }


def _set_price(card, price, now):
    if price is not None and price != report.current_price(card):
        card.setdefault("price_history", []).append({"at": now, "price": price})


def mark_seen(card, rec, now):
    """A lens in a listing page is on sale now."""
    card["last_seen_active"] = now
    _set_price(card, rec.get("price"), now)
    if rec.get("favourites") is not None:
        card["favourites"] = rec["favourites"]


def close(card, status, now, price=None):
    card.update(status=status, closed_at=now)
    if status == "sold":
        card["sold_detected_at"] = now
        card["price_final"] = price if price is not None else report.current_price(card)


def apply_page(card, page, now):
    """Update a lens from its item page. Returns the page status."""
    card["last_checked_at"] = now
    for key in ("description", "photo", "condition"):
        if page.get(key) and not card.get(key):
            card[key] = page[key]
    days = age_days(page.get("uploaded_ago"))
    if days is not None and not card.get("vinted_listed_est"):
        card["uploaded_ago"] = page["uploaded_ago"]
        card["vinted_listed_est"] = (clock.parse(now) - timedelta(days=days)).strftime("%Y-%m-%d")
    if page.get("favourites") is not None:
        card["favourites"] = page["favourites"]
    status = page["status"]
    if status == "active":
        card.update(status="active", last_seen_active=now)
        _set_price(card, page.get("price"), now)
    elif status in ("reserved", "hidden"):
        card["status"] = status
    elif status == "sold":
        close(card, "sold", now, page.get("price"))
    elif status == "deleted":
        close(card, "deleted", now)
    return status


def due(card, now):
    """The item page of an open lens is due: never read, or read long enough ago for its age."""
    if card.get("closed_at"):
        return False
    if not card.get("last_checked_at"):
        return True
    if card.get("kind") == "unclear":  # 'Без деталей': kept up to date weekly
        return clock.minutes_between(card["last_checked_at"], now) >= RECHECK[-1][1]
    age = clock.minutes_between(_listed(card), now) / 1440
    gap = next(minutes for limit, minutes in RECHECK if limit is None or age < limit)
    return clock.minutes_between(card["last_checked_at"], now) >= gap


def _take(recs, cards, now, listed_after, flags, stats):
    """Lenses of the list (and 'unclear' ones) from listing records: known ones seen, new ones carded.
    Returns the hits (lenses of the list)."""
    hits = 0
    for rec in recs:
        cls = lenses.classify(rec["title"])
        if cls["kind"] not in ("lens", "unclear"):
            stats[f"skipped_{cls['kind']}"] += cls["kind"] is not None
            continue
        hits += cls["kind"] == "lens"
        card = cards.get(rec["id"])
        if card is None:
            cards[rec["id"]] = new_card(rec, cls, now, listed_after, flags)
            stats["new" if not flags else "found"] += 1
        elif not card.get("closed_at"):
            mark_seen(card, rec, now)
    return hits


def reclassify(card):
    """The card by the current rules (title, and the description for an unclear one). False: drop it."""
    if card.get("model_source") == "manual":
        return True
    cls = lenses.classify(card["title"], card.get("description"))
    if cls["kind"] not in ("lens", "unclear"):
        return False
    card.update(model=cls["model"], kind=cls["kind"], mount=cls["mount"], unclear_reason=cls.get("reason"),
                flags=[f for f in card.get("flags") or [] if f == "preexisting"] + cls["flags"])
    return True


def apply_labels(cards, labels):
    """'Ручная разметка': {id: model} - the user's model wins (an unclear card becomes a lens)."""
    changed = 0
    for item_id, model in labels.items():
        card = cards.get(item_id)
        if card and (card.get("model"), card.get("model_source")) != (model, "manual"):
            card.update(model=model, kind="lens", model_source="manual", unclear_reason=None)
            changed += 1
    return changed


def run_check(store, client, now=None, labels=None):
    """One check. Returns {'run', 'cards', 'backfill_done', 'blocked'}."""
    now = now or clock.stamp()
    state = store.load_state()
    cards = {**store.load_closed(), **store.load_active()}
    stats, errors = Counter(), []
    if state.get("rules") != lenses.VERSION:  # the rules changed: every card again, the ones out leave the data
        for item_id in [i for i, c in cards.items() if not reclassify(c)]:
            del cards[item_id]
            store.discard(item_id)
            stats["dropped"] += 1
        state["rules"] = lenses.VERSION
    stats["labelled"] = apply_labels(cards, labels or {})
    first = "top_id" not in state
    previous = state.get("last_check_at")
    try:
        # ---- new listings of the category, down to the previous check's newest id
        top = state.get("top_id", 0)
        newest = top
        for page in range(1, NEW_PAGES_MAX + 1):
            recs = client.lens_page(page)
            stats["catalog_pages"] += 1
            plain = [r for r in recs if not r.get("promoted")]  # promoted ones are old listings too
            newest = max([newest] + [r["id"] for r in plain])
            if not first:  # the very first check only marks the top: the first collection finds the rest
                _take([r for r in recs if r["id"] > top], cards, now, previous, [], stats)
            if first or any(r["id"] <= top for r in plain) or len(recs) < 96:
                break
        state["top_id"] = newest

        # ---- item pages: new lenses first, then the youngest due ones
        queue = sorted((c for c in cards.values() if due(c, now)),
                       key=lambda c: (c.get("last_checked_at") is not None, "preexisting" in c["flags"],
                                      clock.minutes_between(_listed(c), now) if c.get("last_checked_at") else 0))
        for card in queue[:ITEM_PAGES_MAX]:
            if not client.has_time():
                stats["deferred"] += 1
                continue
            try:
                page = client.item_page(card["id"])
            except BlockedError:
                raise
            except VintedError:
                stats["check_errors"] += 1
                continue
            stats["item_pages"] += 1
            status = apply_page(card, page, now)
            stats[status] += status in ("sold", "deleted", "reserved", "hidden")
            if card.get("kind") == "unclear" and card.get("description") and card.get("model_source") != "manual":
                cls = lenses.classify(card["title"], card["description"])  # the description may tell the model
                if cls["kind"] == "lens":
                    card.update(model=cls["model"], kind="lens", mount=cls["mount"], model_source="description",
                                unclear_reason=None)
                    stats["by_description"] += 1
        stats["deferred"] += max(0, len(queue) - ITEM_PAGES_MAX)

        # ---- the first collection: every search of the list, as far as the budget goes
        backfill = state.setdefault("backfill", {"page": 1, "done_at": None})
        queries = lenses.search_queries()
        if "done" not in backfill:  # the first version counted searches by their place in the list
            backfill["done"] = queries[:len(queries) if backfill.get("done_at") else backfill.get("query", 0)]
            backfill.pop("query", None)
        if backfill.get("rules", lenses.VERSION) != lenses.VERSION or "rules" not in backfill and lenses.VERSION >= 3:
            backfill.update(done=[], page=1, done_at=None)  # rules that take what the searches skipped: once more
        backfill["rules"] = lenses.VERSION
        pending = [q for q in queries if q not in backfill["done"]]
        backfill["done_at"] = backfill["done_at"] if not pending else None
        while pending and client.has_time():
            text = pending[0]
            recs = client.lens_page(backfill["page"], text)
            stats["search_pages"] += 1
            hits = _take(recs, cards, now, None, ["preexisting"], stats)
            if len(recs) < 96 or hits == 0 or backfill["page"] >= SEARCH_PAGES_MAX:
                backfill["done"].append(pending.pop(0))
                backfill["page"] = 1
                if not pending:
                    backfill["done_at"] = now
            else:
                backfill["page"] += 1
    except BlockedError as exc:
        errors.append(f"blocked: {exc}")
    except VintedError as exc:
        errors.append(str(exc))

    state["last_check_at"] = now
    for card in cards.values():
        store.save(card)
    store.save_state(state)
    open_cards = [c for c in cards.values() if not c.get("closed_at")]
    run = {"at": now, "new": stats["new"], "found": stats["found"], "item_pages": stats["item_pages"],
           "catalog_pages": stats["catalog_pages"], "search_pages": stats["search_pages"],
           "sold": stats["sold"], "deleted": stats["deleted"], "reserved_hidden": stats["reserved"] + stats["hidden"],
           "deferred": stats["deferred"], "skipped_kits": stats["skipped_kit"],
           "skipped_accessories": stats["skipped_accessory"], "open": len(open_cards), "total": len(cards),
           "unclear": sum(c.get("kind") == "unclear" for c in open_cards), "by_description": stats["by_description"],
           "labelled": stats["labelled"], "dropped": stats["dropped"],
           "backfill": "готов" if state["backfill"]["done_at"] else
           f"поиск {len(state['backfill']['done']) + 1} из {len(lenses.search_queries())}",
           "requests": client.requests_made, "errors": errors}
    store.append_run(run)
    # The first collection ends when its lenses have their pages read too (checks go on back to back till then).
    unread = any(not c.get("last_checked_at") and not c.get("closed_at") for c in cards.values())
    return {"run": run, "cards": list(cards.values()), "backfill_done": bool(state["backfill"]["done_at"]) and not unread,
            "blocked": any(e.startswith("blocked") for e in errors)}


def log_line(run):
    return (f"lens check {run['at'][11:]} | new {run['new']}, found {run['found']}, item pages {run['item_pages']}"
            f" (sold {run['sold']}, deleted {run['deleted']}, reserved/hidden {run['reserved_hidden']},"
            f" deferred {run['deferred']}) | pages: catalog {run['catalog_pages']}, search {run['search_pages']}"
            f" | skipped kits {run['skipped_kits']}, accessories {run['skipped_accessories']}"
            f" | open {run['open']} of {run['total']}, unclear {run['unclear']}, by description {run['by_description']},"
            f" labelled {run['labelled']}, dropped {run['dropped']} | first collection {'done' if run['backfill'] == 'готов' else 'running'}"
            f" | requests {run['requests']} | errors: {len(run['errors']) or 'none'}")


def open_writer():
    import gspread

    from . import sheets

    client = gspread.service_account_from_dict(env.google_sa_info())
    return sheets.SheetWriter(client.open_by_key(env.sheet_id("LENS_SHEET_ID")))


def sheets_only():
    """Rewrite the lens sheets from the data as it is (no Vinted requests, nothing pushed)."""
    from . import datarepo, lens_report

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = DataStore(datarepo.clone(Path(tmp) / "data") / "lenses")
        cards = {**store.load_closed(), **store.load_active()}
        writer = open_writer()
        apply_labels(cards, lens_report.manual_labels(writer))
        lens_report.write(writer, list(cards.values()), {"at": clock.stamp()}, add_run=False)
    print(f"lens sheets rewritten: {len(cards)} cards")
    return 0


def main():
    from . import datarepo

    parser = argparse.ArgumentParser(description="One lens check.")
    parser.add_argument("--local", help="use a local folder as the data store (no git)")
    parser.add_argument("--no-sheets", action="store_true", help="skip Google Sheets")
    parser.add_argument("--sheets-only", action="store_true", help="rewrite the sheets from the data, no check")
    args = parser.parse_args()
    if args.sheets_only:
        return sheets_only()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(args.local) if args.local else datarepo.clone(Path(tmp) / "data")
        from . import lens_report

        store = DataStore(root / "lenses")
        writer, labels = None, {}
        if not args.no_sheets:
            try:
                writer = open_writer()
                labels = lens_report.manual_labels(writer)
            except Exception as exc:
                print(f"lens sheets: not opened: {type(exc).__name__}: {env.redact(exc)}")
        result = run_check(store, VintedClient(time_budget=CHECK_BUDGET_S), labels=labels)
        print(log_line(result["run"]))
        if not args.local:
            datarepo.commit_and_push(root, f"lens check {result['run']['at']}")
        if writer is not None:
            try:  # a sheet failure must not lose the data (already pushed)
                lens_report.write(writer, result["cards"], result["run"])
            except Exception as exc:
                print(f"lens sheets failed: {type(exc).__name__}: {env.redact(exc)}")
    print(f"lens check took {(time.monotonic() - started) / 60:.1f} min")
    if result["blocked"]:
        return 1  # Vinted refuses this machine: the loop hands over to a new one
    return BACKFILL_DONE if result["backfill_done"] else BACKFILL_PENDING


if __name__ == "__main__":
    sys.exit(main())
