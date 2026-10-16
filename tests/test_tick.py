"""Tick logic on a fake Vinted and a fake spreadsheet. Run: python -m tests.test_tick"""
import tempfile
from collections import Counter

from tracker import report, tick
from tracker.store import DataStore


def rec(item_id, title, price=50.0, brand=None, promoted=False):
    return {"id": item_id, "title": title, "url": f"https://www.vinted.de/items/{item_id}", "price": price,
            "brand": brand, "condition": "Gut", "seller_id": 1, "promoted": promoted, "favourites": 0}


class FakeClient:
    def __init__(self, pages, item_pages=None, search=None):
        self.pages, self.item_pages, self.search = pages, item_pages or {}, search or {}
        self.requests_made, self.bytes_received, self.opened = 0, 0, []

    def search_page(self, text, page, max_price):
        self.requests_made += 1
        return self.search.get((text, page), [])

    def catalog_page(self, page):
        self.requests_made += 1
        return self.pages.get(page, [])

    def item_page(self, item_id):
        self.requests_made += 1
        self.opened.append(item_id)
        base = {"status": "active", "price": None, "description": None, "uploaded_ago": None, "favourites": None}
        return {**base, **self.item_pages.get(item_id, {})}


class FakeWorksheet:
    def __init__(self, title):
        self.title, self.rows, self.size, self.id = title, [], (0, 0), abs(hash(title)) % 10_000

    def update(self, range_name, values, value_input_option):
        assert range_name == "A1" and len(values) <= self.size[0] or not self.size[0], self.title
        self.rows = [list(r) for r in values]

    def resize(self, rows, cols):
        self.size = (rows, cols)

    def freeze(self, rows):
        pass

    def row_values(self, n):
        return self.rows[n - 1] if len(self.rows) >= n else []

    def insert_row(self, row, index, value_input_option):
        self.rows.insert(index - 1, row)

    def append_row(self, row, value_input_option):
        self.rows.append(row)

    def get_all_values(self):
        return self.rows

    def col_values(self, n):
        return [r[n - 1] if len(r) >= n else "" for r in self.rows]

    def append_rows(self, rows, value_input_option):
        self.rows += [list(r) for r in rows]


class FakeSpreadsheet:
    def __init__(self):
        self.sheets = {"Запуски": FakeWorksheet("Запуски")}
        self.sheets["Запуски"].rows = [["2026-10-15 21:00", "check-setup", "test row", "1"]]

    def worksheets(self):
        return list(self.sheets.values())

    def batch_update(self, body):
        self.formats = getattr(self, "formats", []) + body["requests"]

    def add_worksheet(self, title, rows, cols):
        self.sheets[title] = FakeWorksheet(title)
        return self.sheets[title]


def older(start, n=20):
    return [rec(start - k, f"Kamera alt {k}", 20.0) for k in range(n)]


