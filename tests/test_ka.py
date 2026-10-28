"""Kleinanzeigen collector on fake pages. Run: python -m tests.test_ka"""
import json
import random
import tempfile
from datetime import datetime, timedelta

from tracker import ka_loop, ka_report, ka_tick, kleinanzeigen, models
from tracker.env import BERLIN
from tracker.store import DataStore


def block(adid, title, when, price, description="", reserved=False, old=None):
    """One listing of a search page, shaped like Kleinanzeigen's."""
    meta = {"creditText": "Kleinanzeigen", "title": title, "description": description,
            "contentUrl": f"https://img.example/{adid}", "@type": "ImageObject"}
    return (f'<article class="aditem" data-adid="{adid}" data-href="/s-anzeige/x/{adid}-245-1">'
            f'<script type="application/ld+json">{json.dumps(meta, separators=(",", ":"))}</script>'
            f'<div><span>12345 Ort</span><span>{when}</span></div>'
            + ('<span class="badge">Reserviert</span>' if reserved else "")
            + f'<h3 class="text-title3 font-strong">{title}</h3>'
            + (f'<p class="text-x line-through">{old}</p>' if old else "")
            + f'<p class="text-title3 font-strong">{price}</p></article>')


def rec(adid, title, when, price, kind="camera", **kw):
    html = block(adid, title, when, price, **kw)
    return kleinanzeigen.parse_search(html, NOW, kind)[0]


NOW = "2026-10-28 12:00"


class FakeClient:
    def __init__(self, types=None, searches=None, ads=None):
        self.types, self.searches, self.ads = types or {}, searches or {}, ads or {}
        self.requests_made, self.opened, self.searched = 0, [], []

    def has_time(self):
        return True

    def search_page(self, kind, page, now):
        self.requests_made += 1
        return self.types.get((kind, page), [])

    def model_search(self, text, page, now):
        self.requests_made += 1
        self.searched.append((text, page))
        return self.searches.get((text, page), [])

    def ad_page(self, url):
        self.requests_made += 1
        self.opened.append(url)
        return self.ads.get(url, {"status": "active", "price": None, "vb": False, "date": None, "condition": None})


def test_parsers():
    assert kleinanzeigen.parse_price("1.200 € VB") == (1200.0, True)
    assert kleinanzeigen.parse_price("70 €") == (70.0, False)
    assert kleinanzeigen.parse_price("VB") == (None, True)
    assert kleinanzeigen.parse_price("Zu verschenken") == (0.0, False)
    assert kleinanzeigen.parse_price("12,50 €") == (12.5, False)
    assert kleinanzeigen.listed_at("Heute, 10:47", NOW) == "2026-10-28 10:47"
    assert kleinanzeigen.listed_at("Gestern, 18:02", NOW) == "2026-10-27 18:02"
    assert kleinanzeigen.listed_at("27.09.2026", NOW) == "2026-09-27"
    assert kleinanzeigen.listed_at("", NOW) is None
    assert kleinanzeigen.query_slug("Hasselblad 500C/M") == "hasselblad-500c-m"
    assert kleinanzeigen.query_slug("Canon AE-1 Program") == "canon-ae-1-program"

    page = block(11, "Canon AE-1 mit 50mm", "Heute, 11:40", "140 € VB", "Top Zustand") + \
        block(12, "Nikon FM2", "Gestern, 09:00", "300 €", reserved=True, old="350 €") + block(13, "Ohne Datum", "", "VB")
    a, b, c = kleinanzeigen.parse_search(page, NOW, "camera")
    assert (a["id"], a["price"], a["vb"], a["listed_at"], a["reserved"]) == (11, 140.0, True, "2026-10-28 11:40", False)
    assert a["url"].endswith("/s-anzeige/x/11-245-1") and a["description"] == "Top Zustand"
    assert (b["price"], b["old_price"], b["reserved"], b["listed_at"]) == (300.0, 350.0, True, "2026-10-27 09:00")
    assert (c["price"], c["listed_at"]) == (None, None)

    url = "https://www.kleinanzeigen.de/s-anzeige/x/11-245-1"
    ad = ('<h1 id="viewad-title" class="x">Canon AE-1</h1><h2 id="viewad-price">130 € VB</h2>'
          '<div id="viewad-extra-info"><span>20.10.2026</span></div>'
          '<li class="addetailslist--detail">Zustand<span class="v">Sehr Gut</span></li>')
    assert kleinanzeigen.parse_ad(ad, url, url) == {"status": "active", "price": 130.0, "vb": True,
                                                   "date": "2026-10-20", "condition": "Sehr Gut"}
    reserved = ad.replace(">Canon AE-1<", ">Reserviert • Canon AE-1<")
    assert kleinanzeigen.parse_ad(reserved, url, url)["status"] == "reserved"
    assert kleinanzeigen.parse_ad("<html>Foto</html>", "https://www.kleinanzeigen.de/s-foto/c245", url)["status"] == "gone"


