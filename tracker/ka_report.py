"""Sheets of the Kleinanzeigen collector (tracker.ka_tick) and the comparison with Vinted.

Kleinanzeigen spreadsheet (secret KA_SHEET_ID): 'Список' (every camera, newest listings first),
'Снятые' (taken down: sold or withdrawn - Kleinanzeigen does not tell), 'Сводка' (per model),
'Запуски' (a row per check, newest on top).
Comparison spreadsheet (secret COMPARE_SHEET_ID): 'Сравнение' - per model, Vinted next to
Kleinanzeigen: listings and their mean price, sales (taken down on Kleinanzeigen) and their mean
price, how long they were on sale; then the latest price snapshot of other marketplaces (tracker.snapshot). Both without placeholder prices, flagged listings and bundles.
By brand: Canon, Nikon, Zenit first, then the others A-Z; within a brand the most listings first.
"""
import statistics

from . import clock, models, report, sheets, snapshot
from .store import DataStore

LIST_SHEET, REMOVED_SHEET, SUMMARY_SHEET, RUNS_SHEET = "Список", "Снятые", "Сводка", "Запуски"
COMPARE_SHEET = "Сравнение"
COMPARE_BRANDS = ["Canon", "Nikon", "Zenit"]  # first in 'Сравнение', the other brands after them A-Z
NEW_HEADER = "Новая (12 ч)"
NEW_HOURS = 12
FAST_MINUTES = 30
DESCRIPTION_LIMIT = 150
STATUS_RU = {"active": "активно", "reserved": "зарезервировано", "removed": "снято"}
FLAG_RU = {"preexisting": "было до запуска", "found": "найдено поиском", "bumped": "поднято / TOP",
           "набор": "набор", "price?": "цена-заглушка?"}
LIST_HEADER = ["Модель", "Заголовок", "Статус", "Цена, €", "VB", "Цена старт, €", "Тип", "Комплект", "Состояние",
               "Выставлено", "Впервые увидено", "Последний раз активно", "Снято (обнаружено)", "В продаже",
               "Флаги", "Начало описания", "id", "Ссылка", NEW_HEADER]
REMOVED_HEADER = ["Модель", "Цена при снятии, €", "VB", "История цены, €", "Выставлено", "Снято", "Висело",
                  "Комплект", "Состояние", "Флаги", "Заголовок", "Ссылка"]
SUMMARY_HEADER = ["Модель", "Всего было", "В продаже", "Снято", "Снято < 30 мин", "Снято < 1 дня",
                  "Средняя цена объявлений, €", "Медиана цены, €", "Мин, €", "Макс, €", "Средняя цена снятых, €",
                  "Висело до снятия (медиана)", "Висят в продаже (среднее)", "Самое дешёвое сейчас"]
RUNS_HEADER = ["Время", "Новых", "Поднятых / TOP", "Первый сбор: найдено", "Найдено поиском", "Снято",
               "Зарезервировано", "Страниц типов", "Страниц поиска", "Страниц объявлений", "Отложено",
               "Открыто", "Всего", "Первый сбор", "Запросов", "Ошибки"]
COMPARE_HEADER = ["Модель", "Vinted: объявлений", "Vinted: средняя цена объявлений, €", "Vinted: продано",
                  "Vinted: средняя цена продажи, €", "Vinted: продали за (медиана)",
                  "Kleinanzeigen: объявлений", "Kleinanzeigen: средняя цена объявлений, €", "Kleinanzeigen: снято",
                  "Kleinanzeigen: средняя цена снятых, €", "Kleinanzeigen: висело до снятия (медиана)",
                  "Цена объявлений: Kleinanzeigen − Vinted, €", "То же, %", "Цена продажи: Kleinanzeigen − Vinted, €"]


def _num(value):
    return "" if value is None else value


def _mean(values):
    return round(statistics.mean(values)) if values else None


def _median(values):
    return statistics.median(values) if values else None


def listed(card):
    """When the listing went up ('YYYY-MM-DD HH:MM'; a date-only one at midnight; unknown: the first sight)."""
    at = card.get("listed_at") or card["first_seen"]
    return at if len(at) > 10 else f"{at} 00:00"


def days_on_sale(card, now):
    """Days from the listing to its taking down (the middle of [last seen, found gone]) or to now."""
    start = listed(card)
    if card.get("status") == "removed":
        seen = card.get("last_seen_active") or card["removed_detected_at"]
        mid = (clock.minutes_between(start, seen) + clock.minutes_between(start, card["removed_detected_at"])) / 2
        return max(mid, 0) / 1440
    return max(clock.minutes_between(start, now), 0) / 1440


def removed_minutes_max(card):
    """Upper estimate of the minutes on sale of a taken-down new listing (exact listing time only)."""
    if card.get("status") != "removed" or not card.get("listed_at") or len(card["listed_at"]) <= 10:
        return None
    return max(0, clock.minutes_between(card["listed_at"], card["removed_detected_at"]))


