"""One-off price snapshots of other marketplaces (OLX.pl, leboncoin.fr, eBay.de), looked through by hand in
a browser: the first page of each model's search. Kept in the data repo as snapshots/<YYYY-MM-DD>.json;
the Kleinanzeigen check (tracker.ka_tick) writes each new one to the snapshot spreadsheet (secret
SNAPSHOT_SHEET_ID: 'Срез <date>' per model and site, 'Объявления <date>' every listing) and the latest one
into 'Сравнение'. Asking prices only, titles only (no descriptions); OLX prices in PLN are converted to EUR
at the National Bank of Poland's rate of the day.
"""
import json
import re
import statistics
from pathlib import Path

from . import models, report
from .kleinanzeigen import query_slug

SITES = {"olx": "OLX.pl", "lbc": "leboncoin.fr", "ebay": "eBay.de"}
BRANDS = ("Canon", "Nikon", "Leica")
SIGNAL_FLAGS = {"accessory?", "digital?", "compact?"}
MIN_PRICE = 5.0  # below: a placeholder, not a price
NBP_URL = "https://api.nbp.pl/api/exchangerates/rates/a/eur/?format=json"
_AMOUNT = re.compile(r"(\d[\d.\s]*)(?:,(\d{1,2}))?")


def parse_price(site, text):
    """(amount, currency) from '1 200 zł' / '1588,95zł' (OLX), '150' (leboncoin), 'EUR 1.659,00' (eBay);
    None for 'Zamienię', ranges ('EUR 10,00 bis EUR 20,00') and empty prices."""
    text = (text or "").strip()
    if not text or " bis " in text:
        return None
    if site == "lbc":
        try:
            return float(text), "EUR"
        except ValueError:
            return None
    m = _AMOUNT.search(text.replace(" ", " "))
    if not m:
        return None
    whole = re.sub(r"[.\s]", "", m.group(1))
    if not whole:
        return None
    amount = float(whole + ("." + m.group(2) if m.group(2) else ""))
    return amount, "PLN" if "zł" in text else "EUR"


def is_bundle(title):
    """Two or more different cameras of the list in the title ('Canon AE-1 und Canon A-1'). One camera
    named two ways ('Nikon New FM2 FM2N') is one; flashes, mounts and lenses ('Canon FD', 'Vivitar 2800')
    and 'Set' (a camera with its lens) are no second camera."""
    names = sorted({m for _, _, m in models.find_models(title)}, key=len)
    distinct = [n for i, n in enumerate(names) if not any(m.startswith(n) for m in names[i + 1:])]
    return len(distinct) >= 2


def item_url(site, item_id, searched):
    if site == "lbc":
        return f"https://www.leboncoin.fr/ad/photo_audio_video/{item_id}"
    if site == "ebay":
        return f"https://www.ebay.de/itm/{item_id}"
    return f"https://www.olx.pl/elektronika/fotografia/q-{query_slug(searched)}/"  # the search: no ad link kept


def build(raw, date, pln_per_eur):
    """The snapshot from raw rows [{site, id, price_text, title, searched}]: cameras of the list (Canon,
    Nikon, Leica) by the tracker's own classifier, prices in EUR."""
    items = []
    for r in raw:
        cls = models.classify(r["title"])
        if not cls["model"] or cls["brand"] not in BRANDS or SIGNAL_FLAGS & set(cls["flags"]):
            continue
        price = parse_price(r["site"], r["price_text"])
        eur = None
        if price:
            eur = round(price[0] / pln_per_eur, 2) if price[1] == "PLN" else price[0]
        items.append({"site": r["site"], "id": r["id"], "model": cls["model"], "title": r["title"],
                      "price": price[0] if price else None, "currency": price[1] if price else None,
                      "price_eur": eur, "bundle": is_bundle(r["title"]),
                      "url": item_url(r["site"], r["id"], r["searched"])})
    return {"date": date, "pln_per_eur": pln_per_eur, "sites": list(SITES), "items": items}


def counted(item):
    """In the price statistics: a price, not a placeholder, not a bundle."""
    return item["price_eur"] is not None and item["price_eur"] > MIN_PRICE and not item["bundle"]


def model_stats(snapshot):
    """{model: {site: {n, mean, median, min, max, cheapest}}} (counted listings; n: all the model's)."""
    out = {}
    for i in snapshot["items"]:
        s = out.setdefault(i["model"], {}).setdefault(i["site"], {"all": 0, "prices": [], "cheapest": None})
        s["all"] += 1
        if counted(i):
            s["prices"].append(i["price_eur"])
            if s["cheapest"] is None or i["price_eur"] < s["cheapest"]["price_eur"]:
                s["cheapest"] = i
    for sites in out.values():
        for s in sites.values():
            p = s.pop("prices")
            s.update(n=len(p), mean=round(statistics.mean(p)) if p else None,
                     median=round(statistics.median(p)) if p else None,
                     min=round(min(p)) if p else None, max=round(max(p)) if p else None)
    return out


def _order(model):
    brand = models.MODEL_INFO.get(model, {}).get("brand", "")
    return (BRANDS.index(brand) if brand in BRANDS else len(BRANDS), model)


def summary_rows(snapshot):
    header = ["Модель"]
    for site in snapshot["sites"]:
        name = SITES[site]
        header += [f"{name}: объявлений", f"{name}: средняя цена, €", f"{name}: медиана, €", f"{name}: мин, €",
                   f"{name}: макс, €", f"{name}: самое дешёвое"]
    rows = [header]
    stats = model_stats(snapshot)
    for model in sorted(stats, key=_order):
        row = [model]
        for site in snapshot["sites"]:
            s = stats[model].get(site)
            if not s:
                row += [0, "", "", "", "", ""]
                continue
            row += [s["all"], report._num(s["mean"]), report._num(s["median"]), report._num(s["min"]),
                    report._num(s["max"]), s["cheapest"]["url"] if s["cheapest"] else ""]
        rows.append(row)
    return rows


def item_rows(snapshot):
    rows = [["Площадка", "Модель", "Цена, €", "Цена", "Валюта", "Набор", "Заголовок", "Ссылка"]]
    for i in sorted(snapshot["items"], key=lambda i: (_order(i["model"]), i["site"], i["price_eur"] or 0)):
        rows.append([SITES[i["site"]], i["model"], report._num(i["price_eur"]), report._num(i["price"]),
                     i["currency"] or "", "да" if i["bundle"] else "", i["title"], i["url"]])
    return rows


def load_all(root):
    """Snapshots in the data repo, oldest first."""
    folder = Path(root) / "snapshots"
    if not folder.is_dir():
        return []
    return [json.loads(p.read_text("utf-8")) for p in sorted(folder.glob("*.json"))]


def sheet_titles(snapshot):
    day = "{2}.{1}.{0}".format(*snapshot["date"].split("-"))
    return f"Срез {day}", f"Объявления {day}"


def write(writer, snapshots, written):
    """Sheets of the snapshots not written yet (their dates in `written`). Returns the dates written."""
    done = []
    for snap in snapshots:
        if snap["date"] in written:
            continue
        summary, listings = sheet_titles(snap)
        writer.replace(summary, summary_rows(snap), links=True)
        writer.replace(listings, item_rows(snap), links=True)
        done.append(snap["date"])
    return done
