"""One Kleinanzeigen check: cameras of the list (the same dictionary as Vinted's, tracker.models) on
kleinanzeigen.de, category Foto. Started by tracker.ka_loop every ~30 minutes in the 07:00-00:00 Berlin
window.

- New listings: the newest pages of the types 'Kamera' and 'Kamera & Zubehör' down to listings
  WINDOW_MIN old and below the previous check's newest id (up to MAX_PAGES): a camera of the list gets a
  card - unless it has no price: 'VB' alone, 1 EUR or 'VB' up to 5 EUR ask for offers, they are skipped
  (and dropped from the data when a tracked one turns so).
  Its listing time is Kleinanzeigen's own ('Heute, 10:47'). An older id on top again was pushed up
  ('bumped'); a 'TOP' placement carries no date.
- First collection: a text search for every model of the list (newest first, up to 10 pages, while a
  page has cameras of the list): what is on sale already is 'preexisting' (its listing date is known).
  Then every model's search every two days the same way (MODEL_SEARCH_PER_CHECK, the longest-waiting
  first): listings of other types ('Weitere', 'Zubehör') come in as 'found'.
- Results carry the description's first ~250 characters: a new listing's page is read once (the whole
  description, the condition). A sighting on a page of results counts as a check. A tracked listing
  within the pages read but missing is checked on its page at once; the others when due by age
  (RECHECK). A listing taken down
  (its page redirects away) is 'removed' - sold or withdrawn, Kleinanzeigen does not tell.
No account, public pages only, 2-3 s between requests; no seller names, ids, phones or places are kept.
Data in kleinanzeigen/ of the private data repo; sheets in the Kleinanzeigen spreadsheet (secret
KA_SHEET_ID) and the comparison with Vinted (secret COMPARE_SHEET_ID). Logs show counts only.

    python -m tracker.ka_tick [--local DIR] [--no-sheets]
Exit code 10: the first collection is still running (the loop checks again at once).
"""
import argparse
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from . import clock, env, models, report
from .kleinanzeigen import TYPES, BlockedError, KaClient, KaError
from .store import DataStore

CHECK_BUDGET_S = 8 * 60
BACKFILL_BUDGET_S = 20 * 60
MAX_PAGES = {"camera": 8, "camera_and_equipment": 4}
WINDOW_MIN = 35           # read the newest pages down to listings this old: presence of the young ones
FULL_PAGE = 25
MODEL_PAGES = 10          # the first collection
DAILY_MODEL_PAGES = 4     # then: the newest pages are enough to see what is still on sale
MODEL_SEARCH_PER_CHECK = 4  # ~34 checks a day: every model about every two days
AD_PAGES_MAX = 10
OFFERS_PRICE = 5.0  # 'VB' up to this asks for offers ('1 € VB'): no price, skipped
# Page checks by the listing's age in minutes: (up to, minutes between checks)
RECHECK = ((3 * 60, 60), (1440, 240), (7 * 1440, 1440), (30 * 1440, 3 * 1440), (None, 7 * 1440))
SIGNAL_FLAGS = {"accessory?", "digital?", "compact?"}
OLD_FLAGS = {"preexisting", "found", "bumped"}
DESCRIPTION_KEEP = 1500
BACKFILL_EXIT = 10


def _as_stamp(at):
    return at if len(at) > 10 else f"{at} 00:00"


def listed_minutes(card, now):
    """Minutes since the listing went up (date-only listings: since midnight; unknown: the first sight)."""
    return clock.minutes_between(_as_stamp(card.get("listed_at") or card["first_seen"]), now)


def no_price(price, vb):
    """No real price: 'VB' alone, 1 EUR or less, or 'VB' up to OFFERS_PRICE - the seller waits for offers."""
    return price is None or price <= report.PLACEHOLDER_PRICE or (vb and price <= OFFERS_PRICE)


def classify(rec):
    """The list model of a listing, or None (no model, an accessory / digital / compact, or no price)."""
    if no_price(rec["price"], rec["vb"]):
        return None
    cls = models.classify(rec["title"], rec.get("description"))
    return None if not cls["model"] or SIGNAL_FLAGS & set(cls["flags"]) else cls


