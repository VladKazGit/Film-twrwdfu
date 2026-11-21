"""Push alerts to the phone (Firebase Cloud Messaging, HTTP v1): the same cameras as the e-mail letter.

One message per camera to the topic TOPIC; the Android app (a separate project, not in this repository)
subscribes to it. Secret: FCM_SERVICE_ACCOUNT (the JSON key of a service account with the Firebase
Cloud Messaging role). Without it nothing is sent. Failures are logged as counts only, never fail a tick.
"""
import json
import os

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from . import report

TOPIC = "vinted-alerts"
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
TIMEOUT_S = 15

_creds = None


def configured():
    return bool(os.environ.get("FCM_SERVICE_ACCOUNT", "").strip())


def _access():
    """(project id, bearer token); the token is refreshed by google-auth when it runs out."""
    global _creds
    if _creds is None:
        info = json.loads(os.environ["FCM_SERVICE_ACCOUNT"])
        _creds = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
        _creds.project_id = info["project_id"]
    if not _creds.valid:
        _creds.refresh(Request())
    return _creds.project_id, _creds.token


def text(item, stats, letter):
    """Title and body for one camera: model and price, the model's sales, the listing's age and source."""
    model = item.get("model") or "камера"
    price = report.current_price(item)
    title = f"{letter}: {model}" + (f" — {report._price_text(price)} €" if price is not None else "")
    lines = []
    if model in stats:
        n, mean, low, high, days = stats[model]
        spread = f" (от {report._price_text(low)} до {report._price_text(high)} €)" if n > 1 else ""
        lines.append(f"Продажи в среднем {mean} €{spread}, продаж: {n}")
        if days is not None:
            lines.append(f"Продаётся в среднем за: {report.format_on_sale(days)}")
    else:
        lines.append("Продаж модели в базе пока нет")
    desc = (item.get("description") or "").replace("\n", " ").strip()[:150]
    if desc:
        lines.append(desc)
    return title, "\n".join(line for line in lines if line)


def send_cameras(cameras, stats, letter="Выгодно"):
    """Push one message per camera. Returns the number sent; a failed one is counted, not raised."""
    if not configured() or not cameras:
        return 0
    sent = 0
    for item in cameras:
        try:
            project, token = _access()
            title, body = text(item, stats, letter)
            message = {
                "topic": TOPIC,
                "notification": {"title": title, "body": body},
                "data": {"url": item.get("url") or "", "id": str(item.get("id") or "")},
                "android": {"priority": "high"},
            }
            if item.get("photo"):
                message["notification"]["image"] = item["photo"]
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
