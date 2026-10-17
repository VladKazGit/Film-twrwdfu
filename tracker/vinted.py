"""Vinted (vinted.de) web client and page parsers.

The JSON API is closed, so we read HTML pages. Their data lives in the Next.js
flight payload: `self.__next_f.push([1, "<json text>"])` script chunks.

Politeness: one session, one request at a time, 2-3 s between requests.
Smoke test (aggregates only): python -m tracker.vinted --pages 1 --items 3
"""
import argparse
import json
import random
import re
import time

import requests

BASE_URL = "https://www.vinted.de"
CATEGORY_ID = 3076  # Filmkameras; 3077 Sofortbildkameras is out of scope
MAX_PAGES = 10  # total_entries is capped at 960 = 10 pages x 96

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

RETRY_BACKOFF = (15, 45)  # seconds before 2nd and 3rd attempt on 429/5xx/network
MAX_RETRY_AFTER = 90
FAILURES_IN_ROW_BLOCK = 3  # network errors / 429 / 5xx in a row: treat Vinted as blocking us

STATUSES = ("active", "reserved", "hidden", "sold", "deleted", "unknown")

_FLIGHT_CHUNK = re.compile(r'self\.__next_f\.push\((\[1,".*?"\])\)</script>', re.S)
_SOLD_CELL = re.compile(r"web_ui__Cell__success.{0,3000}?Verkauft", re.S)
_DECODER = json.JSONDecoder()


class VintedError(RuntimeError):
    """Request failed: network, server error or an unexpected page."""


class BlockedError(VintedError):
    """403/429, captcha or a page without data: stop non-essential requests."""


# ---------------------------------------------------------------- parsing

def flight_payload(html):
    """Concatenated Next.js flight payload of a page ('' if there is none)."""
    return "".join(json.loads(m.group(1))[1] for m in _FLIGHT_CHUNK.finditer(html))


def _decode_at(payload, pos):
    try:
        return _DECODER.raw_decode(payload, pos)[0]
    except ValueError:
        return None


def _values_after(payload, key):
    """Decode every JSON value that follows `"key":` in the payload."""
    marker = f'"{key}":'
    pos = payload.find(marker)
    while pos != -1:
        value = _decode_at(payload, pos + len(marker))
        if value is not None:
            yield value
        pos = payload.find(marker, pos + 1)


def _enclosing_object(payload, pos):
    """Decode the innermost JSON object that contains position `pos`."""
    depth = 0
    for i in range(pos - 1, -1, -1):
        char = payload[i]
        if char == "}":
            depth += 1
        elif char == "{":
            if depth == 0:
                return _decode_at(payload, i)
            depth -= 1
    return None


def _text(value):
    """Flight payload uses '$undefined' for missing values."""
    if value is None or value == "$undefined" or value == "":
        return None
    return str(value).strip()


def _resolve(payload, value):
    """Long strings live in separate text rows ('\\nf9:T786,<text>'); '$f9' points there.

    The hex length counts UTF-8 bytes.
    """
    ref = re.fullmatch(r"\$([0-9a-f]+)", value) if isinstance(value, str) else None
    if not ref:
        return value
    row = (re.search(rf"(?:^|\n){ref.group(1)}:T([0-9a-f]+),", payload)
           or re.search(rf"{ref.group(1)}:T([0-9a-f]+),", payload))
    if not row:
        return None
    size = int(row.group(1), 16)
    text = payload[row.end():row.end() + size]  # chars >= bytes, trim below
    return text.encode("utf-8")[:size].decode("utf-8", "ignore")


