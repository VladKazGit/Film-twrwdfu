"""E-mail alerts: a camera entered 'До 20 €' (Gmail SMTP with an app password).

'До 20 €' holds the cameras of 'Список' on sale now at 20 EUR or less whose model is in
'Модели' (new listings, old ones found by search, bumped ones and price drops alike).
One letter per tick at most lists the cameras that entered it; each camera is mailed
once. The first letter only says alerts are on (and how many cameras the sheet holds),
so switching on does not mail the whole sheet.

A letter of its own, 'Zenit 1980': a Zenit of the Moscow 1980 Olympic editions (title: '1980' or an
Olympic word; description: an Olympic word - Olympia, Olimpiadi, JO, Moskva 80, Misha...) on sale at
WATCH_MAX_PRICE or less, each camera once; no welcome letter, what matches now is mailed at once. The
same letter for Kleinanzeigen (tracker.ka_tick: its own state, Vinted's sales of the model in it).

Secrets: MAIL_USER (the Gmail address that sends), MAIL_APP_PASSWORD (its 16-letter app
password), MAIL_TO (optional; recipients separated by commas, default MAIL_USER).
Without them nothing is sent. Logs show counts only, never titles, links or addresses.
"""
import os
import re
import smtplib
from email.message import EmailMessage
from html import escape

from . import models, report
from .sheets import CHEAP_MAX_PRICE

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465
NOTIFIED_KEEP = 5000
MAIL_SKIP_BRANDS = {"Praktica", "Pentax", "Zeiss Ikon"}  # the user does not want letters about them (they stay in 'До 20 €')
MAIL_SKIP_MODELS = {"Canon T50", "Canon T60", "Canon T70"}  # the same for these models
MAIL_MARGIN = 50  # EUR: a letter only for a camera this much below its model's mean sale price, or with none known
DESCRIPTION_CHARS = 300
WATCH_MAX_PRICE = 30.0  # EUR: 'Zenit 1980' letters
# The Moscow 1980 Olympics on a Zenit (normalized text): Olympia / Olimpiadi / olympische (not Olympus),
# Jeux olympiques, JO, Misha, 'Moskva 80' and its spellings, "'80".
_OLYMPIC = (r"olymp(?!us\b)\w*|olimp\w*|jeux olympiques|\bjo\b|\bmisha\b|\bmishka\b"
            r"|\bmos(?:k|c|h)?(?:v|w|k)?a\W{0,3}(?:19)?80\b|\bmos[ck]ow\W{0,3}(?:19)?80\b"
            r"|\bmoskau\W{0,3}(?:19)?80\b|\bmoscou\W{0,3}(?:19)?80\b|\b'80\b")
_WATCH_TITLE = re.compile(rf"1980|{_OLYMPIC}")
_WATCH_DESCRIPTION = re.compile(_OLYMPIC)  # a bare '1980' in a description is the year it was made
WATCH_KEEP = 2000


def configured():
    return bool(os.environ.get("MAIL_USER", "").strip() and os.environ.get("MAIL_APP_PASSWORD", "").strip())


def cheap_now(items, state):
    """The cameras of 'До 20 €' now (the same filter as the sheet)."""
    sheet = set(state.get("models_sheet") or [])
    return [i for i in report.cheap_cameras(items, CHEAP_MAX_PRICE) if not sheet or i.get("model") in sheet]


def _origin(item):
    flags = set(item.get("flags") or [])
    if "found" in flags:
        listed = item.get("vinted_listed_est")
        return "старое объявление, найдено поиском" + (f" (выставлено ~{listed})" if listed else "")
    if "bumped" in flags:
        return "поднятое объявление"
    if "preexisting" in flags:
        return "было до запуска трекера"
    return "новое объявление"


