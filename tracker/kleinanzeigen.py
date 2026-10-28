"""Kleinanzeigen (kleinanzeigen.de) pages for the camera collector (tracker.ka_tick).

Public pages only, no account: the newest listings of the category Foto (c245) of type 'Kamera' and
'Kamera & Zubehör', and a listing's own page. Single-threaded, 2-3 s between requests. Kleinanzeigen
has no 'sold': a listing taken down redirects to the category - sold or withdrawn, nobody can tell.

Search result items carry the title, the whole description and the photo in a JSON block, then the
listing time ('Heute, 10:47', 'Gestern, 18:02', '27.10.2026') and the price ('140 € VB', 'VB',
'Zu verschenken'; a reduced one shows the old price struck through).
"""
import json
import random
import re
import time
from datetime import timedelta

import requests

from . import clock

BASE_URL = "https://www.kleinanzeigen.de"
CATEGORY = "c245"  # Foto
TYPES = {"camera": "Kamera", "camera_and_equipment": "Kamera & Zubehör"}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")
RETRY_BACKOFF = (10, 30)
FAILURES_IN_ROW_BLOCK = 3


class KaError(RuntimeError):
    pass


class BlockedError(KaError):
    pass


_ITEM = re.compile(r'data-adid="(\d+)"')
_HREF = re.compile(r'data-href="(/s-anzeige/[^"]+)"')
_JSON = re.compile(r'(\{"creditText":"Kleinanzeigen".*?\})\s*</script>', re.S)
_WHEN = re.compile(r"(Heute|Gestern),\s*(\d\d):(\d\d)|(\d\d)\.(\d\d)\.(\d{4})")
_PRICE_P = re.compile(r'<p class="[^"]*font-strong[^"]*">\s*([^<]*?)\s*</p>', re.S)
_OLD_PRICE_P = re.compile(r'<p class="[^"]*line-through[^"]*">\s*([^<]*?)\s*</p>', re.S)
_AMOUNT = re.compile(r"(\d[\d.]*)(?:,(\d\d))?\s*€")


def parse_price(text):
    """(price in EUR or None, 'VB' asked) from '1.200 € VB', '70 €', 'VB', 'Zu verschenken' (0)."""
    text = " ".join((text or "").split())
    vb = "VB" in text
    if "verschenken" in text.lower():
        return 0.0, False
    m = _AMOUNT.search(text)
    if not m:
        return None, vb
    return float(m.group(1).replace(".", "") + ("." + m.group(2) if m.group(2) else "")), vb


def listed_at(text, now):
    """'Heute, 10:47' / 'Gestern, 18:02' -> 'YYYY-MM-DD HH:MM' (Berlin); '27.10.2026' -> 'YYYY-MM-DD'."""
    m = _WHEN.search(text or "")
    if not m:
        return None
    if m.group(1):
        day = clock.parse(now) - timedelta(days=0 if m.group(1) == "Heute" else 1)
        return f"{day:%Y-%m-%d} {m.group(2)}:{m.group(3)}"
    return f"{m.group(6)}-{m.group(5)}-{m.group(4)}"