def new_card(rec, cls, now, flags):
    card = {
        "id": rec["id"], "url": rec["url"], "title": rec["title"],
        "description": (rec.get("description") or "")[:DESCRIPTION_KEEP], "photo": rec.get("photo"),
        "group": "list", "model": cls["model"], "brand": cls["brand"], "kit": cls["kit"],
        "kit_details": cls["kit_details"], "type": TYPES.get(rec.get("kind")), "price_start": rec["price"],
        "price_final": None, "price_history": [{"at": now, "price": rec["price"]}] if rec["price"] is not None else [],
        "vb": rec["vb"], "old_price": rec.get("old_price"), "listed_at": rec["listed_at"], "first_seen": now,
        "last_seen_active": now, "last_checked_at": None, "removed_detected_at": None, "closed_at": None,
        "status": "reserved" if rec.get("reserved") else "active", "condition": None, "flags": list(flags),
    }
    bundle = models.bundle_names(rec["title"])
    if bundle:
        card["bundle"] = bundle
    return card


def _set_price(card, price, now):
    if price is not None and price != report.current_price(card):
        card.setdefault("price_history", []).append({"at": now, "price": price})


def mark_seen(card, rec, now):
    card["last_seen_active"] = now
    _set_price(card, rec.get("price"), now)
    card["vb"] = rec.get("vb", card.get("vb"))
    card["status"] = "reserved" if rec.get("reserved") else "active"


def apply_ad(card, ad, now):
    """Update a card from its page. Returns the status."""
    card["last_checked_at"] = now
    if ad["status"] == "gone":
        card.update(status="removed", removed_detected_at=now, closed_at=now)
        card["price_final"] = report.current_price(card)
        return "removed"
    card.update(status=ad["status"], last_seen_active=now)
    _set_price(card, ad["price"], now)
    if ad["price"] is not None or ad["vb"]:  # the page showed a price
        card["vb"] = ad["vb"]
    if ad.get("condition"):
        card["condition"] = ad["condition"]
    if not card.get("listed_at") and ad.get("date"):
        card["listed_at"] = ad["date"]
    if ad.get("description") and len(ad["description"]) > len(card.get("description") or ""):
        card["description"] = ad["description"][:DESCRIPTION_KEEP]
    return ad["status"]


def due(card, now):
    if card.get("closed_at"):
        return False
    last = max(card.get("last_checked_at") or "", card["last_seen_active"])
    gap = next(minutes for limit, minutes in RECHECK if limit is None or listed_minutes(card, now) < limit)
    return clock.minutes_between(last, now) >= gap


