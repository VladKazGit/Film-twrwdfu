"""E-mail alerts: cameras that entered 'До 20 €', once each, intro first. Run: python -m tests.test_notify"""
import os

from tracker import notify


def card(item_id, model, price, flags=(), group="list", status="active"):
    return {"id": item_id, "model": model, "title": f"{model} analog", "url": f"https://www.vinted.de/items/{item_id}",
            "price_start": price, "price_final": None, "price_history": [{"at": "2026-10-18 10:30", "price": price}],
            "first_seen": "2026-10-18 10:30", "flags": list(flags), "group": group, "status": status,
            "description_checked": True}


def main():
    state = {"models_sheet": ["Zenit E", "Canon AE-1", "Praktica MTL 5", "Olympus OM-10", "Canon T70"]}
    items = [card(1, "Zenit E", 15.0), card(2, "Canon AE-1", 120.0)]
    sent = []
    os.environ.pop("MAIL_USER", None)
    assert notify.run(items, state, "2026-10-18 10:37", sent.append) is None and not sent, "not set up: nothing"
    os.environ.update(MAIL_USER="me@example.com", MAIL_APP_PASSWORD="abcd efgh ijkl mnop")
    try:
        # Switched on: one intro letter, the sheet as it is becomes the baseline.
        assert notify.run(items, state, "2026-10-18 10:37", sent.append) == 0 and len(sent) == 1
        assert "включены" in sent[0]["Subject"] and "1 камер" in sent[0].get_body(("plain",)).get_content()
        assert notify.run(items, state, "2026-10-18 10:42", sent.append) == 0 and len(sent) == 1
        # New entries of 'До 20 €': a cheap new one, an old one found by search, a price drop.
        items += [dict(card(3, "Zenit E", 8.0), photo="https://images1.vinted.net/p3.jpg", description="Kamera funktioniert"),
                  card(4, "Canon AE-1", 19.0, flags=["found"]),
                  card(5, "Canon AE-1", 10.0, flags=["accessory?"]),   # flagged: not in the sheet
                  card(6, "Pentax K1000", 15.0),                       # not in 'Модели'
                  card(9, "Praktica MTL 5", 9.0),                      # Praktica: no letters
                  card(12, "Canon T70", 10.0),                         # T50 / T60 / T70: no letters
                  card(10, "Olympus OM-10", 15.0),                     # sells for 40: not 50 EUR below
                  dict(card(11, "Olympus OM-10", 40.0, status="sold"),
                       listed_after="2026-10-16 10:00", sold_detected_at="2026-10-18 10:00"),
                  dict(card(7, "Zenit E", 70.0, status="sold"),       # not on sale; sales in the data
                       listed_after="2026-10-16 10:00", sold_detected_at="2026-10-18 10:00"),
                  dict(card(8, "Zenit E", 90.0, status="sold"),
                       listed_after="2026-10-16 10:00", sold_detected_at="2026-10-20 10:00")]
        items[1]["price_history"].append({"at": "2026-10-18 10:45", "price": 20.0})
        assert notify.run(items, state, "2026-10-18 10:47", sent.append) == 3 and len(sent) == 2
        body = sent[1].get_body(("plain",)).get_content()
        assert "items/3" in body and "items/4" in body and "items/2" in body and "items/5" not in body
        assert "items/9" not in body and "Praktica" not in body
        assert "items/12" not in body and "items/10" not in body, "a skipped model; 15 EUR is not 50 below 40"
        assert "найдено поиском" in body and sent[1]["Subject"].startswith("⚡ Vinted «До 20 €»: Zenit E — 8 € и ещё 2")
        html = sent[1].get_body(("html",)).get_content()
        assert '<img src="https://images1.vinted.net/p3.jpg"' in html and "Kamera funktioniert" in html and "Kamera funktioniert" in body
        assert "Продажи Zenit E в базе: в среднем 80 € (от 70 € до 90 €, продаж: 2)" in body, body
        assert "Продажи Canon AE-1 в базе: пока нет" in body and "в среднем 80 €" in html
        assert "Продаются в среднем за: 3 дня" in body and "Продаются в среднем за: 3 дня" in html, body
        assert body.index("Zenit E — 8 €") < body.index("Продажи Zenit E") < body.index("items/3"), "paragraphs in order"
        assert notify.run(items, state, "2026-10-18 10:52", sent.append) == 0 and len(sent) == 2, "each camera once"

        # 'Zenit 1980': the Moscow 1980 Olympic editions at 30 EUR or less, each once
        def zenit(item_id, title, price, description="", status="active", flags=()):
            return {"id": item_id, "title": title, "description": description, "model": "Zenit EM", "brand": "Zenit",
                    "group": "list", "status": status, "price_start": price, "price_history": [], "flags": list(flags),
                    "url": f"https://www.vinted.de/items/{item_id}"}
        watch = [zenit(101, "Zenit EM (Moskva ‘80 Olympic edition)", 25.0),
                 zenit(102, 'Zenit TTL "Edizione Olimpica"', 30.0),
                 zenit(103, "Appareil photo Zenit EM", 20.0, "édition jeux olympiques de Moscou 1980"),
                 zenit(104, "Zenit-E Olimpiadi 1980 funzionante", 45.0),                      # dearer than 30
                 zenit(105, "Fotocamera Zenit EM", 15.0, "va con Canon, Olympus, Nikon"),     # Olympus, not Olympia
                 zenit(106, "Zenit EM Moskva 80", 20.0, status="sold"),
                 zenit(107, "Zenit-E", 10.0, "Baujahr 1980"),                                  # the year it was made
                 zenit(108, "Mode d'emploi Zenit EM JO 1980", 5.0, flags=["accessory?"])]
        assert [i["id"] for i in notify.watch_now(watch)] == [101, 102, 103], notify.watch_now(watch)
        state2 = {}
        assert notify.run_watch(watch, state2, "2026-10-31 10:00", sent.append) == 3 and len(sent) == 3
        assert sent[2]["Subject"].startswith("🏅 Vinted «Zenit 1980»: Zenit EM — 20 € и ещё 2"), sent[2]["Subject"]
        assert notify.run_watch(watch, state2, "2026-10-31 10:15", sent.append) == 0 and len(sent) == 3, "each once"
        watch[3]["price_history"] = [{"at": "2026-10-31 10:20", "price": 29.0}]
        assert notify.run_watch(watch, state2, "2026-10-31 10:30", sent.append) == 1, "cheaper later: mailed then"
        # Kleinanzeigen: its own state, Vinted's sales in the letter, not one waiting for its page check
        ka = [dict(zenit(201, "Zenit EM Sonderedition Olympia Moskau 1980", 20.0),
                   url="https://www.kleinanzeigen.de/s-anzeige/x/201-245-1"),
              dict(zenit(202, "Zenit TTL Olympia 1980", 25.0), recheck="2026-10-31 09:00")]
        vinted_sales = notify.sale_stats([dict(zenit(301, "Zenit EM", 60.0, status="sold"), price_final=60.0)])
        assert notify.run_watch(ka, {}, "2026-10-31 11:00", sent.append, source="Kleinanzeigen", stats=vinted_sales) == 1
        body = sent[-1].get_body(("plain",)).get_content()
        assert sent[-1]["Subject"].startswith("🏅 Kleinanzeigen «Zenit 1980»: Zenit EM — 20 €"), sent[-1]["Subject"]
        assert "Продажи Zenit EM на Vinted: в среднем 60 €" in body and "201-245-1" in body and "TTL" not in body, body
    finally:
        for name in ("MAIL_USER", "MAIL_APP_PASSWORD"):
            os.environ.pop(name, None)
    print("notify tests passed")


if __name__ == "__main__":
    main()
