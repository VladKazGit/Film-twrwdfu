"""Sheets of the lens spreadsheet ('Лист1' is the user's list and stays as it is):

'Объективы' - every lens tracked; 'Продажи' - the sold ones, newest sale first; 'Сводка' - per model:
how many, on sale now, sold, mean / median / lowest / highest asking price, mean sale price, how long
they take to sell, how long the unsold ones hang, the cheapest one on sale now; 'Модели' - the models
and their Vinted searches; 'Запуски' - one row per check, newest on top; 'Без деталей' - listings
with a word of the list whose title and description do not tell the model (photo, title, price,
link); 'Ручная разметка' - the user's: id or link -> model (it wins over the rules).
Lenses sold for parts, sets of several lenses and placeholder prices stay out of the prices.
"""
import re
import statistics

from . import clock, lenses, report, sheets

ITEMS_SHEET, SALES_SHEET, SUMMARY_SHEET, MODELS_SHEET, RUNS_SHEET = (
    "Объективы", "Продажи", "Сводка", "Модели", "Запуски")
UNCLEAR_SHEET, MANUAL_SHEET = "Не разобрано", "Ручная разметка"
OLD_UNCLEAR_SHEET = "Без деталей"  # the first name of 'Не разобрано'
UNCLEAR_HEADER = ["Фото", "Почему", "Заголовок", "Цена, €", "Байонет", "Статус", "Впервые увиден",
                  "Начало описания", "id", "Ссылка", "Комментарий"]
COMMENT_HEADER = "Комментарий"  # the user's; kept by id when the sheet is rewritten (and in the data)
SET_REASON = "несколько объективов в объявлении — чья цена, не понять"
MANUAL_HEADER = ["id или ссылка", "Модель", "Комментарий"]
# 'да': a listing first seen in the last 12 hours (not one the first collection found); the row is light
# green 3 (a conditional format on this column, added once)
NEW_HEADER = "Новая (12 ч)"
NEW_HOURS = 12
ITEMS_HEADER = ["Модель", "Байонет", "Заголовок", "Статус", "Цена старт, €", "Цена сейчас, €", "Сохранений",
                "Выставлен на Vinted", "Впервые увиден", "Последний раз активен", "Продажа обнаружена", "В продаже",
                "Состояние", "Флаги", "id", "Ссылка", NEW_HEADER]
SALES_HEADER = ["Модель", "Байонет", "Цена продажи, €", "История цены, €", "Выставлен", "Продан", "В продаже",
                "Состояние", "Сохранений", "Описание (начало)", "Ссылка"]
SUMMARY_HEADER = ["Модель", "Байонет", "Всего было", "В продаже", "Продано", "Удалено", "Средняя цена объявлений, €",
                  "Медиана цены объявлений, €", "Мин, €", "Макс, €", "Средняя цена продажи, €", "Мин продажи, €",
                  "Макс продажи, €", "Продали за (медиана)", "Непроданные висят (в среднем)", "Самое дешёвое сейчас"]
MODELS_HEADER = ["Модель", "Байонет", "Поиск на Vinted"]
RUNS_HEADER = ["Время", "Новых", "Найдено первым сбором", "Страниц объявлений", "Продано", "Удалено",
               "Резерв / скрыто", "Отложено", "В продаже всего", "Всего в базе", "Первый сбор", "Запросов", "Ошибки"]
FLAG_RU = {"preexisting": "было до запуска", "parts?": "на запчасти?", "set?": "набор?"}
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
    """In the price statistics: not for parts, not a set of lenses, not a placeholder price."""
    return not {"parts?", "set?"} & set(card.get("flags") or []) and not report.placeholder_price(card)


def is_lens(card):
    return card.get("kind", "lens") == "lens" and card.get("model")


def _flags(card):
    return ", ".join(FLAG_RU.get(f, f) for f in card.get("flags") or [])


def is_new(card, now):
    """First seen in the last 12 hours as a new listing (not found by the first collection)."""
    return "preexisting" not in (card.get("flags") or []) and clock.minutes_between(card["first_seen"], now) < NEW_HOURS * 60


def _newest_first(cards):
    """Newest listings first: Vinted's ids grow with time."""
    return sorted(cards, key=lambda c: c["id"], reverse=True)


def item_rows(cards, now):
    rows = [ITEMS_HEADER]
    for c in _newest_first(cards):
        rows.append([c["model"], c.get("mount") or "", c["title"], report.STATUS_RU.get(c["status"], c["status"]),
                     _num(c.get("price_start")), _num(report.current_price(c)), _num(c.get("favourites")),
                     c.get("vinted_listed_est") or "", c["first_seen"], c.get("last_seen_active") or "",
                     c.get("sold_detected_at") or "", report.format_on_sale(days_on_sale(c, now)),
                     c.get("condition") or "", _flags(c), c["id"], c["url"], "да" if is_new(c, now) else ""])
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


def unclear_rows(cards):
    from . import photos

    rows = [UNCLEAR_HEADER]
    todo = [c for c in cards if not c.get("closed_at") and c.get("model_source") != "manual"
            and (c.get("kind") == "unclear" or "set?" in (c.get("flags") or []))]
    for c in sorted(todo, key=lambda c: c["first_seen"], reverse=True):
        why = (c.get("unclear_reason") or "нет фокусного — модель не понять") if c.get("kind") == "unclear" else SET_REASON
        rows.append([photos.image_formula(c.get("photo")), why, c["title"], _num(report.current_price(c)),
                     c.get("mount") or "", report.STATUS_RU.get(c["status"], c["status"]), c["first_seen"],
                     " ".join((c.get("description") or "").split())[:DESCRIPTION_LIMIT], c["id"], c["url"],
                     c.get("comment") or ""])
    return rows


