"""E-mail alerts: cameras that entered 'До 20 €', once each, intro first. Run: python -m tests.test_notify"""
import os

from tracker import notify


def card(item_id, model, price, flags=(), group="list", status="active"):
    return {"id": item_id, "model": model, "title": f"{model} analog", "url": f"https://www.vinted.de/items/{item_id}",
            "price_start": price, "price_final": None, "price_history": [{"at": "2026-10-18 10:30", "price": price}],
            "first_seen": "2026-10-18 10:30", "flags": list(flags), "group": group, "status": status}


def main():
    state = {"models_sheet": ["Zenit E", "Canon AE-1"]}
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
                  card(7, "Zenit E", 18.0, status="sold"),             # not on sale; a sale in the data
                  card(8, "Zenit E", 46.0, status="sold")]
        items[1]["price_history"].append({"at": "2026-10-18 10:45", "price": 20.0})
        assert notify.run(items, state, "2026-10-18 10:47", sent.append) == 3 and len(sent) == 2
        body = sent[1].get_body(("plain",)).get_content()
        assert "items/3" in body and "items/4" in body and "items/2" in body and "items/5" not in body
        assert "найдено поиском" in body and sent[1]["Subject"].startswith("⚡ Vinted «До 20 €»: Zenit E — 8 € и ещё 2")
        html = sent[1].get_body(("html",)).get_content()
        assert '<img src="https://images1.vinted.net/p3.jpg"' in html and "Kamera funktioniert" in html and "Kamera funktioniert" in body
        assert "Продажи Zenit E в базе: в среднем 32 € (от 18 € до 46 €, продаж: 2)" in body, body
        assert "Продажи Canon AE-1 в базе: пока нет" in body and "в среднем 32 €" in html
        assert notify.run(items, state, "2026-10-18 10:52", sent.append) == 0 and len(sent) == 2, "each camera once"
    finally:
        for name in ("MAIL_USER", "MAIL_APP_PASSWORD"):
            os.environ.pop(name, None)
    print("notify tests passed")


if __name__ == "__main__":
    main()