def sale_stats(items):
    """{model: (sales, mean price, lowest, highest, mean days to sell or None)} over the sold list
    cameras in the data (without placeholder prices or flagged listings, as in the statistics)."""
    sold = {}
    for i in items:
        price = report.current_price(i)
        if (i.get("group") == "list" and i.get("status") == "sold" and price is not None
                and not report.stat_flags(i) & report.SALES_EXCLUDED):
            sold.setdefault(i.get("model"), []).append(i)
    stats = {}
    for model, cameras in sold.items():
        prices = [report.current_price(i) for i in cameras]
        days = [d for d in (report.days_to_sell(i) for i in cameras) if d is not None]
        stats[model] = (len(prices), round(sum(prices) / len(prices)), min(prices), max(prices),
                        sum(days) / len(days) if days else None)
    return stats


def _sales_lines(model, stats, where="в базе"):
    """['Продажи Zenit E в базе: в среднем 32 € (от 15 € до 60 €, продаж: 3)',
        'Продаются в среднем за: 4 дня']."""
    if model not in stats:
        return [f"Продажи {model} {where}: пока нет"]
    n, mean, low, high, days = stats[model]
    spread = f"от {report._price_text(low)} € до {report._price_text(high)} €, " if n > 1 else ""
    when = report.format_on_sale(days) if days is not None else "пока неизвестно"
    return [f"Продажи {model} {where}: в среднем {mean} € ({spread}продаж: {n})", f"Продаются в среднем за: {when}"]


def message(cameras, now, welcome_count=None, stats=None, letter="До 20 €", mark="⚡", source="Vinted",
            sales_where="в базе"):
    """The letter: subject, plain text and HTML. Each camera in paragraphs: model and price, its
    model's sales, the listing, the description. letter / mark: which mailing ('Zenit 1980'); source:
    the marketplace ('Kleinanzeigen'); sales_where: whose sales the stats are ('на Vinted')."""
    stats = stats or {}
    msg = EmailMessage()
    if welcome_count is not None:
        msg["Subject"] = "⚡ Vinted: уведомления «До 20 €» включены"
        intro = (f"Уведомления включены. Сейчас в листе «До 20 €» {welcome_count} камер(ы). Дальше письмо придёт, "
                 "когда в лист попадёт новая камера: новое объявление, найденное старое или подешевевшее до 20 €.")
        text, rows = [intro, ""], [f"<p>{escape(intro)}</p>"]
    else:
        first = cameras[0]
        price = report._price_text(report.current_price(first))
        more = f" и ещё {len(cameras) - 1}" if len(cameras) > 1 else ""
        msg["Subject"] = f"{mark} {source} «{letter}»: {first.get('model') or first.get('title', '')[:40]} — {price} €{more}"
        text, rows = [], []
    p = 'style="margin:0 0 10px 0"'
    for item in cameras:
        price = report._price_text(report.current_price(item))
        model, title, url, origin = item.get("model") or "", item.get("title") or "", item.get("url") or "", _origin(item)
        description = report._one_line(item.get("description"), DESCRIPTION_CHARS)
        sales = _sales_lines(model, stats, sales_where)
        text += [f"{model} — {price} €", origin, "", *sales, "", title, url, ""]
        if description:
            text += [description, ""]
        text.append("—" * 20)
        photo = item.get("photo")
        image = (f'<td style="vertical-align:top;padding-right:14px"><a href="{escape(url)}">'
                 f'<img src="{escape(photo)}" width="160" alt="" style="border-radius:6px"></a></td>' if photo else "")
        rows.append(f'<table style="margin:0 0 18px 0;border-bottom:1px solid #ddd;padding-bottom:12px"><tr>{image}'
                    f'<td style="vertical-align:top">'
                    f'<p {p}><b style="font-size:16px">{escape(model)} — {escape(price)} €</b><br>'
                    f'<i>{escape(origin)}</i></p>'
                    f'<p {p}><span style="color:#1a7f37">{"<br>".join(escape(line) for line in sales)}</span></p>'
                    f'<p {p}><a href="{escape(url)}">{escape(title)}</a></p>'
                    + (f'<p style="margin:0;color:#555">{escape(description)}</p>' if description else "")
                    + '</td></tr></table>')
    text.append(f"Проверка трекера: {now} (Берлин)")
    rows.append(f"<p><small>Проверка трекера: {escape(now)} (Берлин)</small></p>")
    msg.set_content("\n".join(text))
    msg.add_alternative("<html><body>" + "".join(rows) + "</body></html>", subtype="html")
    return msg


