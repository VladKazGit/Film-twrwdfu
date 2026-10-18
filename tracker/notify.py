"""E-mail alerts: a camera entered 'До 20 €' (Gmail SMTP with an app password).

'До 20 €' holds the cameras of 'Список' on sale now at 20 EUR or less whose model is in
'Модели' (new listings, old ones found by search, bumped ones and price drops alike).
One letter per tick at most lists the cameras that entered it; each camera is mailed
once. The first letter only says alerts are on (and how many cameras the sheet holds),
so switching on does not mail the whole sheet.

Secrets: MAIL_USER (the Gmail address that sends), MAIL_APP_PASSWORD (its 16-letter app
password), MAIL_TO (optional; recipients separated by commas, default MAIL_USER).
Without them nothing is sent. Logs show counts only, never titles, links or addresses.
"""
import os
import smtplib
from email.message import EmailMessage
from html import escape

from . import report
from .sheets import CHEAP_MAX_PRICE

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465
NOTIFIED_KEEP = 5000
DESCRIPTION_CHARS = 300


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


def message(cameras, now, welcome_count=None):
    """The letter: subject, plain text and HTML."""
    msg = EmailMessage()
    if welcome_count is not None:
        msg["Subject"] = "Vinted: уведомления «До 20 €» включены"
        intro = (f"Уведомления включены. Сейчас в листе «До 20 €» {welcome_count} камер(ы). Дальше письмо придёт, "
                 "когда в лист попадёт новая камера: новое объявление, найденное старое или подешевевшее до 20 €.")
        text, rows = [intro], [f"<p>{escape(intro)}</p>"]
    else:
        first = cameras[0]
        price = report._price_text(report.current_price(first))
        more = f" и ещё {len(cameras) - 1}" if len(cameras) > 1 else ""
        msg["Subject"] = f"Vinted «До 20 €»: {first.get('model', '')} — {price} €{more}"
        text, rows = [], []
    for item in cameras:
        price = report._price_text(report.current_price(item))
        model, title, url, origin = item.get("model") or "", item.get("title") or "", item.get("url") or "", _origin(item)
        description = report._one_line(item.get("description"), DESCRIPTION_CHARS)
        text.append(f"{model} — {price} € ({origin})\n{title}\n{description}\n{url}\n".replace("\n\n", "\n"))
        photo = item.get("photo")
        image = (f'<td style="vertical-align:top;padding-right:12px"><a href="{escape(url)}">'
                 f'<img src="{escape(photo)}" width="160" alt="" style="border-radius:6px"></a></td>' if photo else "")
        rows.append(f'<table style="margin:0 0 16px 0"><tr>{image}<td style="vertical-align:top">'
                    f'<b>{escape(model)} — {escape(price)} €</b> <i>({escape(origin)})</i><br>'
                    f'<a href="{escape(url)}">{escape(title)}</a><br>'
                    f'<span style="color:#555">{escape(description)}</span></td></tr></table>')
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
    new = sorted((i for i in current if i["id"] not in done), key=lambda i: report.current_price(i) or 0)
    if not new:
        return 0
    send_fn(message(new, now))
    state["notified"] = ((state.get("notified") or []) + [i["id"] for i in new])[-NOTIFIED_KEEP:]
    return len(new)
