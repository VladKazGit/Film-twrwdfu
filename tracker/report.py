"""Summary statistics and sheet rows (Russian labels for the user)."""
import re
import statistics
from collections import Counter

from . import clock, models

# Sale time buckets by the upper estimate (time_to_sell_max), minutes.
BUCKETS = [(30, "< 30 мин"), (360, "30 мин – 6 ч"), (1440, "6–24 ч"), (10080, "1–7 дн"), (None, "> 7 дн")]
FAST_MINUTES = 30
EXCLUDED_FLAGS = {"accessory?", "digital?", "compact?", "price?"}
# Placeholder prices: 1 EUR, or up to 5 EUR when the seller waits for offers. Not the real price,
# so out of the statistics, 'До 20 €', 'Продажи' and the letters; worked out from the current
# price, so a camera that gets a real price comes back.
PLACEHOLDER_PRICE, OFFERS_PRICE = 1.0, 5.0
SALE_MIN_PRICE = 40.0  # 'Сводка': the mean sale price counts sales above this (no cheap or broken ones)


def placeholder_price(item):
    price = current_price(item)
    if price is None:
        return False
    return price <= PLACEHOLDER_PRICE or (price <= OFFERS_PRICE and models.asks_for_offers(item.get("description")))


def stat_flags(item):
    """The item's flags plus 'price?' for a placeholder price."""
    flags = set(item.get("flags") or [])
    return flags | {"price?"} if placeholder_price(item) else flags
GROUP_RU = {"list": "Список", "rest": "Остальные"}

STATUS_RU = {
    "active": "активен", "reserved": "зарезервирован", "hidden": "скрыт", "sold": "продан",
    "deleted": "удалён", "unsold_3h": "не продан за 3 ч", "unsold_30d": "не продан за 30 дн",
}
MECH_RU = {"mechanical": "механическая", "electronic": "полуавтомат / электронная"}
REGION_RU = {"Japan": "Япония", "Europe": "Европа", "Eastern Bloc": "Восточный блок"}
FORMAT_RU = {"35mm": "35 мм", "medium": "средний"}
KIT_RU = {"body": "тушка", "with_lens": "с объективом", "extras": "с аксессуарами", "unklar": "неясно"}
KIT_DETAILS_RU = {"lens": "объектив", "flash": "вспышка", "bag": "сумка/чехол", "strap": "ремень", "film": "плёнка",
                  "manual": "инструкция", "winder": "моторный привод", "filter": "фильтр", "box": "коробка",
                  "accessories": "аксессуары"}


def kit_details_text(item):
    return ", ".join(KIT_DETAILS_RU.get(d, d) for d in item.get("kit_details") or [])
SOURCE_RU = {"title": "заголовок", "description": "описание", "brand_only": "только бренд",
             "photo": "фото", "manual": "вручную"}

ITEM_HEADER = [
    "id", "Модель", "Заголовок", "Статус", "Цена старт", "Цена финал", "Сохранений", "Выставлен после", "Впервые",
    "Выставлен на Vinted (при обнаружении)",
    "Последний раз активен", "Продажа обнаружена", "Время продажи мин, мин", "Время продажи макс, мин", "Продали за",
    "Корзина", "Комплект", "Детали комплекта", "Тип", "Формат", "Регион", "Бренд", "Источник модели",
    "Флаги", "Состояние", "Ссылка",
]


def bucket(item):
    """Speed bucket of a sold item, or None if it has no usable estimate."""
    flags = set(item.get("flags") or [])
    if item.get("status") != "sold" or item.get("time_to_sell_max") is None or flags & {"preexisting", "night", "bumped", "found"}:
        return None
    for limit, label in BUCKETS:
        if limit is None or item["time_to_sell_max"] <= limit:
            return label
    return None


