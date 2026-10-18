"""Secrets from environment variables, Berlin time and log redaction.

Secrets are never printed. Pass any text that may contain them (exception
messages, git output) through `redact()` before logging.
"""
import base64
import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")

SECRET_NAMES = ("GOOGLE_SA_KEY", "SHEET_ID", "DATA_TOKEN", "DATA_REPO", "MAIL_USER", "MAIL_APP_PASSWORD", "MAIL_TO")

# Long digit runs: item ids, user ids, cloud project numbers.
_LONG_NUMBER = re.compile(r"\d{6,}")


class ConfigError(RuntimeError):
    pass


def require(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"secret {name} is not set")
    return value


def now_berlin():
    return datetime.now(BERLIN)


def google_sa_info():
    """Service account key as dict. Accepts raw JSON or base64-encoded JSON."""
    raw = require("GOOGLE_SA_KEY")
    if not raw.startswith("{"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except ValueError:
            raise ConfigError("GOOGLE_SA_KEY is neither JSON nor base64 JSON") from None
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        raise ConfigError("GOOGLE_SA_KEY is not valid JSON") from None
    if info.get("type") != "service_account":
        raise ConfigError("GOOGLE_SA_KEY is not a service account key")
    return info


def sheet_id():
    """Spreadsheet key. Accepts a full docs.google.com URL too."""
    value = require("SHEET_ID")
    match = re.search(r"/d/([A-Za-z0-9_-]+)", value)
    return match.group(1) if match else value


def data_repo():
    """Private data repo as 'owner/name'. Accepts a full GitHub URL too."""
    repo = require("DATA_REPO")
    for prefix in ("https://github.com/", "http://github.com/", "github.com/", "git@github.com:"):
        repo = repo.removeprefix(prefix)
    repo = repo.removesuffix(".git").strip("/")
    if repo.count("/") != 1:
        raise ConfigError("DATA_REPO must look like owner/name")
    return repo


def _secret_values():
    values = [os.environ.get(name, "").strip() for name in SECRET_NAMES]
    for getter in (sheet_id, data_repo):
        try:
            values.append(getter())
        except ConfigError:
            pass
    try:
        info = google_sa_info()
        values += [info.get("client_email", ""), info.get("project_id", ""), info.get("private_key_id", "")]
    except ConfigError:
        pass
    owner_name = [v for v in values if v.count("/") == 1]
    values += [part for v in owner_name for part in v.split("/")]
    return sorted({v for v in values if len(v) >= 4}, key=len, reverse=True)


def redact(text, limit=300):
    """Remove secrets and long ids from text meant for logs."""
    text = str(text)
    for value in _secret_values():
        text = text.replace(value, "***")
    text = _LONG_NUMBER.sub("***", text)
    return text[:limit]