def send(msg):
    user = os.environ["MAIL_USER"].strip()
    to = [a.strip() for a in (os.environ.get("MAIL_TO") or user).split(",") if a.strip()]
    msg["From"], msg["To"] = user, ", ".join(to)
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.login(user, os.environ["MAIL_APP_PASSWORD"].strip().replace(" ", ""))
        smtp.send_message(msg)


def worth_a_letter(item, stats):
    """Not a brand or model the user left out, and priced at least MAIL_MARGIN below the model's
    mean sale price in the data - or no sale of the model known yet."""
    info = models.MODEL_INFO.get(item.get("model")) or {}
    if (info.get("brand") or item.get("brand")) in MAIL_SKIP_BRANDS or item.get("model") in MAIL_SKIP_MODELS:
        return False
    price = report.current_price(item)
    known = stats.get(item.get("model"))
    return known is None or (price is not None and price <= known[1] - MAIL_MARGIN)


def run(items, state, now, send_fn=send):
    """Mail the cameras that entered 'До 20 €' since the last letter (each once).
    Updates state; returns the number mailed, or None when mail is not set up."""
    if not configured():
        return None
    current = cheap_now(items, state)
    if not state.get("mail_welcome"):  # switched on: the sheet as it is now is the baseline
        send_fn(message([], now, welcome_count=len(current)))
        state["mail_welcome"] = now
        state["notified"] = [i["id"] for i in current][-NOTIFIED_KEEP:]
        return 0
    done = set(state.get("notified") or [])
    stats = sale_stats(items)
    # Not mailed yet: one that passes later (its model's sales change) is mailed then.
    new = sorted((i for i in current if i["id"] not in done and worth_a_letter(i, stats)),
                 key=lambda i: report.current_price(i) or 0)
    if not new:
        return 0
    send_fn(message(new, now, stats=stats))
    state["notified"] = ((state.get("notified") or []) + [i["id"] for i in new])[-NOTIFIED_KEEP:]
    return len(new)


def zenit_1980(item):
    """A Zenit of the Moscow 1980 Olympic editions: '1980' or an Olympic word in the title, an Olympic
    word in the description ('Zenit EM (Moskva ‘80 Olympic edition)', 'Zenit TTL "Edizione Olimpica"')."""
    title = models.normalize(item.get("title") or "")
    brand = (models.MODEL_INFO.get(item.get("model")) or {}).get("brand") or item.get("brand")
    if "zenit" not in title and not (item.get("group") == "list" and brand == "Zenit"):
        return False
    return bool(_WATCH_TITLE.search(title) or _WATCH_DESCRIPTION.search(models.normalize(item.get("description") or "")))


def watch_now(items):
    """'Zenit 1980' cameras on sale now at WATCH_MAX_PRICE or less (a real price, not an accessory; on
    Kleinanzeigen not one gone from the searches whose page is not checked yet - 'recheck')."""
    return [i for i in items
            if i.get("status") == "active" and not i.get("recheck") and not report.stat_flags(i) & report.EXCLUDED_FLAGS
            and report.current_price(i) is not None and report.current_price(i) <= WATCH_MAX_PRICE
            and zenit_1980(i)]


def run_watch(items, state, now, send_fn=send, source="Vinted", stats=None):
    """Mail the 'Zenit 1980' cameras at WATCH_MAX_PRICE or less not mailed yet (each once; one that gets
    cheaper later is mailed then). stats: the model's sales for the letter (default: those of `items`).
    Updates state; returns the number mailed, or None without mail."""
    if not configured():
        return None
    done = set(state.get("watch_notified") or [])
    new = sorted((i for i in watch_now(items) if i["id"] not in done), key=lambda i: report.current_price(i) or 0)
    if not new:
        return 0
    send_fn(message(new, now, stats=sale_stats(items) if stats is None else stats, letter="Zenit 1980", mark="🏅",
                    source=source, sales_where="в базе" if stats is None else "на Vinted"))
    state["watch_notified"] = ((state.get("watch_notified") or []) + [i["id"] for i in new])[-WATCH_KEEP:]
    return len(new)
