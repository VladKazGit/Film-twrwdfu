"""Price snapshots of other marketplaces. Run: python -m tests.test_snapshot"""
from tracker import ka_report, snapshot


def main():
    assert snapshot.parse_price("olx", "1 200zł") == (1200.0, "PLN")
    assert snapshot.parse_price("olx", "1588,95zł") == (1588.95, "PLN")
    assert snapshot.parse_price("olx", "Zamienię") is None
    assert snapshot.parse_price("lbc", "150") == (150.0, "EUR")
    assert snapshot.parse_price("ebay", "EUR 1.659,00") == (1659.0, "EUR")
    assert snapshot.parse_price("ebay", "EUR 10,00 bis EUR 20,00") is None
    assert snapshot.is_bundle("Canon AE-1 und Canon A-1")
    assert not snapshot.is_bundle("Nikon New FM2 FM2N analoge Spiegelreflexkamera")
    assert not snapshot.is_bundle("Aparat Nikon FM obiektyw Nikkor 50mm Lampa Vivitar 2800")
    raw = [{"site": "olx", "id": "1", "price_text": "441zł", "title": "Canon AE-1 + 50mm", "searched": "Canon AE-1"},
           {"site": "lbc", "id": "2", "price_text": "130", "title": "Canon AE-1", "searched": "Canon AE-1"},
           {"site": "lbc", "id": "3", "price_text": "170", "title": "Canon AE-1 noir", "searched": "Canon AE-1"},
           {"site": "lbc", "id": "4", "price_text": "5", "title": "Mode emploi canon ae 1", "searched": "Canon AE-1"},
           {"site": "ebay", "id": "5", "price_text": "EUR 99,00", "title": "Sony A7", "searched": "Canon AE-1"}]
    snap = snapshot.build(raw, "2026-10-28", 4.41)
    assert [i["id"] for i in snap["items"]] == ["1", "2", "3"], snap["items"]
    assert snap["items"][0]["price_eur"] == 100.0 and snap["items"][1]["url"].endswith("/ad/photo_audio_video/2")
    stats = snapshot.model_stats(snap)["Canon AE-1"]
    assert stats["lbc"]["n"] == 2 and stats["lbc"]["mean"] == 150 and stats["olx"]["mean"] == 100
    rows = snapshot.summary_rows(snap)
    assert rows[1][0] == "Canon AE-1" and rows[1][7] == 2, rows[1]
    assert snapshot.sheet_titles(snap) == ("Срез 28.10.2026", {"olx": "OLX.pl 28.10.2026",
                                                               "lbc": "leboncoin.fr 28.10.2026",
                                                               "ebay": "eBay.de 28.10.2026"})
    lbc = snapshot.site_rows(snap, "lbc")
    assert [r[1] for r in lbc[1:]] == [130.0, 170.0] and lbc[1][-1].endswith("/2"), lbc
    compare = ka_report.compare_rows([], [], "2026-10-28 12:00", snap)
    assert compare[0][-1] == "eBay.de (срез 28.10): средняя цена, €"
    assert compare[1][0] == "Canon AE-1" and compare[1][-6:] == [1, 100, 2, 150, "", ""], compare[1]
    print("test_snapshot: ok")


if __name__ == "__main__":
    main()