def query_slug(text):
    """'Hasselblad 500C/M' -> 'hasselblad-500c-m' (the search address)."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_search(html, now, kind):
    """The listing items of a search page: [{id, url, title, description, photo, price, vb, old_price,
    listed_at, reserved, kind}]."""
    starts = [(m.start(), int(m.group(1))) for m in _ITEM.finditer(html)]
    out = []
    for (start, item_id), (end, _) in zip(starts, starts[1:] + [(len(html), 0)]):
        block = html[start:end]
        href = _HREF.search(block)
        data = _JSON.search(block)
        if not href or not data:
            continue
        try:
            meta = json.loads(data.group(1))
        except ValueError:
            continue
        rest = block[data.end():]
        text = " ".join(re.sub(r"<[^>]+>", " ", rest).split())
        price_p = _PRICE_P.search(rest)
        old_p = _OLD_PRICE_P.search(rest)
        price, vb = parse_price(price_p.group(1) if price_p else "")
        out.append({
            "id": item_id, "url": BASE_URL + href.group(1), "title": (meta.get("title") or "").strip(),
            "description": meta.get("description") or "", "photo": meta.get("contentUrl"),
            "price": price, "vb": vb, "old_price": parse_price(old_p.group(1))[0] if old_p else None,
            "listed_at": listed_at(text, now), "reserved": "Reserviert" in text[:200], "kind": kind,
        })
    return out


_AD_TITLE = re.compile(r'id="viewad-title"[^>]*>(.*?)</h1>', re.S)
_AD_PRICE = re.compile(r'id="viewad-price"[^>]*>(.*?)</', re.S)
_AD_DATE = re.compile(r'id="viewad-extra-info"[^>]*>(.*?)</div>', re.S)
_AD_DETAIL = re.compile(r'class="addetailslist--detail">\s*([^<]+?)\s*<span[^>]*>\s*([^<]+?)\s*</span>')


def parse_ad(html, final_url, url):
    """A listing's page: {'status': 'active' | 'reserved' | 'gone', 'price', 'vb', 'date', 'condition'}.
    A listing taken down redirects away from its own address."""
    if final_url.rstrip("/").split("?")[0] != url.rstrip("/").split("?")[0] or not _AD_TITLE.search(html):
        return {"status": "gone", "price": None, "vb": False, "date": None, "condition": None}
    title = " ".join(re.sub(r"<[^>]+>", " ", _AD_TITLE.search(html).group(1)).split())
    price_m = _AD_PRICE.search(html)
    price, vb = parse_price(re.sub(r"<[^>]+>", " ", price_m.group(1)) if price_m else "")
    date_m = _AD_DATE.search(html)
    date = _WHEN.search(re.sub(r"<[^>]+>", " ", date_m.group(1))) if date_m else None
    details = dict(_AD_DETAIL.findall(html))
    return {"status": "reserved" if title.startswith("Reserviert") else "active", "price": price, "vb": vb,
            "date": f"{date.group(6)}-{date.group(5)}-{date.group(4)}" if date and date.group(6) else None,
            "condition": details.get("Zustand")}


class KaClient:
    """Single-threaded polite session (2-3 s between requests). Counts requests for the logs."""

    def __init__(self, delay=(2.0, 3.0), timeout=30, time_budget=None):
        self.delay, self.timeout, self.time_budget = delay, timeout, time_budget
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9"})
        self.requests_made, self._last, self._started, self._failures = 0, 0.0, time.monotonic(), 0

    def has_time(self):
        return self.time_budget is None or time.monotonic() - self._started < self.time_budget

    def _get(self, url):
        for attempt in range(len(RETRY_BACKOFF) + 1):
            pause = random.uniform(*self.delay) - (time.monotonic() - self._last)
            if pause > 0:
                time.sleep(pause)
            self._last = time.monotonic()
            self.requests_made += 1
            try:
                resp = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                resp, error = None, type(exc).__name__
            else:
                error = None if resp.status_code < 400 or resp.status_code == 404 else f"http {resp.status_code}"
            if error is None:
                self._failures = 0
                return resp
            self._failures += 1
            if resp is not None and resp.status_code in (403, 429) or self._failures >= FAILURES_IN_ROW_BLOCK:
                raise BlockedError(error)
            if attempt < len(RETRY_BACKOFF):
                time.sleep(RETRY_BACKOFF[attempt])
        raise KaError(error)

    def search_page(self, kind, page, now):
        """Page `page` of the newest listings of a type ('camera', 'camera_and_equipment')."""
        part = "" if page == 1 else f"seite:{page}/"
        resp = self._get(f"{BASE_URL}/s-foto/{kind}/{part}{CATEGORY}+foto.art_s:{kind}")
        items = parse_search(resp.text, now, kind)
        if not items and page == 1:
            raise BlockedError("search page without listings")
        return items

    def model_search(self, text, page, now):
        """Page `page` of a text search in Foto ('Canon AE-1' -> /s-foto/canon-ae-1/k0c245)."""
        part = "" if page == 1 else f"seite:{page}/"
        resp = self._get(f"{BASE_URL}/s-foto/{part}{query_slug(text)}/k0{CATEGORY}")
        return parse_search(resp.text, now, None)

    def ad_page(self, url):
        resp = self._get(url)
        return parse_ad(resp.text, resp.url, url)
