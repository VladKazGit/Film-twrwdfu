"""E-mail alerts about interesting new cameras (Gmail SMTP with an app password).

Secrets: MAIL_USER (the Gmail address that sends), MAIL_APP_PASSWORD (its 16-letter app
password), MAIL_TO (optional; recipients separated by commas, default MAIL_USER).
Without them nothing is sent. Logs show counts only, never titles, links or addresses.

One letter per tick at most, listing every new camera that is worth it (see `reason`);
each camera is mailed once.
"""
import os
import smtplib
import statistics
from datetime import timedelta
from email.message import EmailMessage
from html import escape

from . import clock, report

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465
NEW_WINDOW_MIN = 30          # only cameras first seen this recently (no flood when switched on)
CHEAP_PRICE = 20.0           # at or under: always worth a letter
DEAL_SHARE = 0.7             # at most 70 % of the model's usual price
DEAL_MIN_SAMPLES = 5         # usual price = median of the model's prices, from this many cameras
KEY_MODELS = ("Canon AE-1", "Yashica FX-3 Super 2000", "Olympus OM-10")  # every new one
EXCLUDED_FLAGS = {"accessory?", "digital?", "compact?", "found", "preexisting"}
NOTIFIED_KEEP = 3000


def configured():
    return bool(os.environ.get("MAIL_USER", "").strip() and os.environ.get("MAIL_APP_PASSWORD", "").strip())


def usual_prices(items):
    """Median price per model of the list cameras (active and closed)."""
    prices = {}
    for i in items:
        price = report.current_price(i)
        if i.get("group") == "list" and price:
            prices.setdefault(i.get("model"), []).append(price)
    return {m: statistics.median(p) for m, p in prices.items() if len(p) >= DEAL_MIN_SAMPLES}


def reason(item, usual, sheet_models):
    """Why a new camera is worth a letter ('≤ 20 €', 'на 35 % дешевле обычной …', 'ключевая модель') or None."""
    if item.get("group") != "list" or item.get("status") != "active" or EXCLUDED_FLAGS & set(item.get("flags") or []):
        return None
    model = item.get("model")
    if sheet_models and model not in sheet_models:  # 'Модели' is the user's filter
        return None
    price = report.current_price(item)
    if price is not None and price <= CHEAP_PRICE:
        return f"≤ {CHEAP_PRICE:.0f} €"
    median = usual.get(model)
    if price is not None and median and price <= DEAL_SHARE * median:
        return f"на {round(100 * (1 - price / median))} % дешевле обычной ({report._price_text(median)} €)"
    if model in KEY_MODELS:
        return "ключевая модель"
    return None


def pick(items, state, now):
    """New interesting cameras not mailed yet, as [(item, reason)], newest first."""
    done = set(state.get("notified") or [])
    since = clock.stamp(clock.parse(now) - timedelta(minutes=NEW_WINDOW_MIN))
    usual = usual_prices(items)
    sheet = set(state.get("models_sheet") or [])
    fresh = [i for i in items if i["id"] not in done and (i.get("first_seen") or "") >= since]
    found = [(i, r) for i in fresh if (r := reason(i, usual, sheet))]
    return sorted(found, key=lambda f: f[0]["first_seen"], reverse=True)


def _line(item, why):
    price = report.current_price(item)
    origin = " (поднято)" if "bumped" in (item.get("flags") or []) else ""
    return item.get("model") or "", "" if price is None else f"{report._price_text(price)} €", why, origin


def message(picked, now, welcome=False):
    """The letter: subject, plain text and HTML."""
    msg = EmailMessage()
    if picked:
        model, price, _, _ = _line(*picked[0])
        more = f" и ещё {len(picked) - 1}" if len(picked) > 1 else ""
        msg["Subject"] = f"Vinted: {model} — {price}{more}"
    else:
        msg["Subject"] = "Vinted: уведомления включены"
    text, rows = [], []
    if welcome:
        intro = ("Уведомления о камерах включены. Письмо приходит, когда появляется новая камера модели из листа "
                 f"«Модели» и она стоит ≤ {CHEAP_PRICE:.0f} €, или на {round(100 * (1 - DEAL_SHARE))} % дешевле "
                 f"обычной, или это {', '.join(KEY_MODELS)}.")
        text.append(intro + "\n")
        rows.append(f"<p>{escape(intro)}</p>")
    for item, why in picked:
        model, price, why, origin = _line(item, why)
        title, url = item.get("title") or "", item.get("url") or ""
        text.append(f"{model} — {price}{origin} ({why})\n{title}\n{url}\nвпервые: {item.get('first_seen', '')}\n")
        rows.append(f'<p><b>{escape(model)} — {escape(price)}</b>{escape(origin)} <i>({escape(why)})</i><br>'
                    f'<a href="{escape(url)}">{escape(title)}</a><br><small>впервые: {escape(item.get("first_seen", ""))}'
                    "</small></p>")
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
    """Mail the new interesting cameras once (the very first time with a short intro).
    Updates state; returns the number of cameras mailed, or None when mail is not set up."""
    if not configured():
        return None
    picked = pick(items, state, now)
    welcome = not state.get("mail_welcome")
    if not picked and not welcome:
        return 0
    send_fn(message(picked, now, welcome))
    state["mail_welcome"] = state.get("mail_welcome") or now
    state["notified"] = ((state.get("notified") or []) + [i["id"] for i, _ in picked])[-NOTIFIED_KEEP:]
    return len(picked)