def unclear_comments(writer):
    """{item id: the user's comment} on 'Не разобрано' as it is now ('' where cleared)."""
    if not writer.has(UNCLEAR_SHEET):
        return {}
    rows = writer._get(UNCLEAR_SHEET).get_all_values()
    if not rows or COMMENT_HEADER not in rows[0] or "id" not in rows[0]:
        return {}
    at, key = rows[0].index(COMMENT_HEADER), rows[0].index("id")
    out = {}
    for row in rows[1:]:
        if len(row) > key and row[key].strip().isdigit():
            out[int(row[key])] = row[at].strip() if len(row) > at else ""
    return out


def manual_labels(writer):
    """{item id: model} from 'Ручная разметка' (created with its header if missing)."""
    ws = writer._get(MANUAL_SHEET, MANUAL_HEADER)
    labels = {}
    for row in ws.get_all_values()[1:]:
        if len(row) < 2 or not row[1].strip():
            continue
        match = re.search(r"(?:items/)?(\d{6,})", row[0])
        if match:
            labels[int(match.group(1))] = row[1].strip()
    return labels


CANON_SHEET = "Для Canon TX / AV-1 / FTb QL"
OLD_CANON_SHEETS = ("Для Canon TX / AV-1",)  # its first name
# Which of the cameras a lens fits: FD on all three at full aperture; FL with stop-down metering.
CANON_FIT = {"Canon FD": "Canon TX, AV-1, FTb QL",
             "Canon FL": "Canon TX, FTb QL, AV-1 — замер на рабочей диафрагме"}
CANON_MOUNTS = tuple(CANON_FIT)
CANON_HEADER = ["Модель", "Байонет", "Подходит к камерам", "Заголовок", "Цена, €", "Выставлен на Vinted", "Состояние",
                "Сохранений", "Флаги", "Ссылка", NEW_HEADER]


def canon_rows(cards, now):
    """'Для Canon TX / AV-1 / FTb QL': the lenses on sale now that fit them (Canon FD and FL) and which
    camera each fits, newest listings first. The statistics are in 'Сводка'."""
    on_sale = _newest_first(c for c in cards if c.get("mount") in CANON_MOUNTS and c["status"] == "active")
    return [CANON_HEADER] + [[c["model"], c.get("mount") or "", CANON_FIT.get(c.get("mount"), ""), c["title"],
                              _num(report.current_price(c)), c.get("vinted_listed_est") or "", c.get("condition") or "",
                              _num(c.get("favourites")), _flags(c), c["url"], "да" if is_new(c, now) else ""]
                             for c in on_sale]


def color_new_rows(writer, headers):
    """Light green 3 rows where 'Новая (12 ч)' says 'да', on each sheet of {title: header}: a conditional
    format (it survives the rewrites), added once - unless the sheet has it already."""
    meta = writer.spreadsheet.fetch_sheet_metadata(
        params={"fields": "sheets(properties(title),conditionalFormats)"})
    formulas = {s["properties"]["title"]: {v.get("userEnteredValue") for rule in s.get("conditionalFormats", [])
                                           for v in rule.get("booleanRule", {}).get("condition", {}).get("values", [])}
                for s in meta.get("sheets", [])}
    for title, header in headers.items():
        column = header.index(NEW_HEADER)
        if f'=${sheets.column_letter(column)}2="да"' not in formulas.get(title, set()):
            writer.color_new_rows(title, column, len(header), 0, sheets.LIGHT_GREEN_3)


def write(writer, cards, run, add_run=True):
    """Every tracker sheet of the lens spreadsheet; add_run: a row in 'Запуски' (not for a sheets-only update)."""
    now = run["at"]
    unclear = unclear_rows(cards)
    cards = [c for c in cards if is_lens(c)]
    for old in OLD_CANON_SHEETS:
        if writer.has(old):
            writer.delete(old)
    writer.replace(CANON_SHEET, canon_rows(cards, now), links=True)
    writer.replace(ITEMS_SHEET, item_rows(cards, now), links=True)
    try:  # cosmetic: a failure must not fail the check
        color_new_rows(writer, {ITEMS_SHEET: ITEMS_HEADER, CANON_SHEET: CANON_HEADER})
    except Exception as exc:
        print(f"lens sheets: new-row colours not applied: {type(exc).__name__}")
    if writer.has(OLD_UNCLEAR_SHEET):
        writer.delete(OLD_UNCLEAR_SHEET)
    writer.replace(UNCLEAR_SHEET, unclear, links=True)
    try:  # the rows as tall as row 2 (the first one under the header): the user sets it for the photos
        height = writer.row_height(UNCLEAR_SHEET, 2)
        if height:
            writer.set_row_height(UNCLEAR_SHEET, height)
    except Exception as exc:
        print(f"lens sheets: row heights not set: {type(exc).__name__}")
    writer.replace(SALES_SHEET, sales_rows(cards, now), links=True)
    writer.replace(SUMMARY_SHEET, summary_rows(cards, now), links=True)
    writer.replace(MODELS_SHEET, model_rows())
    if add_run:
        writer._get(RUNS_SHEET, RUNS_HEADER).insert_row(runs_row(run), index=2, value_input_option="RAW")