class Check:
    """The state of one check: cards by id, what was seen, what vanished, the counts."""

    def __init__(self, store, client, now):
        self.store, self.client, self.now = store, client, now
        self.state = store.load_state()
        self.cards = {**store.load_closed(), **store.load_active()}
        self.stats, self.seen, self.vanished = Counter(), set(), {}

    def take(self, recs, flags_for, model=None):
        """Cards from a page of results: known ones are seen, new cameras of the list get a card
        (flags_for(rec) gives its flags). A card in its own model's search results is marked so.
        Returns the list cameras on the page."""
        cameras = 0
        for rec in recs:
            self.seen.add(rec["id"])
            card = self.cards.get(rec["id"])
            if card is None:
                cls = classify(rec)
                if not cls:
                    continue
                flags = flags_for(rec)
                card = self.cards[rec["id"]] = new_card(rec, cls, self.now, flags)
                self.stats[flags[0] if flags else "new"] += 1
            elif no_price(rec["price"], rec["vb"]):  # turned to 'VB' alone or '1 € VB': out of the data
                del self.cards[rec["id"]]
                self.store.discard(rec["id"])
                self.stats["dropped"] += 1
                continue
            else:
                if card.get("closed_at"):  # taken down by mistake (a page that failed to load): back on sale
                    card.update(closed_at=None, removed_detected_at=None, price_final=None)
                    self.stats["reopened"] += 1
                mark_seen(card, rec, self.now)
            cameras += 1
            if model and card["model"] == model:
                card["in_model_search"] = True
        return cameras

    def missing(self, recs, keep):
        """Open cards (keep(card)) with ids within the page's dated listings but not on the pages read."""
        ids = [r["id"] for r in recs if r["listed_at"]]
        if not ids:
            return
        lowest = min(ids)
        for card in self.cards.values():
            if not card.get("closed_at") and card["id"] >= lowest and card["id"] not in self.seen and keep(card):
                self.vanished[card["id"]] = card

    # ---- the newest pages of each type

    def new_listings(self):
        tops = self.state.setdefault("top_ids", {})
        for kind, max_pages in MAX_PAGES.items():
            top = tops.get(kind, 0)
            newest, read = top, []

            def flags_for(rec):
                if not rec["listed_at"]:
                    return ["bumped"]  # a 'TOP' placement: an older listing paid up
                return ["bumped"] if top and rec["id"] <= top else []

            for page in range(1, max_pages + 1):
                recs = self.client.search_page(kind, page, self.now)
                self.stats["search_pages"] += 1
                self.take(recs, flags_for)
                read += recs
                dated = [r for r in recs if r["listed_at"]]
                newest = max([newest] + [r["id"] for r in dated])
                oldest = max((listed_minutes({"listed_at": r["listed_at"], "first_seen": self.now}, self.now)
                              for r in dated), default=0)
                below_top = not top or any(r["id"] <= top for r in dated)
                if len(recs) < FULL_PAGE - 5 or (below_top and oldest >= WINDOW_MIN):
                    break
            tops[kind] = newest
            self.missing(read, lambda c, t=TYPES[kind]: c.get("type") == t)

    # ---- searches by model: the first collection, then each model once a day

    def model_searches(self):
        st = self.state.setdefault("model_search", {"last_run": {}, "backfill": "running"})
        last_run = st["last_run"]
        names = list(models.MODEL_INFO)
        backfill = st["backfill"] != "done"
        if backfill:
            queue = [n for n in names if n not in last_run]
        else:
            queue = sorted(names, key=lambda n: last_run.get(n) or "")[:MODEL_SEARCH_PER_CHECK]
        pages = MODEL_PAGES if backfill else DAILY_MODEL_PAGES
        for name in queue:
            read, finished = [], False
            for page in range(1, pages + 1):
                if not self.client.has_time():
                    break
                recs = self.client.model_search(name, page, self.now)
                self.stats["model_pages"] += 1
                read += recs
                cameras = self.take(recs, lambda rec: ["preexisting"] if backfill else ["found"], name)
                if page == pages or len(recs) < FULL_PAGE - 5 or not cameras:
                    finished = True
                    break
            if not finished:
                break  # out of time: this model again from its first page next time
            last_run[name] = self.now
            # seen in its model's results before, missing now: maybe taken down
            self.missing(read, lambda c, n=name: c["model"] == n and c.get("in_model_search"))
        if backfill and all(n in last_run for n in names):
            st["backfill"] = "done"
        return st["backfill"] != "done"

    # ---- listing pages: the vanished ones first, the new ones (read once), then the due ones (youngest first)

    def ad_pages(self):
        queue = dict(self.vanished)
        for card in self.cards.values():
            if not card.get("closed_at") and not card.get("last_checked_at") and not card.get("flags"):
                queue.setdefault(card["id"], card)
        for card in sorted((c for c in self.cards.values() if c["id"] not in self.seen and due(c, self.now)),
                           key=lambda c: listed_minutes(c, self.now)):
            queue.setdefault(card["id"], card)
        for n, card in enumerate(queue.values()):
            if n >= AD_PAGES_MAX or not self.client.has_time():
                self.stats["deferred"] = len(queue) - n
                break
            try:
                ad = self.client.ad_page(card["url"])
            except BlockedError:
                raise
            except KaError:
                self.stats["ad_errors"] += 1
                continue
            self.stats["ad_pages"] += 1
            self.stats[apply_ad(card, ad, self.now)] += 1

    def reclassify(self):
        """Bundles by the current rules; open cards without a price now leave the data; the dictionary
        changed: the cards again (out: no longer a camera of the list)."""
        for item_id, card in list(self.cards.items()):
            if not card.get("closed_at") and no_price(report.current_price(card), card.get("vb")):
                del self.cards[item_id]
                self.store.discard(item_id)
                self.stats["dropped"] += 1
                continue
            bundle = models.bundle_names(card["title"])
            if bundle != card.get("bundle", []):
                card["bundle"] = bundle
        if self.state.get("models_version") == models.VERSION:
            return
        for item_id, card in list(self.cards.items()):
            cls = models.classify(card["title"], card.get("description"))
            if not cls["model"] or SIGNAL_FLAGS & set(cls["flags"]):
                del self.cards[item_id]
                self.store.discard(item_id)
                self.stats["dropped"] += 1
            else:
                card.update(model=cls["model"], brand=cls["brand"], kit=cls["kit"], kit_details=cls["kit_details"])
        self.state["models_version"] = models.VERSION


