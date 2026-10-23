"""Tick logic on a fake Vinted and a fake spreadsheet. Run: python -m tests.test_tick"""
import json
import tempfile
import time
from collections import Counter
from pathlib import Path

from tracker import models, report, tick
from tracker.store import DataStore


def rec(item_id, title, price=50.0, brand=None, promoted=False):
    return {"id": item_id, "title": title, "url": f"https://www.vinted.de/items/{item_id}", "price": price,
            "brand": brand, "condition": "Gut", "seller_id": 1, "promoted": promoted, "favourites": 0}


class FakeClient:
    def __init__(self, pages, item_pages=None, search=None):
        self.pages, self.item_pages, self.search = pages, item_pages or {}, search or {}
        self.requests_made, self.bytes_received, self.opened = 0, 0, []

    def cheap_page(self, max_price):
        self.requests_made += 1
        return self.pages.get("cheap", [])

    def fresh_page(self, text, page=1):
        self.requests_made += 1
        return self.search.get((text, "fresh") if page == 1 else (text, "fresh", page), [])

    def search_page(self, text, page, max_price):
        self.requests_made += 1
        return self.search.get((text, page), [])

    def catalog_page(self, page, category=3076):
        self.requests_made += 1
        return self.pages.get(page if category == 3076 else (category, page), [])

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
        self.mode, self.sent = value_input_option, values
        if value_input_option == "USER_ENTERED":  # Sheets keeps the text, hides the apostrophe
            values = [[c[1:] if isinstance(c, str) and c.startswith("'") else c for c in r] for r in values]
        if len(values) == 1 and self.rows:  # header row only
            self.rows[0] = list(values[0])
        else:
            self.rows = [list(r) for r in values]

    def resize(self, rows=None, cols=None):
        self.size = (rows if rows is not None else self.size[0], cols if cols is not None else self.size[1])

    @property
    def row_count(self):
        return self.size[0]

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

    def get_values(self, value_render_option=None):
        return [list(r) for r in self.rows]

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
        self.rules = getattr(self, "rules", {})
        for req in body["requests"]:
            if "addConditionalFormatRule" in req:
                add = req["addConditionalFormatRule"]
                sid = add["rule"]["ranges"][0]["sheetId"]
                self.rules.setdefault(sid, []).insert(add["index"], add["rule"])
            elif "updateConditionalFormatRule" in req:
                upd = req["updateConditionalFormatRule"]
                self.rules[upd["sheetId"]][upd["index"]] = upd["rule"]

    def fetch_sheet_metadata(self, params=None):
        rules = getattr(self, "rules", {})
        return {"sheets": [{"properties": {"sheetId": ws.id, "title": ws.title},
                            "conditionalFormats": rules.get(ws.id, [])} for ws in self.sheets.values()]}

    def add_worksheet(self, title, rows, cols):
        self.sheets[title] = FakeWorksheet(title)
        return self.sheets[title]

    def del_worksheet(self, ws):
        del self.sheets[ws.title]


def older(start, n=20):
    return [rec(start - k, f"Kamera alt {k}", 20.0) for k in range(n)]