def days_to_sell(item):
    """Days from listing to the detected sale, or None.

    New listings: from the tick before they first showed up to the tick that
    found the sale (upper estimate, as in the buckets; ticks are 15 min apart).
    Old, bumped and preexisting ones: from Vinted's own upload date
    ('Hochgeladen', coarse) to the middle of [last seen active, sale detected],
    since their checks are a day or more apart.
    """
    if item.get("status") != "sold" or not item.get("sold_detected_at"):
        return None
    sold = item["sold_detected_at"]
    if item.get("listed_after") and not set(item.get("flags") or []) & {"preexisting", "found", "bumped"}:
        return round(max(0, clock.minutes_between(item["listed_after"], sold)) / 1440, 2)
    if not item.get("vinted_listed_est"):
        return None
    start = f"{item['vinted_listed_est']} 00:00"
    seen = item.get("last_seen_active") or sold
    middle = (clock.minutes_between(start, seen) + clock.minutes_between(start, sold)) / 2
    return round(max(0, middle) / 1440, 2)


def _plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


_AGE_RU = (("min", ("минуту", "минуты", "минут")), ("std", ("час", "часа", "часов")),
           ("stunde", ("час", "часа", "часов")), ("tag", ("день", "дня", "дней")),
           ("woche", ("неделю", "недели", "недель")), ("monat", ("месяц", "месяца", "месяцев")),
           ("jahr", ("год", "года", "лет")))


def uploaded_ago_ru(text):
    """Vinted's German 'Hochgeladen' text in Russian: '5 Monaten' -> '5 месяцев назад'."""
    match = re.match(r"\s*(\d+)\s*([^\W\d_]+)", text or "")
    if not match:
        return text or ""
    n, unit = int(match.group(1)), match.group(2).lower()
    for prefix, forms in _AGE_RU:
        if unit.startswith(prefix):
            return f"{n} {_plural(n, *forms)} назад"
    return text


def _vinted_age_text(item):
    """Vinted's own age in Russian, or '~3 месяца назад (оценка)' while it is estimated by id."""
    if item.get("age_source") == "id" and item.get("age_days_at_discovery") is not None:
        return f"~{format_days(item['age_days_at_discovery'])} назад (оценка)"
    return uploaded_ago_ru(item.get("uploaded_ago"))


def format_days(days):
    """'меньше дня', '3 дня', '12 дней' up to 30 days, then months: '2 месяца'."""
    if days is None:
        return ""
    if days < 1:
        return "меньше дня"
    if days <= 30:
        n = int(days)
        return f"{n} {_plural(n, 'день', 'дня', 'дней')}"
    n = max(1, round(days / 30))
    return f"{n} {_plural(n, 'месяц', 'месяца', 'месяцев')}"


