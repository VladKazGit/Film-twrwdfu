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
    raw = [{"site": "olx", "id": "1", "price_text": "441zł", "title": "Canon AE-1 + 50mm", "searched": "Canon AE-1",
            "href": "https://www.olx.pl/d/oferta/canon-ae-1-CID99-ID1.html",
            "photo": "https://ireland.apollo.olxcdn.com:443/v1/files/abc-PL/image;s=216x152"},
           {"site": "lbc", "id": "2", "price_text": "130", "title": "Canon AE-1", "searched": "Canon AE-1",
            "photo": "https://img.leboncoin.fr/api/v1/lbcpb1/images/aa/bb/cc.jpg?rule=ad-thumb"},
           {"site": "lbc", "id": "3", "price_text": "170", "title": "Canon AE-1 noir", "searched": "Canon AE-1",
            "photo": "https://evil.example/x.jpg\")+IMAGE(\"https://img.leboncoin.fr/a.jpg"},
           {"site": "lbc", "id": "4", "price_text": "5", "title": "Mode emploi canon ae 1", "searched": "Canon AE-1"},
           {"site": "ebay", "id": "5", "price_text": "EUR 99,00", "title": "Sony A7", "searched": "Canon AE-1"}]
    snap = snapshot.build(raw, "2026-10-28", 4.41)
    assert [i["id"] for i in snap["items"]] == ["1", "2", "3"], snap["items"]
    assert snap["items"][0]["price_eur"] == 100.0 and snap["items"][1]["url"].endswith("/ad/photo_audio_video/2")
    assert snap["items"][0]["url"].endswith("-ID1.html") and snap["items"][2]["photo"] is None
    assert snapshot.item_url("olx", "1", "Canon AE-1", "https://evil.example/").endswith("/q-canon-ae-1/")
    stats = snapshot.model_stats(snap)["Canon AE-1"]
    assert stats["lbc"]["n"] == 2 and stats["lbc"]["mean"] == 150 and stats["olx"]["mean"] == 100
    vinted = {"Canon AE-1": {"mean": 120, "total": 3}}
    rows = snapshot.summary_rows(snap, vinted)
    assert rows[0][1] == "Vinted: средняя цена объявлений, €" == ka_report.COMPARE_HEADER[2]
    assert rows[1][:2] == ["Canon AE-1", 120] and rows[1][8] == 2, rows[1]
    assert snapshot.summary_rows(snap)[1][1] == ""

    assert snapshot.sheet_titles(snap) == ("Срез 28.10.2026", {"olx": "OLX.pl 28.10.2026",
                                                               "lbc": "leboncoin.fr 28.10.2026",
                                                               "ebay": "eBay.de 28.10.2026"})
    lbc = snapshot.site_rows(snap, "lbc", vinted)
    assert lbc[0][:4] == ["Фото", "Модель", "Цена, €", "Vinted: средняя цена объявлений, €"]
    assert [r[2] for r in lbc[1:]] == [130.0, 170.0] and lbc[1][-1].endswith("/2"), lbc
    assert lbc[1][0] == '=IMAGE("https://img.leboncoin.fr/api/v1/lbcpb1/images/aa/bb/cc.jpg?rule=ad-thumb")'
    assert lbc[2][0] == "" and lbc[1][3] == 120

    class Sheet:
        def __init__(self):
            self.cells = {}

        def update(self, range_name, values, value_input_option):
            self.cells[range_name] = (values, value_input_option)

    class Writer:
        def __init__(self):
            self.sheets, self.written, self.tall = {}, {}, []
            self.spreadsheet = self

        def worksheet(self, title):
            return self.sheets.setdefault(title, Sheet())

        def replace(self, title, rows, links=False):
            self.written[title] = rows

        def set_row_height(self, title, pixels):
            self.tall.append(title)

    w = Writer()
    snapshot.write(w, [snap], vinted)
    assert w.written["leboncoin.fr 28.10.2026"][1][0] == "" and w.tall == ["OLX.pl 28.10.2026", "leboncoin.fr 28.10.2026"]
    assert w.sheets["leboncoin.fr 28.10.2026"].cells["A2"] == ([[lbc[1][0]], [""]], "USER_ENTERED")
    assert "eBay.de 28.10.2026" not in w.sheets
    assert snapshot.build(raw[1:4], "2026-10-31", 4.25)["sites"] == ["lbc"]
    compare = ka_report.compare_rows([], [], "2026-10-28 12:00", snap)
    assert compare[0][-1] == "eBay.de (срез 28.10): средняя цена, €"
    assert compare[1][0] == "Canon AE-1" and compare[1][-6:] == [1, 100, 2, 150, "", ""], compare[1]
    print("test_snapshot: ok")


if __name__ == "__main__":
    main()
