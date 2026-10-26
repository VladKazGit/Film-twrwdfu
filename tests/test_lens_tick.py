"""Lens checks on fake Vinted pages. Run: python -m tests.test_lens_tick"""
import random
import tempfile
from datetime import datetime, timedelta

from tracker import lens_loop, lens_report, lens_tick, lenses
from tracker.env import BERLIN
from tracker.store import DataStore


def rec(item_id, title, price):
    return {"id": item_id, "title": title, "url": f"https://www.vinted.de/items/{item_id}", "price": price,
            "brand": None, "condition": "Gut", "seller_id": 7, "promoted": False, "favourites": 1, "photo": None}


class FakeClient:
    def __init__(self, catalog, search=None, items=None):
        self.catalog, self.search, self.items = catalog, search or {}, items or {}
        self.requests_made, self.opened = 0, []

    def has_time(self):
        return True

    def lens_page(self, page, text=None):
        self.requests_made += 1
        return (self.search.get((text, page), []) if text else self.catalog.get(page, []))

    def item_page(self, item_id):
        self.requests_made += 1
        self.opened.append(item_id)
        base = {"status": "active", "price": None, "description": None, "uploaded_ago": None, "favourites": None,
                "photo": None, "condition": None}
        return {**base, **self.items.get(item_id, {})}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = DataStore(tmp)
        top = [rec(1000, "Sony FE 85mm f/1.8", 400.0)]
        search = {("helios 44", 1): [rec(100, "Helios 44-2 58mm f/2 M42", 40.0),
                                     rec(101, "Zenit E + Helios 44-2 58mm", 60.0),          # a kit
                                     rec(102, "Adapter M42 Sony E für Helios 44-2", 9.0),  # an accessory
                                     rec(103, "Pentacon 50mm 1.8 M42", 30.0)]}
        # First check: marks the catalog's top, the first collection finds what is listed already.
        r1 = lens_tick.run_check(store, FakeClient({1: top}, search), now="2026-10-27 08:00")
        assert r1["run"]["found"] == 2 and r1["run"]["new"] == 0 and not r1["backfill_done"], "pages unread yet"
        assert r1["run"]["skipped_kits"] == 1 and r1["run"]["skipped_accessories"] == 1
        cards = {c["id"]: c for c in r1["cards"]}
        assert cards[100]["model"] == "Helios-44-2" and cards[100]["flags"] == ["preexisting"] and 103 in cards
        assert store.load_state()["top_id"] == 1000
        # Second check: a new listing on top (listed after the first check); every unread lens gets its page.
        catalog = {1: [rec(1001, "Super Takumar 50mm f/1.4", 120.0)] + top}
        items = {100: {"uploaded_ago": "3 Wochen", "description": "Schönes Objektiv", "price": 35.0},
                 1001: {"uploaded_ago": "5 Std."}}
        client = FakeClient(catalog, search, items)
        r2 = lens_tick.run_check(store, client, now="2026-10-27 09:45")
        assert r2["run"]["new"] == 1 and client.opened[0] == 1001 and set(client.opened) == {1001, 100, 103}
        cards = {c["id"]: c for c in r2["cards"]}
        assert cards[1001]["listed_after"] == "2026-10-27 08:00" and cards[1001]["model"] == "Super-Takumar 50mm f/1.4"
        assert cards[100]["vinted_listed_est"] == "2026-10-06" and [p["price"] for p in cards[100]["price_history"]] == [40.0, 35.0]
        assert client.requests_made == 1 + 3, "nothing more to search: the first collection is done"
        assert r2["backfill_done"], "searched and every page read"
        # Third check: the new one is sold; the 3-week-old one is not due again (daily); one without
        # Vinted's date counts from its first sighting (young: every check).
        client = FakeClient(catalog, search, {1001: {"status": "sold", "price": 110.0}})
        r3 = lens_tick.run_check(store, client, now="2026-10-27 11:30")
        assert sorted(client.opened) == [103, 1001] and r3["run"]["sold"] == 1, (client.opened, r3["run"])
        sold = next(c for c in r3["cards"] if c["id"] == 1001)
        assert sold["status"] == "sold" and sold["price_final"] == 110.0 and sold["closed_at"] == "2026-10-27 11:30"
        assert store.load_closed()[1001]["status"] == "sold" and 1001 not in store.load_active()
        # The sheets
        sales = lens_report.sales_rows(r3["cards"], "2026-10-27 11:30")
        assert len(sales) == 2 and sales[1][0] == "Super-Takumar 50mm f/1.4" and sales[1][2] == 110.0
        summary = lens_report.summary_rows(r3["cards"], "2026-10-27 11:30")
        head = summary[2]
        row = next(r for r in summary[3:] if r[0] == "Super-Takumar 50mm f/1.4")
        assert row[head.index("Продано")] == 1 and row[head.index("Средняя цена продажи, €")] == 110
        helios = next(r for r in summary[3:] if r[0] == "Helios-44-2")
        assert helios[head.index("В продаже")] == 1 and helios[head.index("Средняя цена объявлений, €")] == 35
        assert any(r[0] == "Volna-3 80mm f/2.8" and r[2] == 0 for r in summary[3:]), "every model of the list shows"
        items_rows = lens_report.item_rows(r3["cards"], "2026-10-27 11:30")
        assert items_rows[0] == lens_report.ITEMS_HEADER and len(items_rows) == 4
        assert len(lens_report.model_rows()) > 60 and lens_report.runs_row(r3["run"])[0] == "2026-10-27 11:30"

    # A word of the list without details: 'Без деталей', unless its description tells the model; the
    # user's label wins; a change of the rules classifies the old cards again (a converter leaves).
    with tempfile.TemporaryDirectory() as tmp:
        store = DataStore(tmp)
        search = {("helios 44", 1): [rec(300, "Obiettivo helios", 25.0), rec(301, "Tokina Objektive", 15.0),
                                     rec(302, "Vivitar 28mm f/2.8 Canon FD", 20.0)]}
        lens_tick.run_check(store, FakeClient({1: [rec(2000, "x", 1.0)]}, search), now="2026-10-27 08:00")
        cards = {c["id"]: c for c in store.load_active().values()}
        assert cards[300]["kind"] == cards[301]["kind"] == "unclear" and cards[302]["model"] == "Vivitar 28mm f/2.8 (Canon FD)"
        assert cards[302]["mount"] == "Canon FD"
        canon = lens_report.canon_rows([c for c in cards.values() if lens_report.is_lens(c)])
        assert canon[0] == lens_report.CANON_HEADER and len(canon) == 2, "only the lenses on sale now"
        assert canon[1][:5] == ["Vivitar 28mm f/2.8 (Canon FD)", "Canon FD", "Canon TX, AV-1, FTb QL",
                                "Vivitar 28mm f/2.8 Canon FD", 20.0] and canon[1][-1].endswith("/302"), canon[1]
        assert not lens_report.canon_rows([dict(cards[302], status="sold")])[1:], "a sold one is not there"
        items = {300: {"description": "Helios 44M-4 58mm, funziona", "uploaded_ago": "2 Wochen"}, 301: {"description": "alt"}}
        r = lens_tick.run_check(store, FakeClient({1: [rec(2000, "x", 1.0)]}, search, items), now="2026-10-27 09:45",
                                labels={301: "Tokina 28mm f/2.8 (C/Y)"})
        cards = {c["id"]: c for c in r["cards"]}
        assert cards[300]["model"] == "Helios-44M-4" and cards[300]["kind"] == "lens" and r["run"]["by_description"] == 1
        assert cards[301]["model"] == "Tokina 28mm f/2.8 (C/Y)" and cards[301]["model_source"] == "manual"
        assert len(lens_report.unclear_rows(r["cards"])) == 1, "both now named"
        lens_tick.apply_comments(cards, {300: "это Гелиос 44М-4?"})
        row = lens_report.unclear_rows([dict(cards[300], kind="unclear", model_source=None)])[1]
        assert row[lens_report.UNCLEAR_HEADER.index("Комментарий")] == "это Гелиос 44М-4?", "the user's comment stays"
        assert lens_report.unclear_rows([dict(cards[300], kind="unclear", unclear_reason=None, model_source=None)])[1][1]
        old = dict(cards[302], title="Vivitar 2x Teleconverter Canon FD")  # as if carded by older rules
        store.save(old)
        state = store.load_state()
        state["rules"] = 1
        state["backfill"] = {"query": 3, "page": 1, "done_at": None}  # the first version's counter
        store.save_state(state)
        r = lens_tick.run_check(store, FakeClient({1: [rec(2000, "x", 1.0)]}), now="2026-10-27 11:30")
        assert 302 not in {c["id"] for c in r["cards"]} and r["run"]["dropped"] == 1, r["run"]
        backfill = store.load_state()["backfill"]
        assert backfill["rules"] == lenses.VERSION and backfill["done"] == lenses.search_queries(), "searched once more"
        assert r["run"]["search_pages"] == len(lenses.search_queries())

    # 'Не разобрано': every row as tall as row 2 (the user sets it for the photos).
    from tracker import sheets

    class Sheet:
        id, title, row_count = 5, lens_report.UNCLEAR_SHEET, 40

    class Book:
        sent = []

        def worksheets(self):
            return [Sheet()]

        def fetch_sheet_metadata(self, params=None):
            assert params["ranges"] == [f"'{lens_report.UNCLEAR_SHEET}'!A2"]
            return {"sheets": [{"data": [{"rowMetadata": [{"pixelSize": 150}]}]}]}

        def batch_update(self, body):
            self.sent += body["requests"]

    class Unclear:  # the sheet as the user left it: a comment on one row, one cleared
        def get_all_values(self):
            head = lens_report.UNCLEAR_HEADER
            row = lambda i, text: [""] * head.index("id") + [str(i), "https://www.vinted.de/items/1", text]
            return [head, row(300, "проверить фото"), row(301, "")]

    class Writer:
        def has(self, title):
            return True

        def _get(self, title, header=None):
            return Unclear()

    assert lens_report.unclear_comments(Writer()) == {300: "проверить фото", 301: ""}

    writer = sheets.SheetWriter(Book())
    assert writer.row_height(lens_report.UNCLEAR_SHEET, 2) == 150
    writer.set_row_height(lens_report.UNCLEAR_SHEET, 150)
    dim = Book.sent[0]["updateDimensionProperties"]
    assert dim["properties"]["pixelSize"] == 150 and dim["range"]["startIndex"] == 1 and dim["range"]["endIndex"] == 40

    # The lens chain: 10 checks a day, back to back while the first collection runs, none at night.
    rng = random.Random(1)
    last = datetime(2026, 10, 27, 12, 0, tzinfo=BERLIN)
    gap = (lens_loop.next_check(last, False, rng) - last).total_seconds() / 60
    assert 95 <= gap <= 108, gap
    assert (lens_loop.next_check(last, True, rng) - last) == timedelta(seconds=60)
    night = lens_loop.next_check(datetime(2026, 10, 27, 23, 30, tzinfo=BERLIN), False, rng)
    assert night.day == 28 and night.hour == 7, night
    clock = {"now": datetime(2026, 10, 27, 10, 0, tzinfo=BERLIN)}
    codes = iter([10, 10, 0, 0, 0])
    calls = []

    def check():
        calls.append(clock["now"])
        clock["now"] += timedelta(minutes=20)
        return next(codes)

    def sleep(seconds):
        clock["now"] += timedelta(seconds=seconds)

    failures = lens_loop.run_loop(lambda: clock["now"], sleep, check, log=lambda *a: None, rng=rng)
    assert failures == 0 and len(calls) == 5, calls  # 3 back to back, then ~100 minutes apart within 5.5 hours
    assert (calls[1] - calls[0]).total_seconds() / 60 == 21 and (calls[3] - calls[2]).total_seconds() / 60 > 110
    assert lenses.search_queries()[0] == "helios 44"
    print("lens tick tests passed")


if __name__ == "__main__":
    main()
