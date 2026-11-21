"""Push alerts to the phone (Firebase Cloud Messaging, HTTP v1): the same cameras as the e-mail letter.

Data-only messages to the topic TOPIC: the Android app (a separate project, not in this repository)
builds its own notification and keeps the last package with its links and photos. Secret:
FCM_SERVICE_ACCOUNT (the JSON key of a service account with the Firebase Cloud Messaging role).
Without it nothing is sent. Failures are logged as type names only (the repository is public).
"""
import json
import os
from html import escape

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from . import report

TOPIC = "vinted-alerts"
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
TIMEOUT_S = 15

_creds = None
_project = None


def configured():
    return bool(os.environ.get("FCM_SERVICE_ACCOUNT", "").strip())


def _access():
    """(project id, bearer token); the token is refreshed by google-auth when it runs out."""
    global _creds, _project
    if _creds is None:
        info = json.loads(os.environ["FCM_SERVICE_ACCOUNT"])
        _creds = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
        _project = info["project_id"]  # kept apart: the credentials object has no settable project_id
    if not _creds.valid:
        _creds.refresh(Request())
    return _project, _creds.token


def _sales(item, stats):
    """The model's sales in the data: [line, ...] and the time to sell, as in the letter."""
    model = item.get("model") or ""
    if model not in stats:
        return ["Продажи модели в базе пока нет"], None
    n, mean, low, high, days = stats[model]
    spread = f", от {report._price_text(low)} до {report._price_text(high)} €" if n > 1 else ""
    lines = [f"Продажи в среднем {mean} €{spread}, продаж: {n}"]
    return lines, days


def text(item, stats, letter):
    """Title and short body for the notification."""
    model = item.get("model") or "камера"
    price = report.current_price(item)
    title = f"{letter}: {model}" + (f" — {report._price_text(price)} €" if price is not None else "")
    lines, days = _sales(item, stats)
    if days is not None:
        lines.append(f"Продаётся в среднем за: {report.format_on_sale(days)}")
    return title, "\n".join(lines)


def html(item, stats, now=None):
    """The camera as in the letter's HTML part: model and price, sales, the listing link, the photo."""
    model = item.get("model") or ""
    price = report._price_text(report.current_price(item))
    url = item.get("url") or ""
    description = report._one_line(item.get("description"), 150)
    sales, days = _sales(item, stats)
    if days is not None:
        sales.append(f"Продаётся в среднем за: {report.format_on_sale(days)}")
    photo = item.get("photo")
    image = (f'<a href="{escape(url)}"><img src="{escape(photo)}" width="150" alt=""></a><br>' if photo else "")
    parts = [f"{image}<p><b>{escape(model)} — {escape(price)} €</b></p>",
             f'<p style="color:#1a7f37">{"<br>".join(escape(line) for line in sales)}</p>',
             f'<p><a href="{escape(url)}">{escape(item.get("title") or "Объявление")}</a></p>']
    if description:
        parts.append(f"<p>{escape(description)}</p>")
    if now:
        parts.append(f"<p><small>Проверка трекера: {escape(now)} (Берлин)</small></p>")
    return "".join(parts)


def send_cameras(cameras, stats, letter="Выгодно", now=None):
    """Push one data message per camera. Returns the number sent; a failed one is counted, not raised."""
    if not configured() or not cameras:
        return 0
    sent = 0
    for item in cameras:
        try:
            project, token = _access()
            title, body = text(item, stats, letter)
            lines, days = _sales(item, stats)
            when = report.format_on_sale(days) if days is not None else ""
            data = {"title": title, "body": body, "url": item.get("url") or "", "photo": item.get("photo") or "",
                    "letter": letter, "model": item.get("model") or "",
                    "price": report._price_text(report.current_price(item)),
                    "listing": item.get("title") or "", "sales": chr(10).join(lines),
                    "when": when, "description": report._one_line(item.get("description"), 150),
                    "checked": now or ""}
            message = {"topic": TOPIC, "data": {k: str(v) for k, v in data.items()}, "android": {"priority": "high"}}
            response = requests.post(ENDPOINT.format(project=project), json={"message": message},
                                     headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT_S)
            if response.status_code == 200:
                sent += 1
            else:
                print(f"push: HTTP {response.status_code}")
        except Exception as exc:  # never fails the tick; the log has no titles or ids
            print(f"push failed: {type(exc).__name__}")
    if sent:
        print(f"push: sent {sent}")
    return sent