def main():
    from tracker import sheets

    with tempfile.TemporaryDirectory() as tmp:
        store = DataStore(tmp)
        # Tick 1: first run, full scan; everything is preexisting.
        pages = {1: [rec(1010, "Canon AE-1 Kamera"), rec(1009, "Polaroid Kamera", 10.0), rec(1008, "Agfa", 2.0)]
                 + older(1007), 2: older(980)}
        r1 = tick.run_tick(store, FakeClient(pages), now="2026-10-16 07:07")
        a = store.load_active()
        assert r1["run"]["full_scan"] and r1["run"]["pages"] == 2, r1["run"]
        assert 1008 not in a, "rest under 3 EUR must not be tracked"
        assert a[1010]["group"] == "list" and "preexisting" in a[1010]["flags"]
        assert r1["daily"]

        # Tick 2: two new items; the list camera vanished and is sold.
        pages = {1: [rec(1012, "Kamera Canon", 40.0), rec(1011, "Nikon FM2 body", 150.0),
                     rec(1009, "Polaroid Kamera", 10.0), rec(500, "Bumped old", 30.0),
                     rec(400, "Reflex argentique Zenit 12XP bon état", 10.0)] + older(1007), 2: older(980)}
        client = FakeClient(pages, {1010: {"status": "sold", "price": 45.0},
                                    1012: {"description": "Canon AE-1 Program mit 50mm Objektiv"}})
        r2 = tick.run_tick(store, client, now="2026-10-16 07:22")
        a, c = store.load_active(), store.load_closed()
        assert r2["run"]["new_list"] == 1 and r2["run"]["new_rest"] == 1 and r2["run"]["bumped"] == 2, r2["run"]
        assert r2["run"]["bumped_list"] == 1 and a[400]["flags"] == ["bumped"] and a[400]["model"] == "Zenit 12XP"
        assert 500 not in a, "bumped non-list listings are not tracked"
        assert c[1010]["status"] == "sold" and c[1010]["time_to_sell_max"] is None, "preexisting: no max"
        assert a[1012]["group"] == "list" and a[1012]["model"] == "Canon AE-1 Program", a[1012]["model"]
        assert a[1012]["model_source"] == "description" and a[1012]["kit"] == "with_lens"
        assert a[1011]["listed_after"] == "2026-10-16 07:07"

        # Tick 3: FM2 vanished -> reserved.
        pages[1] = [p for p in pages[1] if p["id"] not in (1011, 400)]
        client = FakeClient(pages, {1011: {"status": "reserved"}, 400: {"status": "sold", "price": 10.0}})
        tick.run_tick(store, client, now="2026-10-16 07:37")
        assert store.load_active()[1011]["status"] == "reserved"

        # Tick 4 (3 h later, no full scan): FM2 sold, preexisting rest item closed after 3 h.
        client = FakeClient(pages, {1011: {"status": "sold", "price": 140.0, "favourites": 7}})
        r4 = tick.run_tick(store, client, now="2026-10-16 10:30")
        c = store.load_closed()
        assert not r4["run"]["full_scan"]
        assert c[1011]["status"] == "sold" and c[1011]["time_to_sell_min"] == 0 and c[1011]["time_to_sell_max"] == 203
        assert c[1011]["price_final"] == 140.0
        assert c[1011]["favourites"] == 7 and c[1011]["favourites_history"][-1]["count"] == 7
        assert c[1009]["status"] == "unsold_3h"

        # Tick 5: next morning -> full scan, new items flagged night, daily exports.
        pages[1] = [rec(1020, "Olympus OM-1 analog", 120.0), rec(1021, "Zenit-E Kamera", 15.0)] + pages[1]
        r5 = tick.run_tick(store, FakeClient(pages), now="2026-10-17 07:07")
        a = store.load_active()
        assert r5["run"]["full_scan"] and r5["daily"] and "night" in a[1020]["flags"]
        assert (store.root / "listings.csv").exists() and (store.root / "README.md").exists()

        # Manual label beats everything.
        tick.run_tick(store, FakeClient(pages), labels={1020: "olympus om1n"}, now="2026-10-17 07:22")
        a = store.load_active()
        assert a[1020]["model"] == "Olympus OM-1n" and a[1020]["model_source"] == "manual"

        # Broken catalog: fatal, state keeps the last good tick.
        class Broken(FakeClient):
            def catalog_page(self, page):
                raise tick.BlockedError("http 403")
        r6 = tick.run_tick(store, Broken({}), now="2026-10-17 07:37")
        assert r6["fatal"] and store.load_state()["last_tick_at"] == "2026-10-17 07:22"

        # Sheets: headers, runs row under a pre-existing test row, list and summary sheets.
        ss = FakeSpreadsheet()
        writer = sheets.SheetWriter(ss)
        updates = tick.write_sheets(writer, r5, {})
        assert updates["runs_header"] and "Zenit E" in updates["models_offered"]
        assert len(ss.formats) == 5 and set(updates["status_colors"]) == {"Список", "Остальные", "До 20 €", "Быстрые продажи"}
        blue = ss.formats[-1]["addConditionalFormatRule"]
        assert updates["new_rows_color"] and blue["index"] == 1, "below the green status rule"
        letter = sheets.column_letter(len(report.ITEM_HEADER))
        assert blue["rule"]["booleanRule"]["condition"]["values"][0]["userEnteredValue"] == f'=${letter}2="да"'
        list_rows = ss.sheets["Список"].rows
        assert list_rows[0][-1] == report.NEW_HEADER and len(list_rows[0]) == len(report.ITEM_HEADER) + 1
        marked = {r[0] for r in list_rows[1:] if r[-1] == "да"}
        assert marked == {1020, 1021}, marked  # new listings first seen 17.10 07:07; bumped 400 and older ones are not
        rule = ss.formats[0]["addConditionalFormatRule"]["rule"]
        assert rule["booleanRule"]["condition"]["values"][0]["userEnteredValue"] == "активен"
        assert rule["ranges"][0]["startColumnIndex"] == report.ITEM_HEADER.index("Статус")
        runs = ss.sheets["Запуски"].rows
        assert runs[0] == sheets.RUNS_HEADER and runs[1][1] == "check-setup" and len(runs) == 3
        assert ss.sheets["Список"].rows[0][0] == "id" and len(ss.sheets["Список"].rows) >= 4
        assert ss.sheets["Модели"].rows[0] == sheets.MODELS_HEADER and len(ss.sheets["Модели"].rows) > 150
        assert ss.sheets["Сводка"].rows[0][0] == "Обновлено"
        assert "Остальные" in ss.sheets
        fast = ss.sheets["Быстрые продажи"].rows
        assert fast[0][-2:] == ["Группа", "Уверенность"], fast[0]
        assert [r[0] for r in fast[1:]] == [1011, 400] and fast[1][-1] == "возможно", "reserved fast, sold 3 h later"
        assert fast[2][-1] == "точно" and "bumped" in fast[2][report.ITEM_HEADER.index("Флаги")], "bumped, sold in 15 min"
        assert all(r[0] != 1010 for r in fast[1:]), "preexisting sale is not fast"
        cheap = ss.sheets["До 20 €"].rows
        assert cheap[0][-1] == "Группа" and [r[0] for r in cheap[1:]] == [1021, 400], cheap[1:]
        # 'До 20 €' follows 'Модели': the user deletes Zenit E, it leaves 'До 20 €' and is not re-added.
        models_ws = ss.sheets["Модели"]
        models_ws.rows = [r for r in models_ws.rows if r[0] != "Zenit E"]
        state_flags = {"runs_header": True, "models_offered": updates["models_offered"],
                       "status_colors": updates["status_colors"], "new_rows_color": True}
        assert tick.write_sheets(writer, r5, state_flags) == {}
        assert [r[0] for r in ss.sheets["До 20 €"].rows[1:]] == [400] and ["Zenit E"] not in [r[:1] for r in models_ws.rows]
        # A model new to the dictionary is offered once; spelling in the sheet does not matter.
        models_ws.rows.append(["зенит-е"])
        offered = [m for m in updates["models_offered"] if m != "Zenit KM"]
        models_ws.rows = [r for r in models_ws.rows if r[0] != "Zenit KM"]
        upd = tick.write_sheets(writer, r5, {"runs_header": True, "models_offered": offered,
                                             "status_colors": updates["status_colors"], "new_rows_color": True})
        assert "Zenit KM" in upd["models_offered"] and models_ws.rows[-1][0] == "Zenit KM"
        assert [r[0] for r in ss.sheets["До 20 €"].rows[1:]] == [1021, 400], "Cyrillic 'зенит-е' matches Zenit E"

        # Dictionary version change re-classifies active items, manual labels stay.
        state = store.load_state()
        state["models_version"] = 1
        store.save_state(state)
        item = tick.new_item(rec(1031, "Kamera analog", 30.0), "2026-10-17 07:37", "2026-10-17 07:22", [])
        item["title"] = "Vintage Zenit TTL Spiegelreflexkamera"  # as if the dictionary was older
        store.save(item)
        r7 = tick.run_tick(store, FakeClient(pages), labels={1020: "olympus om1n"}, now="2026-10-17 07:52")
        a = store.load_active()
        assert r7["models_updated"] and a[1031]["model"] == "Zenit TTL" and a[1031]["group"] == "list"
        assert a[1020]["model_source"] == "manual"
        print("log:", tick.log_line(r4["run"]))
    # Search for older cheap list cameras: half a year limit, list models only.
    Z12, ZE, PRIMA, ANCIENT = 9_000_000_300, 9_000_000_301, 9_000_000_302, 8_000_000_303
    with tempfile.TemporaryDirectory() as tmp:
        store = DataStore(tmp)
        base = {1: [rec(10_000_002_000, "Kamera", 30.0)] + older(10_000_001_999)}
        tick.run_tick(store, FakeClient(base), now="2026-10-18 08:07")
        search = {("zenit", 1): [rec(Z12, "Zenit 12 XP", 20.0), rec(ZE, "Zenit E", 5.0), rec(PRIMA, "Canon Prima", 10.0),
                                 rec(ANCIENT, "Zenit TTL", 8.0)]}
        pages_age = {Z12: {"uploaded_ago": "5 Monaten"}, ZE: {"uploaded_ago": "7 Monaten"}}
        r = tick.run_tick(store, FakeClient(base, pages_age, search), now="2026-10-18 08:22")
        assert r["run"]["search_candidates"] == 2 and r["run"]["found"] == 0, r["run"]
        assert r["run"]["search_skipped"] == 1, "an id far below the half-year mark is skipped without opening"
        client = FakeClient(base, pages_age, search)
        r = tick.run_tick(store, client, now="2026-10-18 08:37")
        a = store.load_active()
        assert r["run"]["found"] == 1 and r["run"]["search_skipped"] == 1 and ANCIENT not in client.opened, r["run"]
        assert a[Z12]["flags"] == ["found"] and a[Z12]["uploaded_ago"] == "5 Monaten" and ZE not in a and PRIMA not in a
        assert [i["id"] for i in report.cheap_cameras(r["items"], 20.0)] == [Z12]
        assert report.fast_confidence({**a[Z12], "status": "sold", "time_to_sell_min": 0}) is None
        for minute in range(52, 52 + 15 * 10, 15):  # finish the daily cheap pass over all brands
            now = f"2026-10-18 {9 + minute // 60:02d}:{minute % 60:02d}"
            tick.run_tick(store, FakeClient(base, pages_age, search), now=now)
        assert store.load_state()["search"]["done_on"] == "2026-10-18"

    # Model pass at any price: found -> missing from its model's results -> checked -> sold.
    sweep = tick.Sweep("t", (("canon ae-1", "Canon AE-1"), ("nikon f2", "Nikon F2")), None, 10, 1, 16, False, True)
    AE1 = 9_875_831_290
    state, active, closed, stats, changed = {}, {}, {}, Counter(), set()
    client = FakeClient({}, {AE1: {"uploaded_ago": "6 Wochen", "price": 140.0}},
                        {("canon ae-1", 1): [rec(AE1, "Canon AE-1 Set", 140.0)]})
    tick.search_sweep(sweep, state, client, active, closed, "2026-10-18 10:07", "2026-10-18", stats, changed)
    tick.search_sweep(sweep, state, client, active, closed, "2026-10-18 10:22", "2026-10-18", stats, changed)
    assert AE1 in active and active[AE1]["model"] == "Canon AE-1" and "found" in active[AE1]["flags"]
    assert tick.check_priority(active[AE1], "2026-10-19 10:22", vanished=False) is None, "seen: no daily check"
    client.search = {}  # next pass: the AE-1 is gone from its results
    for now in ("2026-10-19 10:07", "2026-10-19 10:22"):
        tick.search_sweep(sweep, state, client, active, closed, now, "2026-10-19", stats, changed)
    assert active[AE1].get("needs_check") and stats["found_missing"] == 1
    assert tick.check_priority(active[AE1], "2026-10-19 10:37", vanished=False) == tick.P_FOUND
    tick.apply_page(active[AE1], {"status": "sold", "price": 130.0, "description": None, "favourites": 4}, "2026-10-19 10:37")
    assert active[AE1]["status"] == "sold" and "needs_check" not in active[AE1]
    # Over a month on Vinted ('6 Wochen'): checked every 3 days; a younger one daily.
    old = {**active[AE1], "status": "active", "closed_at": None, "last_checked_at": "2026-10-19 10:37"}
    assert active[AE1]["vinted_listed_est"] == "2026-09-06" and active[AE1]["uploaded_ago"] == "6 Wochen"
    assert tick.check_priority(old, "2026-10-21 10:38", vanished=False) is None
    assert tick.check_priority(old, "2026-10-22 10:38", vanished=False) == tick.P_FOUND
    young = {**old, "vinted_listed_est": "2026-10-10"}
    assert tick.check_priority(young, "2026-10-20 10:38", vanished=False) == tick.P_FOUND

    # Old cheap camera: a search sighting does not postpone its check; the daily
    # cheap pass flags it when it drops out of its brand's results.
    cheap = tick.Sweep("c", (("zenit", None), ("fed", None)), 20, 4, 1, 4, True, True)
    ZET = 10_134_306_267
    state, active, closed, stats, changed = {}, {}, {}, Counter(), set()
    client = FakeClient({}, {ZET: {"uploaded_ago": "2 Wochen", "price": 10.0}},
                        {("zenit", 1): [rec(ZET, "Zenit ET appareil photo", 10.0)]})
    for now in ("2026-10-16 00:04", "2026-10-16 00:19", "2026-10-16 00:34"):
        tick.search_sweep(cheap, state, client, active, closed, now, "2026-10-16", stats, changed)
    assert ZET in active and active[ZET]["last_checked_at"] == "2026-10-16 00:19", "found and checked at 00:19"
    state["c"]["done_on"] = None
    tick.search_sweep(cheap, state, client, active, closed, "2026-10-16 08:07", "2026-10-16", stats, changed)
    assert active[ZET]["last_seen_active"] == "2026-10-16 08:07" and active[ZET]["last_checked_at"] == "2026-10-16 00:19"
    tick.search_sweep(cheap, state, client, active, closed, "2026-10-16 08:22", "2026-10-16", stats, changed)  # 'fed'
    assert not active[ZET].get("needs_check")
    client.search = {}  # sold: gone from search
    for now in ("2026-10-17 07:22", "2026-10-17 07:37"):
        tick.search_sweep(cheap, state, client, active, closed, now, "2026-10-17", stats, changed)
    assert active[ZET].get("needs_check"), "missing from the daily cheap pass -> checked next"

    # A list camera closed as 'unsold in 3 h' is reopened and checked.
    with tempfile.TemporaryDirectory() as tmp:
        store = DataStore(tmp)
        base = {1: [rec(10_000_002_000, "Kamera", 30.0)] + older(10_000_001_999)}
        tick.run_tick(store, FakeClient(base), now="2026-10-16 08:07")
        zen = tick.new_item(rec(9_900_000_001, "Zenit TTL", 15.0), "2026-10-15 22:00", None, ["preexisting"])
        zen.update(group="list", status="unsold_3h", closed_at="2026-10-16 01:05")
        store.save(zen)
        assert store.load_closed()[zen["id"]]["status"] == "unsold_3h"
        client = FakeClient(base, {zen["id"]: {"status": "active", "price": 15.0, "uploaded_ago": "3 Wochen"}})
        r = tick.run_tick(store, client, now="2026-10-16 08:22")
        a, c = store.load_active(), store.load_closed()
        assert r["run"]["reopened"] == 1 and zen["id"] in client.opened, r["run"]
        assert zen["id"] in a and zen["id"] not in c and a[zen["id"]]["status"] == "active" and not a[zen["id"]].get("needs_check")

    assert sheets.column_letter(0) == "A" and sheets.column_letter(25) == "Z" and sheets.column_letter(26) == "AA"
    assert report.is_new({"first_seen": "2026-10-16 20:00", "flags": ["night"]}, "2026-10-16 09:00")
    assert not report.is_new({"first_seen": "2026-10-16 20:00", "flags": ["found"]}, "2026-10-16 09:00")
    assert not report.is_new({"first_seen": "2026-10-16 08:00", "flags": []}, "2026-10-16 09:00")

    # 'Продали за': days for new listings, Vinted's date for old ones, months past 30 days.
    assert [report.format_days(d) for d in (None, 0.4, 1, 3.9, 5, 21, 30, 45, 62, 150)] == [
        "", "меньше дня", "1 день", "3 дня", "5 дней", "21 день", "30 дней", "2 месяца", "2 месяца", "5 месяцев"]
    new = {"status": "sold", "listed_after": "2026-10-16 10:07", "sold_detected_at": "2026-10-19 10:37", "flags": []}
    old = {"status": "sold", "listed_after": None, "vinted_listed_est": "2026-06-01",
           "last_seen_active": "2026-10-17 10:37", "sold_detected_at": "2026-10-19 10:37", "flags": ["found"]}
    assert report.days_to_sell(old) == 139.44, "middle of [last seen, detected] = 18.10 10:37"
    assert report.days_to_sell(new) == 3.02 and report.format_days(report.days_to_sell(old)) == "5 месяцев"
    assert report.days_to_sell({**new, "status": "active"}) is None

    # 'До 20 €' includes exactly 20 EUR.
    at = lambda price, group="list", flags=(): {"price_history": [{"at": "x", "price": price}], "group": group,
                                                "flags": list(flags)}
    assert len(report.cheap_cameras([at(20.0), at(19.99), at(20.01)], 20.0)) == 2
    assert not report.cheap_cameras([at(10.0, flags=["accessory?"]), at(10.0, group="rest")], 20.0),         "accessories and rest rows are not in 'До 20 €'"
    print("tick tests passed")


if __name__ == "__main__":
    main()
