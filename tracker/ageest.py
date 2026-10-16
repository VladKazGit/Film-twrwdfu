"""Listing age from the item id.

Vinted ids grow with time. Cards whose listing date is known from Vinted
('Hochgeladen' on the item page) are anchors: sorted by id, smoothed with a
running median (the texts are coarse: '5 Monaten'), and interpolated
linearly. Ids outside the anchors are extrapolated with the overall slope.
"""
import statistics
from bisect import bisect_left
from datetime import date, timedelta

MIN_ANCHORS = 30
SMOOTH = 2  # running median over 2*SMOOTH+1 anchors


def anchor_date(item):
    """Listing date known from Vinted for a card, or None (estimates by id do not count)."""
    if item.get("age_source") == "id":
        return None
    if item.get("vinted_listed_est"):
        return date.fromisoformat(item["vinted_listed_est"])
    if item.get("age_days_at_discovery") is not None and item.get("first_seen"):
        return date.fromisoformat(item["first_seen"][:10]) - timedelta(days=item["age_days_at_discovery"])
    return None


def build_estimator(items, newest_id=None, today=None):
    """Function id -> estimated listing date, or None if there are too few anchors."""
    anchors = sorted((i["id"], d.toordinal()) for i in items if (d := anchor_date(i)) is not None)
    if newest_id and today:
        anchors.append((newest_id, today.toordinal()))
        anchors.sort()
    if len(anchors) < MIN_ANCHORS:
        return None
    ids = [a[0] for a in anchors]
    days = [a[1] for a in anchors]
    smooth = [statistics.median(days[max(0, k - SMOOTH):k + SMOOTH + 1]) for k in range(len(days))]
    span = ids[-1] - ids[0]
    slope = (smooth[-1] - smooth[0]) / span if span else 0.0

    def estimate(item_id):
        k = bisect_left(ids, item_id)
        if k == 0:
            value = smooth[0] - (ids[0] - item_id) * slope
        elif k == len(ids):
            value = smooth[-1] + (item_id - ids[-1]) * slope
        else:
            left, right = ids[k - 1], ids[k]
            share = (item_id - left) / (right - left) if right != left else 0.0
            value = smooth[k - 1] + share * (smooth[k] - smooth[k - 1])
        return date.fromordinal(round(value))

    return estimate