def _price(value):
    if isinstance(value, dict):
        value = value.get("amount")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_catalog(html):
    """Items and pagination of a catalog page.

    Returns (items, pagination); items are dicts with id, title, url, price,
    brand, condition, seller_id, promoted, favourites. pagination may be None.
    """
    payload = flight_payload(html)
    items, seen = [], set()
    for raw in _values_after(payload, "productItem"):
        if not isinstance(raw, dict) or "id" not in raw:
            continue
        item_id = int(raw["id"])
        if item_id in seen:
            continue
        seen.add(item_id)
        box = raw.get("itemBox") or {}
        url = raw.get("url") or f"/items/{item_id}"
        title = _text(raw.get("title")) or ""
        brand = _text(box.get("firstLine"))
        if brand == title:
            brand = None  # items without a brand show the title in firstLine
        items.append({
            "id": item_id,
            "title": title,
            "url": url if url.startswith("http") else BASE_URL + url,
            "price": _price(raw.get("price")),
            "brand": brand,
            "condition": _text(box.get("secondLine")),
            "seller_id": (raw.get("user") or {}).get("id"),
            "promoted": bool(raw.get("isPromoted")),
            "favourites": _count(raw.get("favouriteCount")),
        })
    pagination = next((p for p in _values_after(payload, "pagination") if isinstance(p, dict)), None)
    return items, pagination


