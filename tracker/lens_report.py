"""Sheets of the lens spreadsheet ('Лист1' is the user's list and stays as it is):

'Объективы' - every lens tracked; 'Продажи' - the sold ones, newest sale first; 'Сводка' - per model:
how many, on sale now, sold, mean / median / lowest / highest asking price, mean sale price, how long
they take to sell, how long the unsold ones hang, the cheapest one on sale now; 'Модели' - the models
and their Vinted searches; 'Запуски' - one row per check, newest on top.
Lenses sold for parts and placeholder prices stay out of the prices.
"""
import statistics

from . import clock, lenses, report

ITEMS_SHEET, SALES_SHEET, SUMMARY_SHEET, MODELS_SHEET, RUNS_SHEET = (
    "Объективы", "Продажи", "Сводка", "Модели", "Запуски")
ITEMS_HEADER = ["Модель", "Байонет", "Заголовок", "Статус", "Цена старт, €", "Цена сейчас, €", "Сохранений",
                "Выставлен на Vinted", "Впервые увиден", "Последний раз активен", "Продажа обнаружена", "В продаже",
                "Состояние", "Флаги", "id", "Ссылка"]
SALES_HEADER = ["Модель", "Байонет", "Цена продажи, €", "История цены, €", "Выставлен", "Продан", "В продаже",
                "Состояние", "Сохранений", "Описание (начало)", "Ссылка"]
SUMMARY_HEADER = ["Модель", "Байонет", "Всего было", "В продаже", "Продано", "Удалено", "Средняя цена объявлений, €",
                  "Медиана цены объявлений, €", "Мин, €", "Макс, €", "Средняя цена продажи, €", "Мин продажи, €",
                  "Макс продажи, €", "Продали за (медиана)", "Непроданные висят (в среднем)", "Самое дешёвое сейчас"]
MODELS_HEADER = ["Модель", "Байонет", "Поиск на Vinted"]
RUNS_HEADER = ["Время", "Новых", "Найдено первым сбором", "Страниц объявлений", "Продано", "Удалено",
               "Резерв / скрыто", "Отложено", "В продаже всего", "Всего в базе", "Первый сбор", "Запросов", "Ошибки"]
FLAG_RU = {"preexisting": "было до запуска", "parts?": "на запчасти?"}
DESCRIPTION_LIMIT = 150
OPEN = ("active", "reserved", "hidden")


def _num(value):
    return "" if value is None else value


def _listed(card):
    return f"{card['vinted_listed_est']} 00:00" if card.get("vinted_listed_est") else card["first_seen"]


def days_on_sale(card, now):
    """Days from the listing to the sale (the middle of [last seen on sale, sale found]), to its
    closing, or to now."""
    start = _listed(card)
    if card.get("status") == "sold" and card.get("sold_detected_at"):
        mid = clock.minutes_between(start, card["last_seen_active"]) + clock.minutes_between(
            card["last_seen_active"], card["sold_detected_at"]) / 2
        return max(mid, 0) / 1440
    end = card.get("closed_at") or now
    return max(clock.minutes_between(start, end), 0) / 1440


def counted(card):
    """In the price statistics: not for parts, not a placeholder price."""
    return "parts?" not in (card.get("flags") or []) and not report.placeholder_price(card)


def _flags(card):
    return ", ".join(FLAG_RU.get(f, f) for f in card.get("flags") or [])


def item_rows(cards, now):
    order = {"active": 0, "reserved": 1, "hidden": 2, "sold": 3, "deleted": 4}
    rows = [ITEMS_HEADER]
    for c in sorted(cards, key=lambda c: (c["model"], order.get(c["status"], 9), report.current_price(c) or 0)):
        rows.append([c["model"], c.get("mount") or "", c["title"], report.STATUS_RU.get(c["status"], c["status"]),
                     _num(c.get("price_start")), _num(report.current_price(c)), _num(c.get("favourites")),
                     c.get("vinted_listed_est") or "", c["first_seen"], c.get("last_seen_active") or "",
                     c.get("sold_detected_at") or "", report.format_on_sale(days_on_sale(c, now)),
                     c.get("condition") or "", _flags(c), c["id"], c["url"]])
    return rows