def format_on_sale(days, at_least=False):
    """How long a camera was on sale: '25 мин', '5 ч', '3 дня', '2 месяца', '1 год 2 месяца';
    '≥ ...' when only a lower bound is known."""
    if days is None:
        return ""
    minutes = days * 1440
    if minutes < 60:
        text = f"{max(1, round(minutes))} мин"
    elif days < 1:
        text = f"{round(minutes / 60)} ч"
    elif days < 31:
        n = int(days)
        text = f"{n} {_plural(n, 'день', 'дня', 'дней')}"
    elif days < 365:
        n = max(1, round(days / 30.4))
        text = f"{n} {_plural(n, 'месяц', 'месяца', 'месяцев')}"
    else:
        years, months = int(days // 365), round((days % 365) / 30.4)
        if months == 12:
            years, months = years + 1, 0
        text = f"{years} {_plural(years, 'год', 'года', 'лет')}"
        if months:
            text += f" {months} {_plural(months, 'месяц', 'месяца', 'месяцев')}"
    return ("≥ " if at_least else "") + text


def on_sale_text(item):
    """'В продаже' of a sold camera; without a listing date, at least since it was first seen."""
    days = days_to_sell(item)
    if days is not None:
        return format_on_sale(days)
    if item.get("first_seen") and item.get("sold_detected_at"):
        return format_on_sale(max(0, clock.minutes_between(item["first_seen"], item["sold_detected_at"])) / 1440,
                              at_least=True)
    return ""


def fast_confidence(item):
    """'точно' / 'возможно' if a sold camera may have sold within 30 minutes, else None.

    'точно': upper estimate <= 30 min. 'возможно': lower estimate < 30 min
    (late GitHub runs widen the upper estimate).
    """
    flags = set(item.get("flags") or [])
    if item.get("status") != "sold" or stat_flags(item) & (EXCLUDED_FLAGS | {"preexisting", "night", "found"}):
        return None
    if item.get("time_to_sell_max") is not None and item["time_to_sell_max"] <= FAST_MINUTES:
        return "точно"
    if item.get("time_to_sell_min") is not None and item["time_to_sell_min"] < FAST_MINUTES:
        return "возможно"
    return None


def _maybe_fast(item):
    """'возможно < 30 мин' for the summary, which counts from listing (bumped items count from the bump)."""
    return fast_confidence(item) == "возможно" and "bumped" not in (item.get("flags") or [])


def fast_rows(items):
    """'Быстрые продажи': list cameras that may have sold within 30 minutes, newest sale first.
    Fast sales of other cameras (compacts and the like) only count in 'Сводка'."""
    fast = sorted((i for i in items if i.get("group") == "list" and fast_confidence(i)),
                  key=lambda i: (i.get("sold_detected_at") or "", i["id"]), reverse=True)
    return [ITEM_HEADER + ["Уверенность"]] + [item_row(i) + [fast_confidence(i)] for i in fast]


def item_row(item):
    return [
        item["id"], item.get("model") or "", item.get("title") or "",
        STATUS_RU.get(item.get("status"), item.get("status") or ""),
        _num(item.get("price_start")), _num(item.get("price_final")), _num(item.get("favourites")),
        item.get("listed_after") or "", item.get("first_seen") or "", _vinted_age_text(item),
        item.get("last_seen_active") or "",
        item.get("sold_detected_at") or "", _num(item.get("time_to_sell_min")), _num(item.get("time_to_sell_max")),
        format_days(days_to_sell(item)),
        bucket(item) or "", KIT_RU.get(item.get("kit"), ""), kit_details_text(item),
        MECH_RU.get(item.get("mech_type"), ""), FORMAT_RU.get(item.get("format"), ""),
        REGION_RU.get(item.get("region"), ""), item.get("brand") or "",
        SOURCE_RU.get(item.get("model_source"), ""), ", ".join(sorted(stat_flags(item))),
        item.get("condition") or "", item.get("url") or "",
    ]


NEW_HEADER = "Новая (12 ч)"
FRESH_HEADER = "Новая (3 ч)"


def is_new(item, since, old_listings=False):
    """First seen at or after `since`. Only new listings by default; with old_listings
    also old ones that just entered the sheet (found by search, bumped)."""
    excluded = {"preexisting"} if old_listings else {"preexisting", "found", "bumped"}
    return (item.get("first_seen") or "") >= since and not set(item.get("flags") or []) & excluded


def listed_key(item):
    """Sort key 'YYYY-MM-DD HH:MM' for when the camera went on sale: new and bumped listings
    by their first sighting, old ones found by search by Vinted's upload date. Hundreds of
    old cameras found in one tick must not push fresh listings down."""
    flags = set(item.get("flags") or [])
    if flags & {"found", "preexisting"} and item.get("vinted_listed_est"):
        return f"{item['vinted_listed_est']} 00:00"
    return item.get("first_seen") or ""


def item_rows(items, with_group=False, new_since=None, new_old_listings=False, fresh_since=None):
    """Item sheet rows, newest first. with_group adds 'Группа'; new_since / fresh_since add
    columns marking cameras that appeared in the last 12 / 3 hours ('да')."""
    ordered = sorted(items, key=lambda i: (listed_key(i), i["id"]), reverse=True)
    header = (ITEM_HEADER + (["Группа"] if with_group else []) + ([NEW_HEADER] if new_since else [])
              + ([FRESH_HEADER] if fresh_since else []))
    rows = [header]
    for item in ordered:
        row = item_row(item)
        if with_group:
            row.append(GROUP_RU.get(item.get("group"), ""))
        if new_since:
            row.append("да" if is_new(item, new_since, new_old_listings) else "")
        if fresh_since:
            row.append("да" if is_new(item, fresh_since, new_old_listings) else "")
        rows.append(row)
    return rows


SALES_HEADER = [
    "Модель", "Цена при продаже, €", "История цены, €", "Изменение цены", "Выставлена", "Продана", "В продаже",
    "Комплект", "Состояние", "Сохранений", "Описание (начало)", "Ссылка",
]
SALES_DESCRIPTION_LIMIT = 150  # one line per sale; the full text stays in the data repo


def _price_text(value):
    return "" if value is None else (f"{value:.0f}" if float(value).is_integer() else f"{value:.2f}")


def _listed_text(item):
    """When the listing went up: a tick window for new listings, Vinted's date (~) for old ones."""
    flags = set(item.get("flags") or [])
    if item.get("listed_after") and not flags & {"preexisting", "found", "bumped"}:
        return f"{item['listed_after']} – {item['first_seen'][11:]}"
    if item.get("vinted_listed_est"):
        return f"~{item['vinted_listed_est']}"
    return ""


def _change_text(start, final):
    """'−10 € (−7 %)'; empty when the price never changed."""
    if start is None or final is None or final == start:
        return ""
    change = final - start
    sign = "+" if change > 0 else "−"
    text = f"{sign}{_price_text(round(abs(change), 2))} €"
    return f"{text} ({sign}{abs(100 * change / start):.0f} %)" if start else text


def _kit_text(item):
    """'с объективом: вспышка, сумка/чехол' (the lens is already in the kit name)."""
    kit = item.get("kit")
    details = [KIT_DETAILS_RU.get(d, d) for d in item.get("kit_details") or [] if not (kit == "with_lens" and d == "lens")]
    return KIT_RU.get(kit, "") + (": " + ", ".join(details) if details else "")


def _one_line(text, limit):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def sales_rows(items):
    """'Продажи': sold list cameras, newest sale first, one line each."""
    sold = sorted((i for i in items if i.get("group") == "list" and i.get("status") == "sold" and not placeholder_price(i)),
                  key=lambda i: (i.get("sold_detected_at") or "", i["id"]), reverse=True)
    rows = [SALES_HEADER]
    for i in sold:
        start, final = i.get("price_start"), current_price(i)
        prices = [p["price"] for p in i.get("price_history") or [] if p.get("price") is not None]
        if final is not None and (not prices or prices[-1] != final):
            prices.append(final)
        history = " → ".join(_price_text(p) for p in prices) if len(set(prices)) > 1 else ""
        rows.append([
            i.get("model") or "", _num(final), history, _change_text(start, final),
            _listed_text(i), i.get("sold_detected_at") or "", on_sale_text(i),
            _kit_text(i), i.get("condition") or "", _num(i.get("favourites")),
            _one_line(i.get("description"), SALES_DESCRIPTION_LIMIT), i.get("url") or "",
        ])
    return rows


def current_price(item):
    if item.get("price_final") is not None:
        return item["price_final"]
    history = item.get("price_history") or []
    return history[-1]["price"] if history else item.get("price_start")


CHECK_HEADER = ["Причина", "id", "Модель", "Заголовок", "Цена", "Статус", "Источник модели",
                "Начало описания", "Ссылка"]


def check_rows(items):
    """'Проверка': rows of 'Список' that look like misrecognitions (manually labelled ones are trusted).
    Price is no sign: working cameras sell for 5-10 EUR."""
    found = []
    for i in items:
        if i.get("group") != "list" or i.get("model_source") == "manual":
            continue
        words = models.accessory_words(i.get("title") or "")
        if words:
            found.append((i, "перед моделью: " + ", ".join(words)))
    found.sort(key=lambda f: f[0].get("first_seen") or "", reverse=True)
    return [CHECK_HEADER] + [
        [reason, i["id"], i.get("model") or "", i.get("title") or "", _num(current_price(i)),
         STATUS_RU.get(i.get("status"), i.get("status") or ""), SOURCE_RU.get(i.get("model_source"), ""),
         (i.get("description") or "")[:120], i.get("url") or ""]
        for i, reason in found]


def cheap_cameras(items, max_price):
    """Cameras from 'Список' (not flagged accessory/digital) on sale now, priced max_price or
    less. Sold, deleted, reserved or hidden ones stay in 'Список' / 'Продажи' only."""
    return [i for i in items
            if i.get("group") == "list" and i.get("status") == "active"
            and not stat_flags(i) & EXCLUDED_FLAGS
            and current_price(i) is not None and current_price(i) <= max_price]


def _num(value):
    return "" if value is None else value


def unsold_days(item, now):
    """Days an unsold camera has been on sale: from its listing (Vinted's date for old ones,
    the first sight if unknown) to now, or to its closing if deleted / unsold in 30 days.
    None for sold and reserved ones."""
    status = item.get("status")
    if status not in ("active", "hidden", "deleted", "unsold_30d"):
        return None
    flags = set(item.get("flags") or [])
    if item.get("listed_after") and not flags & {"preexisting", "found", "bumped"}:
        start = item["listed_after"]
    elif item.get("vinted_listed_est"):
        start = f"{item['vinted_listed_est']} 00:00"
    else:
        start = item.get("first_seen")
    end = now if status in ("active", "hidden") else (item.get("closed_at") or item.get("last_seen_active") or now)
    return round(max(0, clock.minutes_between(start, end)) / 1440, 2) if start else None


def summarize(items, now):
    """Aggregates for 'Сводка', summary.json and README.md."""
    counted = [i for i in items if not stat_flags(i) & EXCLUDED_FLAGS]
    groups = {"list": [i for i in counted if i.get("group") == "list"],
              "rest": [i for i in counted if i.get("group") == "rest"]}
    totals = {}
    for name, group in groups.items():
        status = Counter(i.get("status") for i in group)
        flags = Counter(f for i in group for f in i.get("flags") or [])
        totals[name] = {
            "tracked": len(group),
            "active": status["active"] + status["reserved"] + status["hidden"],
            "sold": status["sold"],
            "deleted": status["deleted"],
            "unsold_3h": status["unsold_3h"],
            "unsold_30d": status["unsold_30d"],
            "preexisting": flags["preexisting"],
            "night": flags["night"],
            "bumped": flags["bumped"],
            "found": flags["found"],
            "buckets": {label: sum(bucket(i) == label for i in group) for _, label in BUCKETS},
            "sold_without_estimate": sum(i.get("status") == "sold" and bucket(i) is None for i in group),
            "fast_maybe": sum(_maybe_fast(i) for i in group),
        }
    per_model = {}
    for item in groups["list"]:
        stats = per_model.setdefault(item["model"], {"seen": 0, "sold": 0, "fast": 0, "maybe": 0, "times": [],
                                                     "favourites": [], "days": [], "unsold_days": [], "prices": [], "sale_prices": []})
        stats["seen"] += 1
        if current_price(item) is not None:
            stats["prices"].append(current_price(item))  # sold: the sale price
            if item.get("status") == "sold" and current_price(item) > SALE_MIN_PRICE:
                stats["sale_prices"].append(current_price(item))
        if unsold_days(item, now) is not None:
            stats["unsold_days"].append(unsold_days(item, now))
        if item.get("favourites") is not None:
            stats["favourites"].append(item["favourites"])
        if item.get("status") == "sold":
            stats["sold"] += 1
            if days_to_sell(item) is not None:
                stats["days"].append(days_to_sell(item))
            if bucket(item):
                stats["times"].append(item["time_to_sell_max"])
            if bucket(item) == BUCKETS[0][1]:
                stats["fast"] += 1
            elif _maybe_fast(item):
                stats["maybe"] += 1
    models = [
        {"model": model, "seen": s["seen"], "sold": s["sold"], "sold_under_30": s["fast"], "maybe_under_30": s["maybe"],
         "median_max_minutes": statistics.median(s["times"]) if s["times"] else None,
         "mean_favourites": round(statistics.mean(s["favourites"]), 1) if s["favourites"] else None,
         "median_days_to_sell": statistics.median(s["days"]) if s["days"] else None,
         "mean_unsold_days": round(statistics.mean(s["unsold_days"]), 2) if s["unsold_days"] else None,
         "mean_price": round(statistics.mean(s["prices"])) if s["prices"] else None,
         "mean_sale_price": round(statistics.mean(s["sale_prices"])) if s["sale_prices"] else None}
        for model, s in per_model.items()
    ]
    models.sort(key=lambda m: (-m["sold_under_30"], -m["maybe_under_30"], -m["sold"], -m["seen"], m["model"]))
    return {"updated": now, "excluded_flagged": len(items) - len(counted), "groups": totals, "models": models}


TOTAL_ROWS = [
    ("tracked", "Отслежено всего"), ("active", "Сейчас активны (вкл. резерв/скрытые)"), ("sold", "Продано"),
    ("deleted", "Удалено"), ("unsold_3h", "Не продано за 3 ч"), ("unsold_30d", "Не продано за 30 дн"),
    ("preexisting", "preexisting (были до старта)"), ("night", "night (выставлены ночью)"),
    ("bumped", "bumped (поднятые старые объявления)"),
    ("found", "found (старые дешёвые, найдены поиском)"),
]


TOP_N = 10


def top_rows(items, now):
    """'Топ-10': the models sold most often, the models with the highest sale prices and the most
    expensive sales. List cameras only, without placeholder prices or flagged listings; sale
    prices count above SALE_MIN_PRICE (no cheap, broken or parts-only sales)."""
    counted = [i for i in items if i.get("group") == "list" and not stat_flags(i) & EXCLUDED_FLAGS]
    by_model = {}
    for item in counted:
        by_model.setdefault(item.get("model"), []).append(item)
    stats = []
    for model, cameras in by_model.items():
        sold = [i for i in cameras if i.get("status") == "sold"]
        if not sold:
            continue
        all_prices = [p for p in (current_price(i) for i in sold) if p is not None]
        prices = [p for p in all_prices if p > SALE_MIN_PRICE]
        days = [d for d in (days_to_sell(i) for i in sold) if d is not None]
        stats.append({"model": model, "sold": len(sold), "seen": len(cameras),
                      "share": round(100 * len(sold) / len(cameras)),
                      "mean": round(statistics.mean(prices)) if prices else None,
                      "mean_all": round(statistics.mean(all_prices)) if all_prices else None,
                      "max": max(prices) if prices else None, "priced": len(prices),
                      "days": statistics.median(days) if days else None})
    above = f"> {SALE_MIN_PRICE:.0f} €"
    rows = [["Обновлено", now], [],
            [f"Топ-{TOP_N}: чаще всего продаются"],
            ["Модель", "Продано", "Всего было в продаже", "Продано, %", "Средняя цена продажи (все), €",
             f"Средняя цена продажи ({above}), €", "Продали за (медиана)"]]
    for m in sorted(stats, key=lambda m: (-m["sold"], -m["share"], m["model"]))[:TOP_N]:
        rows.append([m["model"], m["sold"], m["seen"], m["share"], _num(m["mean_all"]), _num(m["mean"]),
                     format_on_sale(m["days"])])
    rows += [[], [f"Топ-{TOP_N}: самые дорогие модели (средняя цена продажи {above})"],
             ["Модель", f"Средняя цена продажи ({above}), €", "Средняя цена продажи (все), €", "Самая высокая, €",
              f"Продаж {above}", "Продано всего"]]
    priced = [m for m in stats if m["mean"] is not None]
    for m in sorted(priced, key=lambda m: (-m["mean"], m["model"]))[:TOP_N]:
        rows.append([m["model"], m["mean"], _num(m["mean_all"]), _num(m["max"]), m["priced"], m["sold"]])
    rows += [[], [f"Топ-{TOP_N}: самые дорогие проданные камеры"],
             ["Модель", "Цена продажи, €", "Продана", "В продаже", "Заголовок", "Ссылка"]]
    sales = [i for i in counted if i.get("status") == "sold" and current_price(i) is not None]
    for i in sorted(sales, key=lambda i: (-current_price(i), i["id"]))[:TOP_N]:
        rows.append([i.get("model") or "", current_price(i), i.get("sold_detected_at") or "", on_sale_text(i),
                     i.get("title") or "", i.get("url") or ""])
    width = max(len(r) for r in rows)
    return [r + [""] * (width - len(r)) for r in rows]


def summary_rows(summary):
    lst, rest = summary["groups"]["list"], summary["groups"]["rest"]
    rows = [["Обновлено", summary["updated"]],
            ["Исключено из статистики (аксессуары/цифровые)", summary["excluded_flagged"]],
            [],
            ["Показатель", "Список", "Остальные"]]
    rows += [[label, lst[key], rest[key]] for key, label in TOTAL_ROWS]
    rows += [[], ["Время продажи (верхняя оценка)", "Список", "Остальные"]]
    rows += [[label, lst["buckets"][label], rest["buckets"][label]] for _, label in BUCKETS]
    rows += [["Возможно < 30 мин (по нижней оценке)", lst["fast_maybe"], rest["fast_maybe"]]]
    rows += [["Продано без оценки (preexisting/night/bumped/found)", lst["sold_without_estimate"], rest["sold_without_estimate"]]]
    rows += [[], ["Модель", "Появилось", "Продано", "Средняя цена, €", f"Средняя цена продажи (> {SALE_MIN_PRICE:.0f} €), €",
                  "Продано < 30 мин", "Возможно < 30 мин",
                  "Медиана макс. времени продажи, мин", "Сохранений в среднем", "Продали за (медиана)",
                  "Непроданные висят (в среднем)"]]
    rows += [[m["model"], m["seen"], m["sold"], _num(m.get("mean_price")), _num(m.get("mean_sale_price")),
              m["sold_under_30"], m["maybe_under_30"],
              _num(m["median_max_minutes"]),
              _num(m["mean_favourites"]), format_on_sale(m.get("median_days_to_sell")),
              format_on_sale(m.get("mean_unsold_days"))]
             for m in summary["models"]]
    width = max(len(r) for r in rows)
    return [r + [""] * (width - len(r)) for r in rows]


def readme(summary):
    """Markdown version of the summary for the data repo."""
    lines = ["# Film camera tracker: summary", "", f"Updated: {summary['updated']} (Berlin)", ""]
    table = summary_rows(summary)
    blocks, block = [], []
    for row in table[2:]:
        if not any(str(c) for c in row):
            if block:
                blocks.append(block)
            block = []
        else:
            block.append([str(c) for c in row if str(c) != ""] if not block else [str(c) for c in row])
    if block:
        blocks.append(block)
    for block in blocks:
        width = len(block[0])
        lines.append("| " + " | ".join(block[0]) + " |")
        lines.append("|" + "---|" * width)
        lines += ["| " + " | ".join(r[:width]) + " |" for r in block[1:]]
        lines.append("")
    return "\n".join(lines)