def _count(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _favourites(payload, item_id):
    """Users' saves ('favourite_count') of this item, or None."""
    pos = payload.find('"favourite_count":')
    while pos != -1:
        obj = _enclosing_object(payload, pos)
        if isinstance(obj, dict) and str(obj.get("item_id", obj.get("id"))) == str(item_id):
            return _count(obj.get("favourite_count"))
        pos = payload.find('"favourite_count":', pos + 1)
    return None


def _plugins(payload):
    for value in _values_after(payload, "plugins"):
        if isinstance(value, list) and any(isinstance(p, dict) and "name" in p for p in value):
            return {p["name"]: p.get("data") or {} for p in value if isinstance(p, dict) and "name" in p}
    return {}


def _item_state(payload, item_id):
    """Merged fields of the payload objects that carry can_buy for this item."""
    state = {}
    pos = payload.find('"can_buy":')
    while pos != -1:
        obj = _enclosing_object(payload, pos)
        if isinstance(obj, dict) and str(obj.get("id", obj.get("item_id"))) == str(item_id):
            for key, value in obj.items():
                if not (isinstance(value, str) and value.startswith("$")):
                    state.setdefault(key, value)
        pos = payload.find('"can_buy":', pos + 1)
    return state


def _json_ld_product(html):
    for m in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            return data
    return None


_AGE_UNITS = (("min", 0), ("std", 0), ("stunde", 0), ("tag", 1), ("woche", 7), ("monat", 30), ("jahr", 365))


def age_days(uploaded_ago):
    """Days from Vinted's relative upload text ('3 Std.', '2 Wochen', '5 Monaten'), or None."""
    m = re.match(r"\s*(\d+)\s*([^\W\d_]+)", uploaded_ago or "")
    if not m:
        return None
    unit = m.group(2).lower()
    return next((int(m.group(1)) * days for prefix, days in _AGE_UNITS if unit.startswith(prefix)), None)


def parse_item(html, status_code, final_url, item_id):
    """Status and details of an item page.

    status: active / reserved / hidden / sold / deleted / unknown.
    Other keys (None when absent): title, description, price, brand,
    condition, uploaded_ago (relative text like '3 Std.'), favourites
    (users' saves), reason.
    """
    result = dict.fromkeys(("title", "description", "price", "brand", "condition", "uploaded_ago", "favourites"))
    result.update(status="unknown", reason=None)

    if status_code in (404, 410):
        return {**result, "status": "deleted", "reason": f"http {status_code}"}
    if not re.search(rf"/items/{item_id}(?:[-/?#]|$)", final_url or ""):
        return {**result, "status": "deleted", "reason": "redirected away"}
    if status_code != 200:
        return {**result, "reason": f"http {status_code}"}

    payload = flight_payload(html)
    if not payload:
        raise BlockedError("item page without data")

    plugins = _plugins(payload)
    attributes = {a.get("code"): (a.get("data") or {}).get("value")
                  for a in (plugins.get("attributes") or {}).get("attributes") or []}
    state = _item_state(payload, item_id)
    ld = _json_ld_product(html)

    result.update(
        title=_text(_resolve(payload, state.get("title"))),
        description=_text(_resolve(payload, (plugins.get("description") or {}).get("description"))),
        price=_price(state.get("price")),
        brand=_text(attributes.get("brand")),
        condition=_text(attributes.get("status")),
        uploaded_ago=_text(attributes.get("upload_date")),
        favourites=_favourites(payload, item_id),
    )
    if ld:
        result["title"] = result["title"] or _text(ld.get("name"))
        result["description"] = result["description"] or _text(ld.get("description"))
        if result["price"] is None:
            result["price"] = _price((ld.get("offers") or {}).get("price"))

    # Sold pages replace the buy buttons with a status banner:
    # buyer_item_status = {"theme": "SUCCESS", "title": "Verkauft"}.
    banner = plugins.get("buyer_item_status") or {}
    banner_title = _text(banner.get("title"))

    if state.get("is_hidden"):
        result["status"] = "hidden"
    elif state.get("is_reserved"):
        result["status"] = "reserved"
    elif state.get("can_buy") is True:
        result["status"] = "active"
    elif banner_title == "Verkauft" or _SOLD_CELL.search(html):
        result["status"] = "sold"
    elif banner_title:
        result["reason"] = f"banner {banner_title}"
    elif not state:
        result["reason"] = "no item state"
    else:
        result["reason"] = "can_buy false, no sold marker"
    return result


# ---------------------------------------------------------------- client

class VintedClient:
    """Single-threaded polite session. Counts requests and bytes for logs."""

    def __init__(self, delay=(2.0, 3.0), timeout=30, max_requests=None, time_budget=None):
        self.delay = delay
        self.timeout = timeout
        self.max_requests = max_requests
        self.time_budget = time_budget  # seconds of Vinted traffic per tick (None: no limit)
        self.requests_made = 0
        self.bytes_received = 0
        self.session = None
        self._last_request = 0.0
        self._started = time.monotonic()
        self._failures_in_row = 0

    def has_time(self):
        return self.time_budget is None or time.monotonic() - self._started < self.time_budget

    def _failed(self):
        self._failures_in_row += 1
        if self._failures_in_row >= FAILURES_IN_ROW_BLOCK:
            raise BlockedError("vinted not responding")

    def _get(self, url, params=None):
        if self.max_requests is not None and self.requests_made >= self.max_requests:
            raise VintedError("request budget exhausted")
        if not self.has_time():
            raise VintedError("time budget exhausted")
        pause = random.uniform(*self.delay) - (time.monotonic() - self._last_request)
        if pause > 0:
            time.sleep(pause)
        self.requests_made += 1
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise VintedError(f"network error: {type(exc).__name__}") from None
        finally:
            self._last_request = time.monotonic()
        self.bytes_received += len(resp.content)
        return resp

    def start(self):
        """Open a fresh session: the home page sets access_token_web and friends."""
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        resp = self._get(BASE_URL + "/")
        if resp.status_code in (403, 429):
            raise BlockedError(f"home page http {resp.status_code}")
        if "access_token_web" not in self.session.cookies:
            raise BlockedError("no session cookie")

    def _start_with_retries(self):
        """Open the session; a slow or failing home page is retried like any request
        (a single ReadTimeout there used to fail the whole tick)."""
        for attempt in range(len(RETRY_BACKOFF) + 1):
            try:
                self.start()
                self._failures_in_row = 0
                return
            except BlockedError:
                raise
            except VintedError as exc:
                if "budget" in str(exc):
                    raise
                self.session = None
                self._failed()
                if attempt == len(RETRY_BACKOFF):
                    raise
                time.sleep(RETRY_BACKOFF[attempt])

    def fetch(self, url, params=None):
        """GET with retries: 429/5xx/network back off, 401/403 renew the session once."""
        if self.session is None:
            self._start_with_retries()
        renewed = False
        for attempt in range(len(RETRY_BACKOFF) + 1):
            try:
                resp = self._get(url, params)
            except VintedError as exc:
                if "budget" in str(exc):
                    raise
                self._failed()
                if attempt == len(RETRY_BACKOFF):
                    raise
                time.sleep(RETRY_BACKOFF[attempt])
                continue
            code = resp.status_code
            if code in (401, 403) and not renewed:
                renewed = True
                self._start_with_retries()
                continue
            if code == 429 or code >= 500:
                self._failed()
                if attempt == len(RETRY_BACKOFF):
                    break
                wait = RETRY_BACKOFF[attempt]
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    wait = min(max(wait, int(retry_after)), MAX_RETRY_AFTER)
                time.sleep(wait)
                continue
            if code in (401, 403):
                raise BlockedError(f"http {code}")
            self._failures_in_row = 0
            return resp
        if resp.status_code == 429:
            raise BlockedError("http 429")
        raise VintedError(f"http {resp.status_code}")

    def catalog_page(self, page):
        """Items of catalog page `page` (newest first). Raises BlockedError if empty."""
        resp = self.fetch(BASE_URL + "/catalog",
                          {"catalog[]": CATEGORY_ID, "order": "newest_first", "page": page})
        if resp.status_code != 200:
            raise VintedError(f"catalog http {resp.status_code}")
        items, pagination = parse_catalog(resp.text)
        if not items:
            if pagination and page > pagination.get("total_pages", MAX_PAGES):
                return []
            raise BlockedError("catalog page without items")
        return items

    def search_page(self, text, page, max_price=None):
        """Category search by text (relevance order), optionally up to max_price."""
        params = {"search_text": text, "catalog[]": CATEGORY_ID, "order": "relevance", "page": page}
        if max_price is not None:
            params["price_to"] = max_price
        resp = self.fetch(BASE_URL + "/catalog", params)
        if resp.status_code != 200:
            raise VintedError(f"search http {resp.status_code}")
        if not flight_payload(resp.text):
            raise BlockedError("search page without data")
        return parse_catalog(resp.text)[0]

    def fresh_page(self, text):
        """Newest listings for a text in all categories, page 1 (cameras put in another category)."""
        resp = self.fetch(BASE_URL + "/catalog", {"search_text": text, "order": "newest_first", "page": 1})
        if resp.status_code != 200:
            raise VintedError(f"search http {resp.status_code}")
        if not flight_payload(resp.text):
            raise BlockedError("search page without data")
        return parse_catalog(resp.text)[0]

    def item_page(self, item_id):
        resp = self.fetch(f"{BASE_URL}/items/{item_id}")
        return parse_item(resp.text, resp.status_code, resp.url, item_id)


# ---------------------------------------------------------------- smoke test

def main():
    parser = argparse.ArgumentParser(description="Vinted smoke test; prints aggregates only.")
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--items", type=int, default=2, help="item pages to open from page 1")
    args = parser.parse_args()

    client = VintedClient()
    started = time.monotonic()
    items = []
    for page in range(1, args.pages + 1):
        items += client.catalog_page(page)
    ids = [i["id"] for i in items]
    print(f"catalog: {args.pages} page(s), {len(items)} items, unique {len(set(ids))}, "
          f"promoted {sum(i['promoted'] for i in items)}, "
          f"with price {sum(i['price'] is not None for i in items)}, "
          f"with brand {sum(i['brand'] is not None for i in items)}")
    statuses = {}
    for item in items[:args.items]:
        status = client.item_page(item["id"])["status"]
        statuses[status] = statuses.get(status, 0) + 1
    print(f"item pages: {statuses}")
    print(f"requests {client.requests_made}, {client.bytes_received / 1e6:.1f} MB, "
          f"{time.monotonic() - started:.0f} s")


if __name__ == "__main__":
    main()
