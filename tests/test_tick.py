"""Tick logic on a fake Vinted and a fake spreadsheet. Run: python -m tests.test_tick"""
import tempfile

from tracker import tick
from tracker.store import DataStore


def rec(item_id, title, price=50.0, brand=None, promoted=False):
    return {"id": item_id, "title": title, "url": f"https://www.vinted.de/items/{item_id}", "price": price,
            "brand": brand, "condition": "Gut", "seller_id": 1, "promoted": promoted}


class FakeClient:
    def __init__(self, pages, item_pages=None):
        self.pages, self.item_pages = pages, item_pages or {}
        self.requests_made, self.bytes_received, self.opened = 0, 0, []

    def catalog_page(self, page):
        self.requests_made += 1
        return self.pages.get(page, [])

    def item_page(self, item_id):
        self.requests_made += 1
        self.opened.append(item_id)
        base = {"status": "active", "price": None, "description": None}
        return {**base, **self.item_pages.get(item_id, {})}


class FakeWorksheet:
    def __init__(self, title):
        self.title, self.rows, self.size = title, [], (0, 0)

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
                     rec(1009, "Polaroid Kamera", 10.0), rec(500, "Bumped old", 30.0)] + older(1007), 2: older(980)}
        client = FakeClient(pages, {1010: {"status": "sold", "price": 45.0},
                                    1012: {"description": "Canon AE-1 Program mit 50mm Objektiv"}})
        r2 = tick.run_tick(store, client, now="2026-10-16 07:22")
        a, c = store.load_active(), store.load_closed()
        assert r2["run"]["new_list"] == 1 and r2["run"]["new_rest"] == 1 and r2["run"]["bumped"] == 1, r2["run"]
        assert c[1010]["status"] == "sold" and c[1010]["time_to_sell_max"] is None, "preexisting: no max"
        assert a[1012]["group"] == "list" and a[1012]["model"] == "Canon AE-1 Program", a[1012]["model"]
        assert a[1012]["model_source"] == "description" and a[1012]["kit"] == "with_lens"
        assert a[1011]["listed_after"] == "2026-10-16 07:07"

        # Tick 3: FM2 vanished -> reserved.
        pages[1] = [p for p in pages[1] if p["id"] != 1011]
        client = FakeClient(pages, {1011: {"status": "reserved"}})
        tick.run_tick(store, client, now="2026-10-16 07:37")
        assert store.load_active()[1011]["status"] == "reserved"

        # Tick 4 (3 h later, no full scan): FM2 sold, preexisting rest item closed after 3 h.
        client = FakeClient(pages, {1011: {"status": "sold", "price": 140.0}})
        r4 = tick.run_tick(store, client, now="2026-10-16 10:30")
        c = store.load_closed()
        assert not r4["run"]["full_scan"]
        assert c[1011]["status"] == "sold" and c[1011]["time_to_sell_min"] == 0 and c[1011]["time_to_sell_max"] == 203
        assert c[1011]["price_final"] == 140.0
        assert c[1009]["status"] == "unsold_3h"

        # Tick 5: next morning -> full scan, new items flagged night, daily exports.
        pages[1] = [rec(1020, "Olympus OM-1 analog", 120.0)] + pages[1]
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
        tick.write_sheets(writer, r5, {})
        runs = ss.sheets["Запуски"].rows
        assert runs[0] == sheets.RUNS_HEADER and runs[1][1] == "check-setup" and len(runs) == 3
        assert ss.sheets["Список"].rows[0][0] == "id" and len(ss.sheets["Список"].rows) >= 4
        assert ss.sheets["Модели"].rows[0] == sheets.MODELS_HEADER and len(ss.sheets["Модели"].rows) > 150
        assert ss.sheets["Сводка"].rows[0][0] == "Обновлено"
        assert "Остальные" in ss.sheets
        cheap = ss.sheets["До 20 €"].rows
        assert cheap[0][-1] == "Группа" and any(r[0] == 1009 for r in cheap[1:]), "10 EUR item in 'До 20 €'"
        assert not any(r[0] == 1010 for r in cheap[1:]), "45 EUR item not in 'До 20 €'"
        # 'Модели' exists and was edited by the user: only missing models are appended.
        models_ws = ss.sheets["Модели"]
        models_ws.rows = models_ws.rows[:-3] + [["Моя заметка"]]
        assert writer.ensure_models() == 3 and ["Моя заметка"] in models_ws.rows

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
    print("tick tests passed")


if __name__ == "__main__":
    main()