def sales_rows(cards, now):
    rows = [SALES_HEADER]
    sold = sorted((c for c in cards if c["status"] == "sold" and counted(c)),
                  key=lambda c: (c.get("sold_detected_at") or "", c["id"]), reverse=True)
    for c in sold:
        history = " → ".join(report._price_text(p["price"]) for p in c.get("price_history") or [])
        description = " ".join((c.get("description") or "").split())[:DESCRIPTION_LIMIT]
        rows.append([c["model"], c.get("mount") or "", _num(report.current_price(c)), history,
                     c.get("vinted_listed_est") or c["first_seen"], c.get("sold_detected_at") or "",
                     report.format_on_sale(days_on_sale(c, now)), c.get("condition") or "", _num(c.get("favourites")),
                     description, c["url"]])
    return rows


def _mean(values):
    return round(statistics.mean(values)) if values else ""


def summary_rows(cards, now):
    names = {n for n in lenses.model_names() if n not in ("SMC Takumar", "Orestor")} | {c["model"] for c in cards}
    mounts = {n: m for n, m in lenses.HELIOS.values()} | {lens.name: lens.mount for lens in lenses.LENSES}
    by_model = {}
    for c in cards:
        by_model.setdefault(c["model"], []).append(c)
        mounts.setdefault(c["model"], c.get("mount") or "")
    out = []
    for name in names:
        group = by_model.get(name, [])
        on_sale = [c for c in group if c["status"] in OPEN]
        asking = [report.current_price(c) for c in on_sale if counted(c) and report.current_price(c) is not None]
        sold = [c for c in group if c["status"] == "sold" and counted(c)]
        sale = [report.current_price(c) for c in sold if report.current_price(c) is not None]
        sold_days = [days_on_sale(c, now) for c in sold]
        hanging = [days_on_sale(c, now) for c in group if c["status"] in ("active", "hidden", "deleted")]
        cheapest = min((c for c in on_sale if c["status"] == "active" and counted(c) and report.current_price(c)),
                       key=report.current_price, default=None)
        out.append([name, mounts.get(name, ""), len(group), len(on_sale), len(sold),
                    sum(c["status"] == "deleted" for c in group), _mean(asking),
                    round(statistics.median(asking)) if asking else "", min(asking, default=""), max(asking, default=""),
                    _mean(sale), min(sale, default=""), max(sale, default=""),
                    report.format_on_sale(statistics.median(sold_days)) if sold_days else "",
                    report.format_on_sale(statistics.mean(hanging)) if hanging else "",
                    cheapest["url"] if cheapest else ""])
    out.sort(key=lambda r: (-r[4], -r[2], r[0]))
    return [["Обновлено", now, "", "Без объявлений на запчасти и цен-заглушек; «В продаже» — активные, "
             "резерв и скрытые"], [], SUMMARY_HEADER] + out


def model_rows():
    rows = [MODELS_HEADER]
    helios = ", ".join(lenses.HELIOS_QUERIES)
    for name, mount in sorted(set(lenses.HELIOS.values())):
        rows.append([name, mount, helios])
    for lens in lenses.LENSES:
        label = lens.name + (" (все фокусные)" if lens.name in ("SMC Takumar", "Orestor") else "")
        rows.append([label, lens.mount, ", ".join(lens.queries)])
    return rows


def runs_row(run):
    return [run["at"], run["new"], run["found"], run["item_pages"], run["sold"], run["deleted"], run["reserved_hidden"],
            run["deferred"], run["open"], run["total"], run["backfill"], run["requests"],
            "; ".join(run["errors"])[:300]]


def write(writer, cards, run):
    now = run["at"]
    writer.replace(ITEMS_SHEET, item_rows(cards, now), links=True)
    writer.replace(SALES_SHEET, sales_rows(cards, now), links=True)
    writer.replace(SUMMARY_SHEET, summary_rows(cards, now), links=True)
    writer.replace(MODELS_SHEET, model_rows())
    writer._get(RUNS_SHEET, RUNS_HEADER).insert_row(runs_row(run), index=2, value_input_option="RAW")