def main():
    from tracker import sheets

    with tempfile.TemporaryDirectory() as tmp:
        store = DataStore(tmp)
        # Tick 1: first run, full scan; everything is preexisting.
        pages = {1: [rec(1010, "Canon AE-1 Kamera"), rec(1009, "Agfa Silette Kamera", 10.0), rec(1008, "Agfa", 2.0)]
                 + older(1007), 2: older(980)}
        r1 = tick.run_tick(store, FakeClient(pages), now="2026-10-16 07:07")
        a = store.load_active()
        assert r1["run"]["full_scan"] and r1["run"]["pages"] == 2, r1["run"]
        assert 1008 not in a, "rest under 3 EUR must not be tracked"
        assert a[1010]["group"] == "list" and "preexisting" in a[1010]["flags"]
        assert r1["daily"]

        # Tick 2: two new items; the list camera vanished and is sold.
        pages = {1: [rec(1012, "Kamera Canon", 40.0), rec(1011, "Nikon FM2 body", 150.0),
                     rec(1009, "Agfa Silette Kamera", 10.0), rec(500, "Bumped old", 30.0),
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

        # Manual label beats everything. A labelled id the tracker never saw (the model only in the
        # photos) is opened and tracked; 'не камера' is not; a page that fails is retried later.
        client = FakeClient(pages, {5555: {"title": "Analoge Spiegelreflex Kamera", "price": 80.0, "brand": "Canon",
                                           "uploaded_ago": "2 Monaten", "description": "gepflegte Analogkamera"},
                                    5557: {"status": "unknown"}})
        labels = {1020: "olympus om1n", 5555: "Canon AE-1", 5556: "не камера", 5557: "Nikon FM"}
        r_lab = tick.run_tick(store, client, labels=labels, now="2026-10-17 07:22")
        a = store.load_active()
        assert a[1020]["model"] == "Olympus OM-1n" and a[1020]["model_source"] == "manual"
        assert a[5555]["model"] == "Canon AE-1" and a[5555]["model_source"] == "manual" and a[5555]["group"] == "list"
        assert a[5555]["flags"] == ["found"] and a[5555]["vinted_listed_est"] and a[5555]["price_start"] == 80.0
        assert 5556 not in client.opened and 5557 not in a and store.load_state()["labelled_tries"] == {"5557": 1}
        assert r_lab["run"]["labelled"] == 1 and "Canon AE-1 — 80 € (разметка), id 5555" in r_lab["run"]["added"], r_lab["run"]["added"]

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
        assert updates["runs_header_v5"] and "Zenit E" in updates["models_offered"]
        assert set(updates["status_colors"]) == {"Список", "Остальные", "До 20 €", "Быстрые продажи"}
        rules = [f["addConditionalFormatRule"] for f in ss.formats]
        assert len(rules) == 8, len(rules)  # 4 green + blue and yellow on 2 sheets
        n = len(report.ITEM_HEADER)

        def added(color):
            return [(r["index"], r["rule"]["booleanRule"]["condition"]["values"][0]["userEnteredValue"])
                    for r in rules if r["rule"]["booleanRule"]["format"]["backgroundColor"] == color]
        L = sheets.column_letter
        assert added(sheets.LIGHT_BLUE_3) == [(1, f'=${L(n)}2="да"'), (1, f'=${L(n + 1)}2="да"')]
        assert [f for f in added(sheets.LIGHT_GREEN_3) if f[1].startswith("=")] == [
            (1, f'=${L(n + 1)}2="да"'), (1, f'=${L(n + 2)}2="да"')], "3-hour rows: light green 3"
        list_rules = ss.rules[ss.sheets["Список"].id]
        assert [r["booleanRule"]["format"]["backgroundColor"] for r in list_rules] == [
            sheets.LIGHT_GREEN_3, sheets.LIGHT_GREEN_3, sheets.LIGHT_BLUE_3], "status, 3 h above 12 h"
        assert updates["fresh_rows_green"] and not added(sheets.LIGHT_YELLOW_3)
        assert updates["new_rows_colors"] == updates["fresh_rows_colors"] == ["До 20 €", "Список"]
        cheap_rows = ss.sheets["До 20 €"].rows
        assert cheap_rows[0][-3:] == ["Группа", report.NEW_HEADER, report.FRESH_HEADER]
        assert {r[0] for r in cheap_rows[1:] if r[-2] == "да"} == {1021} and {r[0] for r in cheap_rows[1:] if r[-1] == "да"} == {1021}
        assert 400 in {r[0] for r in ss.sheets["Список"].rows[1:]} and "https://www.vinted.de/items/400" in {r[-1] for r in ss.sheets["Продажи"].rows[1:]}
        list_rows = ss.sheets["Список"].rows
        assert list_rows[0][-2:] == [report.NEW_HEADER, report.FRESH_HEADER] and len(list_rows[0]) == n + 2
        marked = {r[0] for r in list_rows[1:] if r[-2] == "да"}
        assert marked == {1020, 1021}, marked  # new listings first seen 17.10 07:07; bumped 400 and older ones are not
        assert {r[0] for r in list_rows[1:] if r[-1] == "да"} == {1020, 1021}, "07:07 is within 3 h of the 07:07 tick"
        rule = ss.formats[0]["addConditionalFormatRule"]["rule"]
        assert rule["booleanRule"]["condition"]["values"][0]["userEnteredValue"] == "активен"
        assert rule["ranges"][0]["startColumnIndex"] == report.ITEM_HEADER.index("Статус")
        runs = ss.sheets["Запуски"].rows
        assert runs[0] == sheets.RUNS_HEADER and runs[1][1] == "check-setup" and len(runs) == 3
        assert updates["runs_header_v5"] and runs[2][1] == 0, "first tick: nothing counted as new in 'До 20 €'"
        assert updates["cheap_ids"] == [1021]
        # Links clickable, other text kept literal.
        fast_ws = ss.sheets["Быстрые продажи"]
        link_col = report.ITEM_HEADER.index("Ссылка")
        assert fast_ws.mode == "USER_ENTERED" and fast_ws.rows[1][link_col].startswith("https://")
        status_col = report.ITEM_HEADER.index("Статус")
        assert fast_ws.sent[1][status_col] == "'продан" and fast_ws.rows[1][status_col] == "продан"
        assert fast_ws.rows[1][0] == 1011 and fast_ws.sent[1][link_col] == fast_ws.rows[1][link_col]
        assert ss.sheets["Сводка"].mode == "RAW" and ss.sheets["Проверка"].rows[0] == report.CHECK_HEADER
        assert ss.sheets["Список"].rows[0][0] == "id" and len(ss.sheets["Список"].rows) >= 4
        assert ss.sheets["Модели"].rows[0] == sheets.MODELS_HEADER and len(ss.sheets["Модели"].rows) > 150
        assert ss.sheets["Сводка"].rows[0][0] == "Обновлено"
        assert ss.sheets["Топ-10"].rows[2][0] == "Топ-10: чаще всего продаются", ss.sheets["Топ-10"].rows[:4]
        assert ss.sheets["Аналитика"].rows[0][0] == "Обновлено" and ss.sheets["Аналитика"].mode == "RAW"
        # Photo labels (trial): a sheet with the photo as a formula, nothing else becomes one.
        from tracker import photos
        photo = "https://images1.vinted.net/t/abc/f800/123.jpeg"
        labelled = {"id": 7, "group": "rest", "status": "active", "title": "Appareil photo", "photo": photo,
                    "price_start": 20.0, "price_history": [], "first_seen": "2026-10-17 10:00", "url": "u",
                    "photo_label": {"verdict": ["list", "Zenit 122", "надпись"], "similar": "model:Zenit E",
                                    "ocr": "ZENIT 122", "at": "2026-10-17 10:05"}}
        dropped = dict(labelled, id=9, photo_label={"verdict": ["drop", "compact"], "at": "x"})
        kept_older = dict(labelled, id=10, first_seen="2026-10-18 10:00", photo_label={"verdict": ["keep"], "at": "x"})
        both = [labelled, dict(labelled, id=8, photo_label=None), dropped, kept_older]
        prow = report.photo_rows(both, dropped=False)
        assert [r[-2] for r in prow[1:]] == [7, 10], "kept: the ones for 'Список' on top, then newest first"
        assert prow[1][:3] == [f'=IMAGE("{photo}")', "", "в «Список»: Zenit 122 (по надписи)"], prow
        assert [r[-2] for r in report.photo_rows(both, dropped=True)[1:]] == [9]
        fs = FakeSpreadsheet()
        fs.sheets[sheets.OLD_PHOTO_SHEET] = FakeWorksheet(sheets.OLD_PHOTO_SHEET)
        fw = sheets.SheetWriter(fs)
        fw.delete(sheets.OLD_PHOTO_SHEET)
        assert sheets.OLD_PHOTO_SHEET not in fs.sheets and not fw.has(sheets.OLD_PHOTO_SHEET)
        assert sheets._as_typed(prow[1][0]) == prow[1][0] and sheets._as_typed('=HYPERLINK("x")').startswith("'")
        assert photos.image_formula('https://images1.vinted.net/a"),HYPERLINK("x') == "" and photos.image_formula("http://x") == ""
        assert photos.verdict_text({"verdict": ["drop", "compact"]}) == "убрать: compact"
        tick.photo_step(DataStore(tempfile.mkdtemp()), {"items": [labelled]}, time.monotonic())  # no gallery: off
        # Drops leave the data with a short record; outside verdicts replace earlier ones; manual labels stay.
        root = Path(tempfile.mkdtemp())
        assert photos.is_dropped(dropped) and not photos.is_dropped(labelled)
        assert not photos.is_dropped(dict(dropped, model_source="manual")) and not photos.is_dropped(dict(dropped, group="list"))
        photos.record_drops(root, [dropped])
        photos.record_drops(root, [dict(dropped, id=11), dropped])
        assert [r["id"] for r in photos.dropped_records(root)] == [11, 9]
        assert [r[-2] for r in report.photo_rows(photos.dropped_records(root), dropped=True)[1:]] == [11, 9]
        (root / photos.BACKFILL_FILE).write_text(json.dumps({"7": {"verdict": ["drop", "compact"]}}), encoding="utf-8")
        state, cards = {}, [dict(labelled)]
        assert photos.apply_backfill(root, cards, state) == cards and cards[0]["photo_label"]["verdict"] == ["drop", "compact"]
        assert photos.apply_backfill(root, cards, state) == [], "once per file"
        # Exact names outside the list; a list model read on the photo moves the card to 'Список';
        # near models of the list go to 'Братья моделей списка'.
        named = [dict(labelled, id=21, title="Bellissima macchina fotografica minolta x300s", photo_label={"verdict": ["keep"]}),
                 dict(labelled, id=22, title="Appareil photo", photo_label={"verdict": ["keep"], "ocr": "ZENIT 122"},
                      closed_at="2026-10-17 13:00", status="unsold_3h"),
                 dict(labelled, id=23, title="Appareil photo", photo_label={"verdict": ["keep"], "ocr": "xx"})]
        counts = tick.name_step(DataStore(tempfile.mkdtemp()), {"items": named})
        assert counts["named"] == 2 and counts["unnamed"] == 1 and counts["to_list"] == 1, counts
        assert named[0]["camera_name"] == "Minolta X300S" and named[0]["camera_name_source"] == "title"
        assert named[1]["model"] == "Zenit 122" and named[1]["model_source"] == "photo" and named[1]["group"] == "list"
        assert report.item_row(named[0])[1] == "Minolta X300S" and "название" in report.item_row(named[0])[report.ITEM_HEADER.index("Источник модели")]
        sib = report.sibling_rows(named)
        assert [r[1] for r in sib[1:]] == ["Minolta X300S"] and "Minolta X-700" in sib[1][2], sib
        # No name from the first photo: the 2nd/3rd photos are read; still nothing -> the manual sheet.
        more = [dict(labelled, id=31, title="Kamera", photo_label={"verdict": ["keep"]}, name_tried="t",
                     photo_more_ocr="CHINON CE-4 | x", photos_more=[photo, photo]),
                dict(labelled, id=32, title="Kamera", photo_label={"verdict": ["keep"], "similar": "model:Zenit E"},
                     name_tried="t", photo_more_ocr="", photos_more=[photo])]
        assert [i["id"] for i in photos.more_photo_candidates(more + [dict(labelled, id=33, title="Kamera",
                photo_label={"verdict": ["keep"]})])] == [33], "tried once"
        tick.name_step(DataStore(tempfile.mkdtemp()), {"items": more})
        assert more[0]["camera_name"] == "Chinon CE-4" and more[0]["camera_name_source"] == "more_photos"
        unnamed = report.unnamed_rows(more)
        assert [r[-2] for r in unnamed[1:]] == [32] and unnamed[1][1] == f'=IMAGE("{photo}")' and unnamed[1][2] == ""
        assert unnamed[1][3] == "Zenit E"
        # Each card on one sheet: named outside the list -> 'Предложение' (the most frequent model first),
        # near a list model -> 'Братья', tried without a name -> 'без названия', the rest -> 'оставить'.
        cards = [dict(labelled, id=41, camera_name="Chinon CE-4", first_seen="2026-10-17 09:00"),
                 dict(labelled, id=42, camera_name="Agfa Selecta", first_seen="2026-10-17 11:00"),
                 dict(labelled, id=43, camera_name="Chinon CE-4", first_seen="2026-10-17 12:00"),
                 dict(labelled, id=44, camera_name="Minolta X-300"),
                 dict(labelled, id=45, name_tried="t"), dict(labelled, id=46)]
        prop = report.proposal_rows(cards)
        assert [(r[1], r[2], r[-2]) for r in prop[1:]] == [("Chinon CE-4", 2, 43), ("Chinon CE-4", 2, 41),
                                                           ("Agfa Selecta", 1, 42)], prop
        assert [r[-2] for r in report.sibling_rows(cards)[1:]] == [44]
        assert [r[-2] for r in report.photo_rows(cards, dropped=False)[1:]] == [46]
        # Relists: the same seller and model, the earlier listing taken down unsold before the next one showed up.
        def listing(item_id, status, first, last, price, seller=7, **extra):
            return dict({"id": item_id, "group": "list", "model": "Canon AE-1", "seller_id": seller, "status": status,
                         "flags": [], "price_start": price, "price_final": price if status == "sold" else None,
                         "price_history": [{"at": first, "price": price}], "first_seen": first, "listed_after": first,
                         "last_seen_active": last}, **extra)
        cards = [listing(1, "deleted", "2026-09-01 10:00", "2026-09-10 10:00", 150.0, closed_at="2026-09-11 10:00"),
                 listing(2, "unsold_30d", "2026-09-12 10:00", "2026-10-12 09:00", 140.0, closed_at="2026-10-12 10:00"),
                 listing(3, "sold", "2026-10-13 10:00", "2026-10-14 09:00", 120.0, sold_detected_at="2026-10-14 10:00"),
                 listing(4, "active", "2026-10-01 10:00", "2026-10-17 10:00", 90.0, seller=8),
                 listing(5, "active", "2026-10-05 10:00", "2026-10-17 10:00", 95.0, seller=8)]  # two at once: no chain
        chains = report.relist_chains(cards)
        assert [[i["id"] for i in c] for c in chains] == [[1, 2, 3]], chains
        relisted = dict(zip(report.SALES_HEADER, report.sales_rows(cards)[1]))["Перевыставлялась"]
        assert relisted == "2 раза, на рынке всего 1 месяц, первая цена 150 €", relisted
        analytics = report.analytics_rows(cards, "2026-10-17 12:00")
        assert ["Камер, которые перевыставляли", 1] == next(r for r in analytics if r[0].startswith("Камер, которые"))[:2]
        saves = {"first_seen": "2026-10-17 10:00", "favourites_history": [
            {"at": "2026-10-17 10:00", "count": 0}, {"at": "2026-10-17 10:45", "count": 3}, {"at": "2026-10-17 12:00", "count": 9}]}
        assert report.saves_in_first_hour(saves) == 3
        def sale(item_id, model, price):
            return {"id": item_id, "group": "list", "model": model, "status": "sold", "flags": [], "price_start": price,
                    "price_final": price, "price_history": [{"at": "x", "price": price}], "title": model,
                    "url": f"https://www.vinted.de/items/{item_id}", "first_seen": "2026-10-16 10:00",
                    "sold_detected_at": "2026-10-17 10:00"}
        top = report.top_rows([sale(1, "Canon AE-1", 120.0), sale(2, "Canon AE-1", 100.0), sale(3, "Leica M6", 2500.0),
                               sale(4, "Zenit E", 1.0)], "2026-10-17 12:00")
        heads = [k for k, r in enumerate(top) if r[0].startswith("Топ-10")]
        assert top[heads[0] + 2][:6] == ["Canon AE-1", 2, 2, 100, 110, 110], top[heads[0] + 2]
        assert top[heads[1] + 2][:2] == ["Leica M6", 2500] and top[heads[2] + 2][:2] == ["Leica M6", 2500.0]
        assert all(r[0] != "Zenit E" for r in top), "a 1 EUR placeholder is no sale"
        pricy = next(k for k, r in enumerate(top) if r[0].startswith("Продажи дороже 100"))
        assert [r[:3] for r in top[pricy + 2:pricy + 4]] == [["Leica M6", 1, 2500], ["Canon AE-1", 1, 120]], top[pricy:pricy + 4]
        model_header = next(r for r in ss.sheets["Сводка"].rows if r[0] == "Модель")
        assert model_header[3] == "Средняя цена, €" and model_header[4] == "Средняя цена продажи (> 40 €), €", model_header
        sold = [{"group": "list", "model": "Nikon FM2", "status": "sold", "flags": [], "price_start": p, "price_final": p,
                 "price_history": [{"at": "x", "price": p}], "first_seen": "2026-10-16 10:00"} for p in (30.0, 150.0, 170.0)]
        fm2 = next(m for m in report.summarize(sold, "2026-10-17 10:00")["models"] if m["model"] == "Nikon FM2")
        assert fm2["mean_sale_price"] == 160 and fm2["mean_price"] == 117, fm2
        assert "Остальные" in ss.sheets
        sales = ss.sheets["Продажи"].rows
        ids = [r[-1].rsplit("/", 1)[-1] for r in sales[1:]]
        assert sales[0] == report.SALES_HEADER and len(sales[0]) == 13 and ids == ["1011", "400", "1010"], ids
        fm2 = dict(zip(report.SALES_HEADER, sales[1]))
        assert fm2["Модель"] == "Nikon FM2" and fm2["Цена при продаже, €"] == 140.0 and fm2["История цены, €"] == "150 → 140"
        assert fm2["Изменение цены"] == "−10 € (−7 %)", fm2["Изменение цены"]
        assert fm2["Выставлена"] == "2026-10-16 07:07 – 07:22" and fm2["В продаже"].endswith((" мин", " ч")), fm2
        assert [report.format_on_sale(d) for d in (0.01, 0.3, 3.5, 75, 400, 800)] == [
            "14 мин", "7 ч", "3 дня", "2 месяца", "1 год 1 месяц", "2 года 2 месяца"]
        hanging = [{"status": "active", "flags": ["found"], "vinted_listed_est": "2026-10-07", "first_seen": "2026-10-16 10:00"},
                   {"status": "unsold_30d", "flags": [], "listed_after": "2026-09-16 10:00", "first_seen": "2026-09-16 10:15",
                    "closed_at": "2026-10-16 10:15"}, {"status": "sold", "flags": []}]
        assert [report.unsold_days(i, "2026-10-17 00:00") for i in hanging] == [10.0, 30.01, None]
        assert report.on_sale_text({"status": "sold", "flags": ["preexisting"], "first_seen": "2026-10-15 10:00",
                                    "sold_detected_at": "2026-10-17 12:00"}) == "≥ 2 дня"
        assert all("\n" not in str(c) and len(str(c)) <= 150 for r in sales[1:] for c in r[:-1]), "one line per sale"
        # Placeholder prices: 1 EUR always, a few EUR when the seller waits for offers.
        one = {"price_start": 1.0, "price_history": [{"at": "x", "price": 1.0}], "description": "Accetto offerte"}
        three = {"price_start": 3.0, "price_history": [{"at": "x", "price": 3.0}], "description": "Offen für Angebote"}
        real = {"price_start": 4.0, "price_history": [{"at": "x", "price": 4.0}], "description": "Funktioniert"}
        assert report.placeholder_price(one) and report.placeholder_price(three) and not report.placeholder_price(real)
        assert report.cheap_cameras([dict(one, group="list", status="active", flags=[])], 20) == []
        item = {"kit": "with_lens", "kit_details": ["lens", "flash"], "description": "Canon AE-1\n\n" + "sehr gut " * 30}
        assert report._kit_text(item) == "с объективом: вспышка" and report._one_line(item["description"], 30).endswith("…")
        assert report._change_text(100.0, 100.0) == "" and report._change_text(80.0, 100.0) == "+20 € (+25 %)"
        fast = ss.sheets["Быстрые продажи"].rows
        assert fast[0][-1] == "Уверенность" and "Группа" not in fast[0], fast[0]
        assert [r[0] for r in fast[1:]] == [1011, 400] and fast[1][-1] == "возможно", "reserved fast, sold 3 h later"
        assert fast[2][-1] == "точно" and "bumped" in fast[2][report.ITEM_HEADER.index("Флаги")], "bumped, sold in 15 min"
        assert all(r[0] != 1010 for r in fast[1:]), "preexisting sale is not fast"
        cheap = ss.sheets["До 20 €"].rows
        assert "Группа" in cheap[0] and [r[0] for r in cheap[1:]] == [1021], "sold Zenit 400 is not shown"
        assert cheap[0][6:8] == ["Сохранений", "Ссылка"] and cheap[1][7].startswith("https://"), cheap[0]
        assert cheap[0][report.ITEM_HEADER.index("Статус")] == "Статус" and cheap[0][-2:] == [report.NEW_HEADER, report.FRESH_HEADER]
        # 'До 20 €' follows 'Модели': the user deletes Zenit E, it leaves 'До 20 €' and is not re-added.
        models_ws = ss.sheets["Модели"]
        models_ws.rows = [r for r in models_ws.rows if r[0] != "Zenit E"]
        state_flags = {"runs_header_v5": True,
                       "cheap_ids": updates["cheap_ids"], "models_offered": updates["models_offered"],
                       "status_colors": updates["status_colors"], "new_rows_colors": updates["new_rows_colors"],
                       "fresh_rows_colors": updates["fresh_rows_colors"], "fresh_rows_green": True}
        assert {k: v for k, v in tick.write_sheets(writer, r5, state_flags).items() if k != "models_sheet"} == {"cheap_ids": []}, "Zenit E left 'До 20 €'"
        assert ss.sheets["Запуски"].rows[-1][1] == 0
        assert [r[0] for r in ss.sheets["До 20 €"].rows[1:] if r[0] != ""] == [] and ["Zenit E"] not in [r[:1] for r in models_ws.rows]
        assert len(ss.sheets["До 20 €"].rows) == 2 and not any(ss.sheets["До 20 €"].rows[1]), "old data row blanked"
        # A model new to the dictionary is offered once; spelling in the sheet does not matter.
        models_ws.rows.append(["зенит-е"])
        offered = [m for m in updates["models_offered"] if m != "Zenit KM"]
        models_ws.rows = [r for r in models_ws.rows if r[0] != "Zenit KM"]
        upd = tick.write_sheets(writer, r5, {"runs_header_v5": True,
                                             "cheap_ids": [400], "models_offered": offered,
                                             "status_colors": updates["status_colors"], "new_rows_color": True,
                                             "fresh_rows_green": True})
        assert upd.get("new_rows_colors") == ["До 20 €", "Список"], "old flag: only 'До 20 €' added"
        assert upd.get("fresh_rows_colors") == ["До 20 €", "Список"]
        assert ss.sheets["Запуски"].rows[-1][1] == 1 and upd["cheap_ids"] == [1021], "Zenit E 1021 entered 'До 20 €'"
        assert ss.sheets["Запуски"].rows[-1][2].endswith("В «До 20 €» (1): Zenit E — 15 €, id 1021"), ss.sheets["Запуски"].rows[-1][2]
        assert "Zenit KM" in upd["models_offered"] and models_ws.rows[-1][0] == "Zenit KM"
        assert [r[0] for r in ss.sheets["До 20 €"].rows[1:]] == [1021], "Cyrillic 'зенит-е' matches Zenit E"

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
        # A 3-hour rule added in light yellow 3 earlier is recoloured once to light green 3.
        sid = ss.sheets["Список"].id
        ss.rules[sid].insert(1, {"ranges": [{"sheetId": sid}], "booleanRule": {
            "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": "=$AE2=\"да\""}]},
            "format": {"backgroundColor": {"red": 1, "green": 0.9490196, "blue": 0.8}}}})
        upd = tick.write_sheets(writer, r5, {**state_flags, "fresh_rows_green": None})
        assert {k: v for k, v in upd.items() if k != "models_sheet"} == {"fresh_rows_green": True}, upd
        assert ss.rules[sid][1]["booleanRule"]["format"]["backgroundColor"] == sheets.LIGHT_GREEN_3
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

    # First pass runs faster (fill pages per tick), later passes at the normal pace.
    fill = tick.Sweep("f", tuple((f"q{k}", None) for k in range(6)), None, 10, 1, 4, False, False, fill_pages_per_tick=3)
    state, client = {}, FakeClient({})
    tick.search_sweep(fill, state, client, {}, {}, "2026-10-16 12:07", "2026-10-16", Counter(), set())
    assert client.requests_made == 3 and state["f"]["query"] == 3
    tick.search_sweep(fill, state, client, {}, {}, "2026-10-16 12:22", "2026-10-16", Counter(), set())
    assert state["f"]["passes"] == 1 and state["f"]["query"] == 0
    tick.search_sweep(fill, state, client, {}, {}, "2026-10-16 12:37", "2026-10-16", Counter(), set())
    assert client.requests_made == 7 and state["f"]["query"] == 1, "after the first pass: 1 page per tick"

    # Priority models are searched before the regular pass continues (once each).
    prio = tick.Sweep("model_search", (("q0", None), ("q1", None), ("q2", None)), None, 10, 1, 4, False, False)
    state, client = {}, FakeClient({})
    real_sweep, real_prio = tick.MODEL_SWEEP, models.PRIORITY_SEARCH
    tick.MODEL_SWEEP, models.PRIORITY_SEARCH = prio, ("Canon TX",)
    try:
        tick.search_sweep(prio, state, client, {}, {}, "2026-10-16 20:07", "2026-10-16", Counter(), set())
        tick.queue_priority_models(state, "2026-10-16 20:07")
        assert state["model_search"]["priority"] == [["canon tx", "Canon TX"]] and state["model_search"]["query"] == 1
        tick.search_sweep(prio, state, client, {}, {}, "2026-10-16 20:22", "2026-10-16", Counter(), set())
        assert state["model_search"]["priority"] == [] and state["model_search"]["query"] == 1, "priority first"
        tick.queue_priority_models(state, "2026-10-16 20:37")
        assert state["model_search"]["priority"] == [], "each model only once"
    finally:
        tick.MODEL_SWEEP, models.PRIORITY_SEARCH = real_sweep, real_prio

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
    # Over a month on Vinted ('6 Wochen'): checked every 5 days; a younger one daily.
    old = {**active[AE1], "status": "active", "closed_at": None, "last_checked_at": "2026-10-19 10:37"}
    assert active[AE1]["vinted_listed_est"] == "2026-09-06" and active[AE1]["uploaded_ago"] == "6 Wochen"
    assert tick.check_priority(old, "2026-10-23 10:38", vanished=False) is None
    assert tick.check_priority(old, "2026-10-24 10:38", vanished=False) == tick.P_FOUND
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
    assert report.is_new({"first_seen": "2026-10-16 20:00", "flags": ["found"]}, "2026-10-16 09:00", old_listings=True)
    assert not report.is_new({"first_seen": "2026-10-16 20:00", "flags": ["preexisting"]}, "2026-10-16 09:00", True)
    assert not report.is_new({"first_seen": "2026-10-16 08:00", "flags": []}, "2026-10-16 09:00")

    # Accessories with a model stay out of 'Список'; a manual found by its description leaves it.
    lens = tick.new_item(rec(9_833_721_448, "Zoom Vivitar 70/210 per Nikon F", 19.0), "2026-10-16 12:00", None, [])
    assert lens["model"] == "Nikon F" and lens["group"] == "rest" and "accessory?" in lens["flags"]
    yashica = tick.new_item(rec(9_729_396_918, "Yashica Mat-124g", 3.0), "2026-10-16 12:00", "2026-10-16 11:45", [])
    assert yashica["group"] == "list" and tick.wants_description(yashica)
    tick.apply_page(yashica, {"status": "active", "price": 3.0, "description": "brochure originale in ottime condizioni",
                              "favourites": 0}, "2026-10-16 12:15")
    assert yashica["group"] == "rest" and "accessory?" in yashica["flags"]

    # Age from the id: anchors with known Vinted dates -> interpolated listing date.
    from datetime import date, timedelta
    from tracker import ageest
    today = date(2026, 10, 16)
    anchors = [{"id": 10_390_000_000 - d * 10_000_000, "vinted_listed_est": (today - timedelta(days=d)).isoformat()}
               for d in range(0, 200, 5)]
    estimate = ageest.build_estimator(anchors, 10_390_000_000, today)
    assert abs((today - estimate(10_390_000_000 - 97 * 10_000_000)).days - 97) <= 1
    assert (today - estimate(8_000_000_000)).days > 200, "below the anchors: extrapolated"
    assert ageest.build_estimator(anchors[:10]) is None, "too few anchors"

    # Fast fill: a found camera comes in with its age estimated by id, is enriched once
    # (exact age, description); older than half a year by the exact age -> removed.
    with tempfile.TemporaryDirectory() as tmp:
        store = DataStore(tmp)
        base = {1: [rec(10_390_000_000, "Kamera", 30.0)] + older(10_389_999_999)}
        tick.run_tick(store, FakeClient(base), now="2026-10-16 12:07")
        old_ids = [10_390_000_000 - d * 10_000_000 for d in range(0, 200, 5)]
        for k, item_id in enumerate(old_ids[1:31]):  # 30 anchors with known Vinted dates
            it = tick.new_item(rec(item_id, "Nikon FM2", 100.0), "2026-10-16 12:07", None, ["found"])
            it.update(age_source="vinted", vinted_listed_est=(today - timedelta(days=5 * (k + 1))).isoformat(),
                      description="Kamera", description_checked=True, last_checked_at="2026-10-16 12:07")
            store.save(it)
        young, old_one = 9_600_000_001, 9_000_000_001
        state = store.load_state()  # the models searched first are done already: the pass starts at 'nikon f'
        tick.sweep_state(state, tick.MODEL_SWEEP, "2026-10-16 12:07")["prioritized"] = list(models.PRIORITY_SEARCH)
        store.save_state(state)
        search = {("nikon f", 1): [rec(young, "Nikon F Photomic", 150.0), rec(old_one, "Nikon F body", 140.0)]}
        client = FakeClient(base, {young: {"uploaded_ago": "2 Monaten", "description": "Kamera, Prisma"},
                                   old_one: {"uploaded_ago": "7 Monaten"}}, search)
        r = tick.run_tick(store, client, now="2026-10-16 12:22")
        a = store.load_active()
        assert young in a and a[young]["age_source"] == "id" and "оценка" in report.item_row(a[young])[9], r["run"]
        assert young not in client.opened and tick.needs_enrich(a[young])
        r = tick.run_tick(store, client, now="2026-10-16 12:37")
        a = store.load_active()
        assert r["run"]["enriched"] >= 1 and a[young]["age_source"] == "vinted" and a[young]["uploaded_ago"] == "2 Monaten"
        assert not tick.needs_enrich(a[young]) and a[young]["description"] == "Kamera, Prisma"
        # Estimated ~139 days by id (taken in), '7 Monaten' on its page -> removed and never re-added.
        assert r["run"]["too_old"] == 1 and old_one not in a and old_one in store.load_state()["model_search"]["skipped"]

    # 'Запуски' comment: what entered the list and what sold this tick.
    comment = tick.runs_comment(r2["run"])
    assert "Добавлены (3): " in comment and "Nikon FM2 — 150 €" in comment and "Zenit 12XP — 10 € (поднято)" in comment, comment
    assert comment.endswith("Проданы (1): Canon AE-1 — 45 €, id 1010"), comment
    assert tick.runs_comment({"added": [f"m{k}" for k in range(45)]}).endswith("m39 … и ещё 5")
    assert "Canon" not in tick.log_line(r2["run"]), "names never reach the Actions log"

    # An older, shorter 'Запуски' header is replaced, not duplicated.
    ss2 = FakeSpreadsheet()
    ss2.sheets["Запуски"].rows = [sheets.RUNS_HEADER_V4[:-1], ["2026-10-16 07:07"]]
    sheets.SheetWriter(ss2).ensure_runs_header()
    assert ss2.sheets["Запуски"].rows[0] == sheets.RUNS_HEADER and len(ss2.sheets["Запуски"].rows) == 2
    # Rows of the old order (v4, or shorter v3): 'Новых в «До 20 €»' and 'Комментарий' move to the front.
    old = ["2026-10-16 07:07", "да", 2, 40, 0.0, 300] + [0] * 14 + ["Добавлены (1): Zenit E — 15 €", 3]
    ss2.sheets["Запуски"].rows = [sheets.RUNS_HEADER_V4[:-1], old, ["2026-10-16 07:22", "", 2]]
    sheets.SheetWriter(ss2).ensure_runs_header()
    moved = ss2.sheets["Запуски"].rows
    assert moved[0] == sheets.RUNS_HEADER and moved[1][:5] == ["2026-10-16 07:07", 3, "Добавлены (1): Zenit E — 15 €", "да", 2], moved[1]
    assert moved[2][:5] == ["2026-10-16 07:22", "", "", "", 2] and len(moved[1]) == len(sheets.RUNS_HEADER)
    run_row = tick.runs_row({"at": "t", "full_scan": False, "pages": 1, "requests": 1, "mb": 0, "seconds": 1,
                             **{k: 0 for k in ("new_list", "new_rest", "bumped", "checks", "sold_list", "sold_rest",
                                               "deleted", "reserved_hidden", "closed_3h", "closed_30d", "descriptions",
                                               "description_to_list", "deferred")}, "errors": []})
    assert len(run_row) == len(sheets.RUNS_HEADER)

    # Vinted's German upload age, in Russian.
    assert [report.uploaded_ago_ru(t) for t in ("5 Monaten", "1 Monat", "2 Wochen", "1 Woche", "3 Tagen", "1 Tag",
                                                "1 Std.", "5 Std.", "18 Min.", "1 Jahr", "2 Jahren", None, "gestern")] == [
        "5 месяцев назад", "1 месяц назад", "2 недели назад", "1 неделю назад", "3 дня назад", "1 день назад",
        "1 час назад", "5 часов назад", "18 минут назад", "1 год назад", "2 года назад", "", "gestern"]

    # An old card that kept group 'list' with an accessory flag (created before the rule) moves out.
    with tempfile.TemporaryDirectory() as tmp:
        store = DataStore(tmp)
        base = {1: [rec(10_390_000_000, "Kamera", 30.0)] + older(10_389_999_999)}
        tick.run_tick(store, FakeClient(base), now="2026-10-16 17:00")
        acc = tick.new_item(rec(10_384_439_658, "Accessoires Olympus OM 10", 10.0), "2026-10-16 09:00", None, [])
        acc["group"] = "list"  # as created by the older code
        store.save(acc)
        state = store.load_state()
        state["models_version"] = 0
        store.save_state(state)
        r = tick.run_tick(store, FakeClient(base), now="2026-10-16 17:15")
        moved = (store.load_active().get(acc["id"]) or store.load_closed().get(acc["id"]))
        # out of the list, and as an accessory out of the data too
        assert moved is None and r["run"]["reclassified"] >= 1 and r["run"]["junk_dropped"] >= 1, r["run"]
        assert r["daily"], "'Остальные' is rewritten after the clean-up"

    # 'Проверка': a Mat-124G at 3 EUR among 200 EUR ones, a model taken from the description,
    # and a title with an accessory word that slipped through; manual labels are trusted.
    def card(item_id, title, price, **extra):
        it = tick.new_item(rec(item_id, title, price), "2026-10-16 12:00", "2026-10-16 11:45", [])
        it.update(extra)
        return it
    pool = [card(100 + k, "Yashica Mat-124G", 200.0 + k) for k in range(5)]
    cheap_mat = card(200, "Yashica Mat-124g", 5.0)  # cameras sell for 5-10 EUR
    by_desc = card(201, "Kamera Canon", 50.0, model="Canon AE-1", model_source="description", group="list", in_list=True)
    kit = card(202, "Nikon FM2 Kamera Tasche Leder", 120.0)
    slipped = card(204, "Lederhülle Canon AE-1 Kamera", 15.0, group="list", flags=[])  # an old card
    labelled = card(203, "Winder Canon AE-1", 2.0, group="list", flags=[], model_source="manual")
    rows = report.check_rows(pool + [cheap_mat, by_desc, kit, slipped, labelled])
    reasons = {r[1]: r[0] for r in rows[1:]}
    assert rows[0] == report.CHECK_HEADER and set(reasons) == {204}, reasons
    assert "hulle" in reasons[204], reasons

    # Real cameras the user reviewed: kit words after the model are not suspicious.
    reviewed = [
        "Olympus OM-1 Film SLR Camera / Olympus F. Zuiko Auto-S 50mm F1.8 Lens",
        "Praktica L - Spiegelreflexkamera - DDR - all in - Belichtungsmesser, Blitz, Objektive",
        "Nikon F3 Analoge Kamera Set DW-3 DW-4 Sucher MF-14 Rückwand",
        "Appareil photo CANON A-1 Speedlite 155A, son flash et ses trois objectifs",
        "Canon T90 Kamera Objektiv Speedlite 300TL Blitz Professionell",
        "Appareil photo Olympus OM 2 N analogique, flash, optique Tamron",
        "Fotocamera Canon AE1 Program - Zoom -2 Flash- optical filter vintage",
        "Fotocamera Olympus OM-1 completa di obiettivo",
        "Canon AE-1 silver film camera set - 3 lenses, flash & power winder",
        "Kamera Praktica L, Objektiv Carl Zeiss Jena Tessar 2.8/50, Blitzgeräte, Tasche",
        "Nikon Em appareil photo argentique complet objectif sigma 28-85 mm sacoche cuir et manuels",
        "Nikon FM Schwarz Black SLR 35mm Filmkamera Gehäuse Body Deckel getestet",
        "Nikon FG Kamera, Tokina AT-X, 28-85mm Objektiv und Zubehör",
        "Zorki 4 - Fotocamera a rullino 35mm pellicola funzionante",
        "Appareil argentique Praktica MTL 5 - objectif 135mm F2.8 monture M42 fonctionnel",
        "Objectif Sigma 28mm + appareil photo argentique Konica Autoreflex TC",
        "Canon A-1 – Vintage 35mm analog Filmkamera SLR / AE1 Programm 28-85 f1:3.5 Zoom getestet",
    ]
    cards = [card(300 + k, t, 90.0) for k, t in enumerate(reviewed)]
    assert all(c["group"] == "list" and not c["flags"] for c in cards), [(c["title"], c["flags"]) for c in cards]
    assert report.check_rows(cards)[1:] == [], report.check_rows(cards)[1:]
    assert "accessory?" in tick.new_item(rec(300, "Nikon FM2 camera body cap", 9.0), "x", None, [])["flags"]

    # Sorting: a fresh listing stays above old cameras found later by search.
    fresh = {"id": 1, "first_seen": "2026-10-16 19:07", "flags": []}
    old_found = {"id": 2, "first_seen": "2026-10-16 19:37", "flags": ["found"], "vinted_listed_est": "2026-08-01"}
    bumped = {"id": 3, "first_seen": "2026-10-16 19:22", "flags": ["bumped"], "vinted_listed_est": "2026-05-01"}
    order = [i["id"] for i in sorted([old_found, fresh, bumped], key=report.listed_key, reverse=True)]
    assert order == [3, 1, 2], order

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
    at = lambda price, group="list", flags=(), status="active": {
        "price_history": [{"at": "x", "price": price}], "group": group, "flags": list(flags), "status": status}
    assert len(report.cheap_cameras([at(20.0), at(19.99), at(20.01)], 20.0)) == 2
    assert not report.cheap_cameras([at(10.0, status=s) for s in ("sold", "deleted", "reserved", "hidden", "unsold_30d")], 20.0)
    assert not report.cheap_cameras([at(10.0, flags=["accessory?"]), at(10.0, group="rest")], 20.0),         "accessories and rest rows are not in 'До 20 €'"
    # Quick checks between ticks: page 1 only; a new list camera is in at once, a fresh one
    # gone from page 1 is opened (fast sale); no searches, no labelled ids, no full scan.
    with tempfile.TemporaryDirectory() as tmp:
        store = DataStore(tmp)
        page1 = [rec(20_000_000_010, "Canon AE-1 Program", 120.0)] + older(20_000_000_009)
        tick.run_tick(store, FakeClient({1: page1[1:], 2: older(19_000_000_000)}), now="2026-10-17 10:22")
        tick.run_tick(store, FakeClient({1: page1, 2: older(19_000_000_000)}), now="2026-10-17 10:37")
        client = FakeClient({1: [rec(20_000_000_020, "Nikon FM2 Kamera", 200.0)] + page1[1:], 2: older(19_000_000_000)},
                            {20_000_000_010: {"status": "sold", "price": 120.0}})
        rq = tick.run_tick(store, client, labels={5555: "Canon AE-1"}, now="2026-10-17 10:42", quick=True)
        run = rq["run"]
        assert run["quick"] and run["pages"] == 1 and not run["full_scan"] and run["search_pages"] == 0, run
        assert run["new_list"] == 1 and run["sold_list"] == 1 and run["list_changed"], run
        assert set(client.opened) == {20_000_000_020, 20_000_000_010}, client.opened  # description + vanished
        a, c = store.load_active(), store.load_closed()
        assert a[20_000_000_020]["listed_after"] == "2026-10-17 10:37" and c[20_000_000_010]["status"] == "sold"
        assert c[20_000_000_010]["time_to_sell_max"] == 20, "listed after 10:22, gone at the 10:42 quick check"
        assert store.load_state()["last_tick_at"] == "2026-10-17 10:42" and tick.runs_row(run)[sheets.RUNS_HEADER.index("Полный обход")] == "быстрая"
        assert tick.log_line(run).startswith("quick tick 10:42")
        idle = tick.run_tick(store, FakeClient({1: [rec(20_000_000_020, "Nikon FM2 Kamera", 200.0)] + page1[1:]}),
                             now="2026-10-17 10:47", quick=True)
        assert not idle["run"]["list_changed"], "nothing new: the sheet is not written"
        # 'Sofortbildkameras' page 1: list cameras only, new ones as new, older ones as found.
        pages = {1: [rec(20_000_000_300, "Kamera", 30.0)] + page1[1:], 2: older(19_000_000_000),
                 (3077, 1): [rec(20_000_000_301, "Nikon EM Camera met een Nikon Camerariem", 30.0),
                             rec(20_000_000_302, "Polaroid 600", 25.0), rec(19_500_000_000, "Canon AE-1 alt", 60.0)]}
        r3077 = tick.run_tick(store, FakeClient(pages), now="2026-10-17 11:07")
        a = store.load_active()
        assert a[20_000_000_301]["model"] == "Nikon EM" and a[20_000_000_301]["listed_after"] == "2026-10-17 10:47"
        assert 20_000_000_302 not in a and a[19_500_000_000]["flags"] == ["found"], r3077["run"]

        # Cheap check: a new cheap list camera is carded at once (listed after the last check of
        # any kind); a cheap listing without a model gets its description read and may join the
        # list; the catalog's top id and tick time stay; nothing vanishes from a filtered page.
        state0 = store.load_state()
        client = FakeClient({"cheap": [rec(30_000_000_001, "Zenit E", 15.0), rec(30_000_000_002, "Kamera alt", 10.0)]},
                            {30_000_000_002: {"description": "Praktica MTL 5, Verschluss ok"}})
        rc = tick.run_cheap(store, client, now="2026-10-17 11:10")
        a, st = store.load_active(), store.load_state()
        assert rc["run"]["cheap"] and a[30_000_000_001]["model"] == "Zenit E" and a[30_000_000_001]["group"] == "list"
        assert a[30_000_000_001]["listed_after"] == "2026-10-17 11:07" and st["last_cheap_at"] == "2026-10-17 11:10"
        assert a[30_000_000_002]["model"] == "Praktica MTL 5" and rc["run"]["description_to_list"] == 1
        assert st["max_seen_id"] == state0["max_seen_id"] and st["last_tick_at"] == state0["last_tick_at"]
        assert set(client.opened) <= {30_000_000_001, 30_000_000_002}, client.opened
        assert tick.log_line(rc["run"]).startswith("cheap tick") and tick.runs_row(rc["run"])[sheets.RUNS_HEADER.index("Полный обход")] == "до 20 €"
        assert store.load_state()["checks_since_tick"]["cheap"] == 1 and tick.runs_row(rc["run"])[-1] == ""

        # Full scans (the morning after the night) read 3 pages of the extra categories.
        state = store.load_state()
        state["last_full_scan_at"] = "2026-10-17 06:00"
        store.save_state(state)
        pages = {1: page1, 2: older(19_000_000_000), (3077, 2): [rec(25_000_000_100, "Nikon EM Kamera", 40.0)]}
        rf = tick.run_tick(store, FakeClient(pages), now="2026-10-17 11:20")
        assert rf["run"]["full_scan"] and 25_000_000_100 in store.load_active(), rf["run"]
        assert tick.runs_row(rf["run"])[-1] == "быстрых 0, до 20 € 1", tick.runs_row(rf["run"])[-1]
        assert store.load_state()["checks_since_tick"] == {"quick": 0, "cheap": 0}

        # Fresh search: a list camera from another category, listed within a day, is tracked.
        state = {"max_seen_id": 20_000_000_100, "max_seen_history": [["2026-10-16 11:00", 20_000_000_000],
                                                                    ["2026-10-17 10:30", 20_000_000_040]],
                 "models_sheet": ["Canon AE-1"]}
        fresh = [rec(20_000_000_050, "Canon AE-1 analog", 90.0), rec(20_000_000_051, "Canon AE-1 Tasche", 9.0),
                 rec(20_000_000_200, "Canon AE-1 neu", 99.0), rec(19_000_000_000, "Canon AE-1 alt", 80.0)]
        client, active, st = FakeClient({}, search={("canon ae-1", "fresh"): fresh}), {}, Counter()
        tick.fresh_search(state, client, active, {}, "2026-10-17 10:52", st, set(), quick=True)
        assert list(active) == [20_000_000_050] and active[20_000_000_050]["flags"] == ["found"], active
        cam = active[20_000_000_050]
        assert cam["fresh_query"] == "Canon AE-1" and cam["fresh_seen_at"] == "2026-10-17 10:52"
        tick.fresh_search(state, client, active, {}, "2026-10-17 11:20", st, set(), quick=True)
        assert st["fresh_pages"] == 1, "each model about once an hour"
        assert tick._top_at(state["max_seen_history"], "2026-10-17 10:52") == 20_000_000_040
        # Next hour: the camera is gone from its model's page -> its page is opened next tick.
        client.search[("canon ae-1", "fresh")] = fresh[1:]
        tick.fresh_search(state, client, active, {}, "2026-10-17 11:52", st, set(), quick=True)
        assert state["fresh_search"]["last_run"]["Canon AE-1"] == "2026-10-17 11:52" and st["fresh_pages"] == 2
        assert cam["needs_check"] and st["fresh_missing"] == 1
        # A sighting counts as a check, but the page is opened every 5 days.
        seen = {"group": "list", "flags": ["found"], "last_checked_at": "2026-10-15 10:00",
                "fresh_seen_at": "2026-10-17 11:00", "first_seen": "2026-10-10 10:00"}
        assert tick.check_priority(seen, "2026-10-17 12:00", vanished=False) is None
        assert tick.check_priority({**seen, "last_checked_at": "2026-10-12 09:00"}, "2026-10-17 12:00", False) == tick.P_FOUND

        # A listing newer than the catalog pages is new, not an old one found by search.
        sweep = tick.Sweep("model_search", (("q0", None),), None, 10, 1, 4, False, False)
        state = store.load_state()
        client = FakeClient({}, search={("q0", 1): [rec(30_000_000_000, "Canon AE-1", 100.0)]})
        tick.search_sweep(sweep, state, client, {}, {}, "2026-10-17 10:52", "2026-10-17", Counter(), set())
        assert not state["model_search"]["pending"], "left for the catalog"

    print("tick tests passed")


if __name__ == "__main__":
    main()
