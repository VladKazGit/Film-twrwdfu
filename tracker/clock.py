"""Berlin wall-clock timestamps stored to the minute: 'YYYY-MM-DD HH:MM'."""
from datetime import datetime, timezone

from .env import BERLIN, now_berlin

FMT = "%Y-%m-%d %H:%M"


def stamp(dt=None):
    return (dt or now_berlin()).astimezone(BERLIN).strftime(FMT)


def parse(text):
    return datetime.strptime(text, FMT).replace(tzinfo=BERLIN)


def minutes_between(start, end):
    """Real minutes from start to end; DST-safe (compares in UTC)."""
    delta = parse(end).astimezone(timezone.utc) - parse(start).astimezone(timezone.utc)
    return int(delta.total_seconds() // 60)