def test_checks():
    with tempfile.TemporaryDirectory() as tmp:
        store = DataStore(tmp)
        ae1 = rec(500, "Canon AE-1 analog mit 50mm", "Heute, 11:50", "120 € VB")
        sony = rec(499, "Sony A6400", "Heute, 11:45", "500 €")
        lot = rec(498, "Canon AE-1 und Canon A-1 Konvolut", "Heute, 11:30", "200 €")
        old = rec(300, "Canon AE-1 Program", "Heute, 10:00", "90 €")  # older than the hour: the last page
        fm2 = rec(200, "Nikon FM2 Gehäuse", "12.10.2026", "350 €", kind=None)
        manual = rec(201, "Bedienungsanleitung Nikon FM2", "11.10.2026", "5 €", kind=None)
        client = FakeClient(types={("camera", 1): [ae1, sony, lot] * 7 + [old]},
                            searches={("Nikon FM2", 1): [fm2, manual]})
        result = ka_tick.run_check(store, client, NOW)
        run, cards = result["run"], {c["id"]: c for c in result["cards"]}
        assert set(cards) == {500, 498, 300, 200}, cards.keys()
        assert cards[500]["flags"] == [] and cards[500]["listed_at"] == "2026-10-28 11:50" and cards[500]["vb"]
        assert cards[500]["model"] == "Canon AE-1" and cards[500]["type"] == "Kamera"
        assert cards[498].get("bundle") and cards[200]["flags"] == ["preexisting"] and cards[200]["type"] is None
        assert cards[200]["in_model_search"]
        assert run["new"] == 3 and run["preexisting"] == 1 and run["backfill"] == "готов" and not result["backfill"]
        assert len({t for t, _ in client.searched}) == len(models.MODEL_INFO), "every model searched once"
        assert store.load_state()["top_ids"]["camera"] == 500

        # 20 minutes on: the AE-1 is gone from the newest pages (taken down), the FM2 page is due later
        later = "2026-10-28 12:20"
        newer = rec(510, "Olympus OM-1", "Heute, 12:10", "180 €")
        client = FakeClient(types={("camera", 1): [newer, lot, old]},
                            ads={ae1["url"]: {"status": "gone", "price": None, "vb": False, "date": None,
                                              "condition": None}})
        result = ka_tick.run_check(store, client, later)
        cards = {c["id"]: c for c in result["cards"]}
        assert cards[500]["status"] == "removed" and cards[500]["removed_detected_at"] == later
        assert cards[500]["price_final"] == 120.0 and cards[510]["flags"] == []
        assert client.opened == [ae1["url"]], client.opened
        assert len(client.searched) == ka_tick.MODEL_SEARCH_PER_CHECK, "after the first collection: a few models"
        assert store.load_closed()[500]["status"] == "removed"

        # a listing seen again after being taken down by mistake is back on sale
        client = FakeClient(types={("camera", 1): [ae1, newer, lot, old]})
        cards = {c["id"]: c for c in ka_tick.run_check(store, client, "2026-10-28 12:40")["cards"]}
        assert cards[500]["status"] == "active" and not cards[500]["closed_at"]

        # sheets
        all_cards = list(cards.values())
        rows = ka_report.list_rows(all_cards, later)
        assert rows[0] == ka_report.LIST_HEADER and rows[1][-3] == 510 and rows[1][-1] == "да"
        summary = {r[0]: r for r in ka_report.summary_rows(all_cards, later)[1:]}
        assert summary["Canon AE-1"][1] == 2 and summary["Canon AE-1"][6] == 120, summary["Canon AE-1"]
        vinted = [{"id": 1, "group": "list", "model": "Canon AE-1", "status": "sold", "price_start": 100.0,
                   "price_history": [], "listed_after": "2026-10-20 10:00", "sold_detected_at": "2026-10-22 10:00",
                   "flags": []},
                  {"id": 2, "group": "list", "model": "Canon AE-1", "status": "active", "price_start": 140.0,
                   "price_history": [], "flags": []}]
        compare = {r[0]: r for r in ka_report.compare_rows(all_cards, vinted, later)[1:]}
        row = compare["Canon AE-1"]
        assert row[1:6] == [2, 120, 1, 100, "2 дня"], row
        assert row[11] == 0 and row[12] == "+0 %", row


def test_due():
    card = {"listed_at": "2026-10-28 11:00", "first_seen": "2026-10-28 11:05", "last_seen_active": "2026-10-28 11:05"}
    assert not ka_tick.due(card, "2026-10-28 11:40") and ka_tick.due(card, "2026-10-28 11:45")
    card = {"listed_at": "2026-10-25", "first_seen": "2026-10-28 08:00", "last_seen_active": "2026-10-28 08:00"}
    assert not ka_tick.due(card, "2026-10-28 20:00") and ka_tick.due(card, "2026-10-29 08:00")  # daily
    card["last_checked_at"] = "2026-10-29 08:00"
    assert not ka_tick.due(card, "2026-10-29 20:00")
    card = {"listed_at": "2026-10-10", "first_seen": "2026-10-28 08:00", "last_seen_active": "2026-10-28 08:00"}
    assert not ka_tick.due(card, "2026-10-30 08:00") and ka_tick.due(card, "2026-10-31 08:00")  # every 3 days


def test_loop():
    rng = random.Random(1)
    at = datetime(2026, 10, 28, 12, 0, tzinfo=BERLIN)
    gap = (ka_loop.next_check(at, False, rng) - at).total_seconds() / 60
    assert 17 <= gap <= 23, gap
    assert ka_loop.next_check(at, True, rng) - at == timedelta(seconds=ka_loop.BACKFILL_PAUSE_S)
    night = ka_loop.next_check(datetime(2026, 10, 28, 23, 55, tzinfo=BERLIN), False, rng)
    assert (night.day, night.hour) == (29, 7) and 3 <= night.minute <= 12, night


def main():
    test_parsers()
    test_checks()
    test_due()
    test_loop()
    print("test_ka: ok")


if __name__ == "__main__":
    main()