def counted(card):
    """In the price statistics: a price, not a placeholder, not a bundle, not flagged."""
    return report.current_price(card) is not None and not report.stat_flags(card) & report.SALES_EXCLUDED


def _flags(card):
    return ", ".join(FLAG_RU.get(f, f) for f in sorted(report.stat_flags(card)))


def is_new(card, now):
    return not set(card.get("flags") or []) & {"preexisting", "found", "bumped"} and \
        clock.minutes_between(card["first_seen"], now) < NEW_HOURS * 60


def _newest_first(cards):
    return sorted(cards, key=lambda c: c["id"], reverse=True)


def _description(card):
    return " ".join((card.get("description") or "").split())[:DESCRIPTION_LIMIT]


def list_rows(cards, now):
    rows = [LIST_HEADER]
    for c in _newest_first(cards):
        rows.append([c["model"], c["title"], STATUS_RU.get(c["status"], c["status"]), _num(report.current_price(c)),
                     "да" if c.get("vb") else "", _num(c.get("price_start")), c.get("type") or "",
                     report.KIT_RU.get(c.get("kit"), c.get("kit") or ""), c.get("condition") or "",
                     c.get("listed_at") or "", c["first_seen"], c.get("last_seen_active") or "",
                     c.get("removed_detected_at") or "", report.format_on_sale(days_on_sale(c, now)), _flags(c),
                     _description(c), c["id"], c["url"], "да" if is_new(c, now) else ""])
    return rows


def removed_rows(cards, now):
    rows = [REMOVED_HEADER]
    gone = sorted((c for c in cards if c["status"] == "removed"),
                  key=lambda c: (c.get("removed_detected_at") or "", c["id"]), reverse=True)
    for c in gone:
        history = " → ".join(report._price_text(p["price"]) for p in c.get("price_history") or [])
        rows.append([c["model"], _num(report.current_price(c)), "да" if c.get("vb") else "", history,
                     c.get("listed_at") or "", c["removed_detected_at"], report.format_on_sale(days_on_sale(c, now)),
                     report.KIT_RU.get(c.get("kit"), c.get("kit") or ""), c.get("condition") or "", _flags(c),
                     c["title"], c["url"]])
    return rows


def ka_model_stats(cards, now):
    """{model: {...}} of the Kleinanzeigen cards."""
    out = {}
    for c in cards:
        out.setdefault(c["model"], []).append(c)
    stats = {}
    for model, group in out.items():
        open_ = [c for c in group if c["status"] != "removed"]
        removed = [c for c in group if c["status"] == "removed"]
        prices = [report.current_price(c) for c in group if counted(c)]
        fast = [m for c in removed if not c.get("flags") and (m := removed_minutes_max(c)) is not None]
        cheapest = min((c for c in open_ if c["status"] == "active" and counted(c)), key=report.current_price,
                       default=None)
        stats[model] = {
            "total": len(group), "open": len(open_), "removed": len(removed),
            "under_30": sum(m <= FAST_MINUTES for m in fast), "under_day": sum(m <= 1440 for m in fast),
            "mean": _mean(prices), "median": _median(prices), "min": min(prices, default=None),
            "max": max(prices, default=None),
            "removed_mean": _mean([report.current_price(c) for c in removed if counted(c)]),
            "removed_days": _median([days_on_sale(c, now) for c in removed]),
            "open_days": statistics.mean([days_on_sale(c, now) for c in open_]) if open_ else None,
            "cheapest": cheapest,
        }
    return stats


def summary_rows(cards, now):
    rows = [SUMMARY_HEADER]
    stats = ka_model_stats(cards, now)
    for model, s in sorted(stats.items(), key=lambda kv: (-kv[1]["total"], kv[0])):
        rows.append([model, s["total"], s["open"], s["removed"], s["under_30"], s["under_day"], _num(s["mean"]),
                     _num(s["median"]), _num(s["min"]), _num(s["max"]), _num(s["removed_mean"]),
                     report.format_on_sale(s["removed_days"]), report.format_on_sale(s["open_days"]),
                     s["cheapest"]["url"] if s["cheapest"] else ""])
    return rows


def runs_row(run):
    return [run["at"], run["new"], run["bumped"], run["preexisting"], run["found"], run["removed"], run["reserved"],
            run["search_pages"], run["model_pages"], run["ad_pages"], run["deferred"], run["open"], run["total"],
            run["backfill"], run["requests"], "; ".join(run["errors"])[:300]]


