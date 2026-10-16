"""Summary statistics and sheet rows (Russian labels for the user)."""
import statistics
from collections import Counter

from . import clock

# Sale time buckets by the upper estimate (time_to_sell_max), minutes.
BUCKETS = [(30, "< 30 мин"), (360, "30 мин – 6 ч"), (1440, "6–24 ч"), (10080, "1–7 дн"), (None, "> 7 дн")]
FAST_MINUTES = 30
EXCLUDED_FLAGS = {"accessory?", "digital?"}
GROUP_RU = {"list": "Список", "rest": "Остальные"}

STATUS_RU = {
    "active": "активен", "reserved": "зарезервирован", "hidden": "скрыт", "sold": "продан",
    "deleted": "удалён", "unsold_3h": "не продан за 3 ч", "unsold_30d": "не продан за 30 дн",
}
MECH_RU = {"mechanical": "механическая", "electronic": "полуавтомат / электронная"}
REGION_RU = {"Japan": "Япония", "Europe": "Европа", "Eastern Bloc": "Восточный блок"}
FORMAT_RU = {"35mm": "35 мм", "medium": "средний"}
KIT_RU = {"body": "тушка", "with_lens": "с объективом", "extras": "с аксессуарами", "unklar": "неясно"}
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

    New listings start at the tick before they first showed up (upper
    estimate, as in the buckets); old, bumped and preexisting ones at Vinted's
    own upload date ('Hochgeladen'), which is coarse (weeks, months).
    """
    if item.get("status") != "sold" or not item.get("sold_detected_at"):
        return None
    if item.get("listed_after") and not set(item.get("flags") or []) & {"preexisting", "found", "bumped"}:
        start = item["listed_after"]
    elif item.get("vinted_listed_est"):
        start = f"{item['vinted_listed_est']} 00:00"
    else:
        return None
    return round(max(0, clock.minutes_between(start, item["sold_detected_at"])) / 1440, 2)


def _plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


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


def fast_confidence(item):
    """'точно' / 'возможно' if a sold camera may have sold within 30 minutes, else None.

    'точно': upper estimate <= 30 min. 'возможно': lower estimate < 30 min
    (late GitHub runs widen the upper estimate).
    """
    flags = set(item.get("flags") or [])
    if item.get("status") != "sold" or flags & (EXCLUDED_FLAGS | {"preexisting", "night", "found"}):
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
    """'Быстрые продажи': sold cameras that may have sold within 30 minutes, newest sale first."""
    fast = sorted((i for i in items if fast_confidence(i)),
                  key=lambda i: (i.get("sold_detected_at") or "", i["id"]), reverse=True)
    header = ITEM_HEADER + ["Группа", "Уверенность"]
    return [header] + [item_row(i) + [GROUP_RU.get(i.get("group"), ""), fast_confidence(i)] for i in fast]


def item_row(item):
    return [
        item["id"], item.get("model") or "", item.get("title") or "",
        STATUS_RU.get(item.get("status"), item.get("status") or ""),
        _num(item.get("price_start")), _num(item.get("price_final")), _num(item.get("favourites")),
        item.get("listed_after") or "", item.get("first_seen") or "", item.get("uploaded_ago") or "",
        item.get("last_seen_active") or "",
        item.get("sold_detected_at") or "", _num(item.get("time_to_sell_min")), _num(item.get("time_to_sell_max")),
        format_days(days_to_sell(item)),
        bucket(item) or "", KIT_RU.get(item.get("kit"), ""), ", ".join(item.get("kit_details") or []),
        MECH_RU.get(item.get("mech_type"), ""), FORMAT_RU.get(item.get("format"), ""),
        REGION_RU.get(item.get("region"), ""), item.get("brand") or "",
        SOURCE_RU.get(item.get("model_source"), ""), ", ".join(item.get("flags") or []),
        item.get("condition") or "", item.get("url") or "",
    ]


def item_rows(items, with_group=False):
    ordered = sorted(items, key=lambda i: (i.get("first_seen") or "", i["id"]), reverse=True)
    if with_group:
        return [ITEM_HEADER + ["Группа"]] + [item_row(i) + [GROUP_RU.get(i.get("group"), "")] for i in ordered]
    return [ITEM_HEADER] + [item_row(i) for i in ordered]


def current_price(item):
    if item.get("price_final") is not None:
        return item["price_final"]
    history = item.get("price_history") or []
    return history[-1]["price"] if history else item.get("price_start")


def cheap_cameras(items, max_price):
    """Cameras from 'Список' (not flagged accessory/digital) priced max_price or less."""
    return [i for i in items
            if i.get("group") == "list" and not set(i.get("flags") or []) & EXCLUDED_FLAGS
            and current_price(i) is not None and current_price(i) <= max_price]


def _num(value):
    return "" if value is None else value


def summarize(items, now):
    """Aggregates for 'Сводка', summary.json and README.md."""
    counted = [i for i in items if not set(i.get("flags") or []) & EXCLUDED_FLAGS]
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
                                                     "favourites": [], "days": []})
        stats["seen"] += 1
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
         "median_days_to_sell": statistics.median(s["days"]) if s["days"] else None}
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
    rows += [[], ["Модель", "Появилось", "Продано", "Продано < 30 мин", "Возможно < 30 мин",
                  "Медиана макс. времени продажи, мин", "Сохранений в среднем", "Продали за (медиана)"]]
    rows += [[m["model"], m["seen"], m["sold"], m["sold_under_30"], m["maybe_under_30"], _num(m["median_max_minutes"]),
              _num(m["mean_favourites"]), format_days(m.get("median_days_to_sell"))]
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