def run_check(store, client, now=None):
    """One check. Returns {'run', 'cards', 'blocked', 'backfill'}."""
    check = Check(store, client, now or clock.stamp())
    errors, backfill = [], check.state.get("model_search", {}).get("backfill") != "done"
    try:
        check.reclassify()
        check.new_listings()
        if backfill:  # the first collection before the page checks: these are all seen now
            backfill = check.model_searches()
            check.ad_pages()
        else:
            check.ad_pages()
            check.model_searches()
    except BlockedError as exc:
        errors.append(f"blocked: {exc}")
    except KaError as exc:
        errors.append(str(exc))

    stats, cards = check.stats, check.cards
    check.state["last_check_at"] = check.now
    for card in cards.values():
        store.save(card)
    store.save_state(check.state)
    run = {"at": check.now, "new": stats["new"], "bumped": stats["bumped"], "preexisting": stats["preexisting"],
           "found": stats["found"], "removed": stats["removed"], "reserved": stats["reserved"],
           "search_pages": stats["search_pages"], "model_pages": stats["model_pages"], "ad_pages": stats["ad_pages"],
           "deferred": stats["deferred"], "dropped": stats["dropped"],
           "open": sum(not c.get("closed_at") for c in cards.values()), "total": len(cards),
           "backfill": "идёт" if backfill else "готов", "requests": client.requests_made, "errors": errors}
    store.append_run(run)
    return {"run": run, "cards": list(cards.values()), "blocked": any(e.startswith("blocked") for e in errors),
            "backfill": backfill}


def log_line(run):
    return (f"ka check {run['at'][11:]} | new {run['new']}, bumped {run['bumped']}, first collection"
            f" {run['preexisting']}, found {run['found']}, removed {run['removed']}, reserved {run['reserved']}"
            f" | pages: type {run['search_pages']}, model {run['model_pages']}, listings {run['ad_pages']}"
            f" (deferred {run['deferred']}) | open {run['open']} of {run['total']}"
            f" | first collection {'running' if run['backfill'] == 'идёт' else 'done'} | requests {run['requests']}"
            f" | errors: {len(run['errors']) or 'none'}")


def open_writer(secret):
    import gspread

    from . import sheets

    client = gspread.service_account_from_dict(env.google_sa_info())
    return sheets.SheetWriter(client.open_by_key(env.sheet_id(secret)))


def main():
    from . import datarepo, ka_report
    from .lens_tick import push_data

    parser = argparse.ArgumentParser(description="One Kleinanzeigen check.")
    parser.add_argument("--local", help="use a local folder as the data store (no git)")
    parser.add_argument("--no-sheets", action="store_true", help="skip Google Sheets")
    args = parser.parse_args()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(args.local) if args.local else datarepo.clone(Path(tmp) / "data")
        store = DataStore(root / "kleinanzeigen")
        backfill = store.load_state().get("model_search", {}).get("backfill") != "done"
        client = KaClient(time_budget=BACKFILL_BUDGET_S if backfill else CHECK_BUDGET_S)
        result = run_check(store, client)
        print(log_line(result["run"]))
        if not args.local:
            push_data(root, f"ka check {result['run']['at']}")
        if not args.no_sheets:
            done = {"at": result["run"]["at"]}
            writes = (("ka", "KA_SHEET_ID", lambda w: ka_report.write(w, result["cards"], result["run"])),
                      ("compare", "COMPARE_SHEET_ID",
                       lambda w: ka_report.write_compare(w, result["cards"], root, result["run"]["at"])))
            for name, secret, write in writes:
                try:  # a sheet failure must not lose the data (already pushed)
                    write(open_writer(secret))
                    done[name] = "ok"
                except Exception as exc:
                    done[name] = f"{type(exc).__name__}: {env.redact(exc, 150)}"
                    print(f"{name} sheets failed: {done[name]}")
            # the sheets' outcome in the data: seen before the run's log is out (5.5 hours)
            state = store.load_state()
            state["sheets"] = done
            store.save_state(state)
            if not args.local:
                push_data(root, f"ka sheets {result['run']['at']}")
    print(f"ka check took {(time.monotonic() - started) / 60:.1f} min")
    if result["blocked"]:
        return 1
    return BACKFILL_EXIT if result["backfill"] else 0


if __name__ == "__main__":
    sys.exit(main())
