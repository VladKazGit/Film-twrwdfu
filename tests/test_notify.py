"""E-mail alerts: which cameras, once each, intro first. Run: python -m tests.test_notify"""
import os

from tracker import notify


def card(item_id, model, price, first_seen="2026-10-18 10:30", flags=(), group="list", status="active"):
    return {"id": item_id, "model": model, "title": f"{model} analog", "url": f"https://www.vinted.de/items/{item_id}",
            "price_start": price, "price_final": None, "price_history": [{"at": first_seen, "price": price}],
            "first_seen": first_seen, "flags": list(flags), "group": group, "status": status}


def main():
    pool = [card(k, "Minolta X-700", 100.0 + k, first_seen="2026-10-10 10:00") for k in range(5)]
    items = pool + [
        card(10, "Minolta X-700", 60.0),                      # 58 % of the usual ~102 €: a deal
        card(11, "Minolta X-700", 95.0),                      # ordinary price: no letter
        card(12, "Zenit E", 15.0),                            # cheap
        card(13, "Canon AE-1", 180.0),                        # key model
        card(14, "Canon AE-1", 10.0, flags=["accessory?"]),   # flagged: no
        card(15, "Canon AE-1", 90.0, flags=["found"]),        # an old listing found by search: no
        card(16, "Zenit E", 12.0, first_seen="2026-10-18 09:00"),  # seen too long ago
        card(17, "Pentax K1000", 15.0),                       # not in 'Модели'
    ]
    state = {"models_sheet": ["Minolta X-700", "Zenit E", "Canon AE-1"]}
    picked = notify.pick(items, state, "2026-10-18 10:37")
    reasons = {i["id"]: r for i, r in picked}
    assert set(reasons) == {10, 12, 13}, reasons
    assert reasons[10].startswith("на 41 % дешевле обычной") and reasons[12] == "≤ 20 €" and reasons[13] == "ключевая модель"

    sent = []
    os.environ.pop("MAIL_USER", None)
    assert notify.run(items, state, "2026-10-18 10:37", sent.append) is None and not sent, "not set up: nothing"
    os.environ.update(MAIL_USER="me@example.com", MAIL_APP_PASSWORD="abcd efgh ijkl mnop")
    try:
        assert notify.run(items, state, "2026-10-18 10:37", sent.append) == 3 and len(sent) == 1
        body = sent[0].get_body(("plain",)).get_content()
        assert "Уведомления о камерах включены" in body and "https://www.vinted.de/items/12" in body
        assert sent[0]["Subject"].startswith("Vinted: ") and "и ещё 2" in sent[0]["Subject"], sent[0]["Subject"]
        assert notify.run(items, state, "2026-10-18 10:42", sent.append) == 0 and len(sent) == 1, "each camera once"
        items.append(card(18, "Zenit E", 5.0, first_seen="2026-10-18 10:47"))
        assert notify.run(items, state, "2026-10-18 10:47", sent.append) == 1 and len(sent) == 2
        assert "включены" not in sent[1].get_body(("plain",)).get_content(), "the intro comes once"
    finally:
        for name in ("MAIL_USER", "MAIL_APP_PASSWORD"):
            os.environ.pop(name, None)
    print("notify tests passed")


if __name__ == "__main__":
    main()