def color_new_rows(writer):
    """Light green 3 rows of new listings (the last 12 hours) in 'Список', added once."""
    meta = writer.spreadsheet.fetch_sheet_metadata(params={"fields": "sheets(properties(title),conditionalFormats)"})
    letter = sheets.column_letter(LIST_HEADER.index(NEW_HEADER))
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == LIST_SHEET:
            values = {v.get("userEnteredValue") for rule in s.get("conditionalFormats", [])
                      for v in rule.get("booleanRule", {}).get("condition", {}).get("values", [])}
            if f'=${letter}2="да"' not in values:
                writer.color_new_rows(LIST_SHEET, LIST_HEADER.index(NEW_HEADER), len(LIST_HEADER), 0,
                                      sheets.LIGHT_GREEN_3)


def write(writer, cards, run):
    """Every sheet of the Kleinanzeigen spreadsheet and a row in 'Запуски'."""
    now = run["at"]
    writer.replace(LIST_SHEET, list_rows(cards, now), links=True)
    try:  # cosmetic: a failure must not fail the check
        color_new_rows(writer)
    except Exception as exc:
        print(f"ka sheets: new-row colours not applied: {type(exc).__name__}")
    writer.replace(REMOVED_SHEET, removed_rows(cards, now), links=True)
    writer.replace(SUMMARY_SHEET, summary_rows(cards, now), links=True)
    writer._get(RUNS_SHEET, RUNS_HEADER).insert_row(runs_row(run), index=2, value_input_option="RAW")


# ---- the comparison with Vinted


def vinted_model_stats(items):
    """{model: {...}} of Vinted's list cameras: listings and their mean price (sold: the sale price),
    sales and their mean price, the median 'продали за'."""
    out = {}
    for i in items:
        if i.get("group") != "list" or report.stat_flags(i) & report.SALES_EXCLUDED:
            continue
        s = out.setdefault(i["model"], {"total": 0, "prices": [], "sold": 0, "sale_prices": [], "days": []})
        s["total"] += 1
        price = report.current_price(i)
        if price is not None:
            s["prices"].append(price)
        if i.get("status") == "sold":
            s["sold"] += 1
            if price is not None:
                s["sale_prices"].append(price)
            if report.days_to_sell(i) is not None:
                s["days"].append(report.days_to_sell(i))
    return {m: {"total": s["total"], "mean": _mean(s["prices"]), "sold": s["sold"], "sale_mean": _mean(s["sale_prices"]),
                "days": _median(s["days"])} for m, s in out.items()}


def compare_rows(ka_cards, vinted_items, now, snap=None):
    """Vinted next to Kleinanzeigen; with a price snapshot of other marketplaces (tracker.snapshot), its
    listings and mean asking price per site at the end."""
    ka = ka_model_stats(ka_cards, now)
    vinted = vinted_model_stats(vinted_items)
    header, snap_stats = list(COMPARE_HEADER), {}
    if snap:
        day = "{2}.{1}".format(*snap["date"].split("-"))
        for site in snap["sites"]:
            header += [f"{snapshot.SITES[site]} (срез {day}): объявлений", f"{snapshot.SITES[site]} (срез {day}): средняя цена, €"]
        snap_stats = snapshot.model_stats(snap)
    rows = [header]
    names = set(ka) | set(vinted) | set(snap_stats)

    def order(name):  # by brand (Canon, Nikon, Zenit first), then the most listings first
        brand = models.MODEL_INFO.get(name, {}).get("brand") or name.split()[0]
        rank = COMPARE_BRANDS.index(brand) if brand in COMPARE_BRANDS else len(COMPARE_BRANDS)
        return (rank, brand, -((vinted.get(name) or {}).get("total", 0) + (ka.get(name) or {}).get("total", 0)), name)

    for name in sorted(names, key=order):
        v, k = vinted.get(name) or {}, ka.get(name) or {}
        diff = k["mean"] - v["mean"] if k.get("mean") is not None and v.get("mean") is not None else None
        sale_diff = (k["removed_mean"] - v["sale_mean"]
                     if k.get("removed_mean") is not None and v.get("sale_mean") is not None else None)
        rows.append([name, _num(v.get("total")), _num(v.get("mean")), _num(v.get("sold")), _num(v.get("sale_mean")),
                     report.format_on_sale(v.get("days")), _num(k.get("total")), _num(k.get("mean")),
                     _num(k.get("removed")), _num(k.get("removed_mean")), report.format_on_sale(k.get("removed_days")),
                     _num(diff), f"{round(100 * diff / v['mean']):+d} %" if diff is not None and v["mean"] else "",
                     _num(sale_diff)])
        for site in (snap or {}).get("sites", []):
            s = snap_stats.get(name, {}).get(site) or {}
            rows[-1] += [_num(s.get("all")), _num(s.get("mean"))]
    return rows


def write_compare(writer, ka_cards, root, now):
    """'Сравнение' in the comparison spreadsheet; Vinted's cameras come from the same data repo."""
    vinted = DataStore(root)
    items = list({**vinted.load_closed(), **vinted.load_active()}.values())
    snaps = snapshot.load_all(root)
    writer.replace(COMPARE_SHEET, compare_rows(ka_cards, items, now, snaps[-1] if snaps else None))
