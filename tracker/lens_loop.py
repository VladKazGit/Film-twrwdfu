"""Lens checks for one GitHub Actions run (up to ~5.5 hours): the lens chain, like the cameras'
(tracker.loop) but on its own machine. 10 checks a day in the 07:00-00:00 Berlin window, about 100
minutes apart (a few minutes either way, at random); while the first collection runs (a check exits
with code 10), one check right after another. Before each check the latest code from main is fetched;
right before its time budget ends the workflow starts the next run and hands it the time of its first
check (--next-check), so a hand-over adds no check of its own.

Run: python -m tracker.lens_loop [--force] [--chained] [--next-check ISO-TIME]
"""
import argparse
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

from . import env
from .loop import FAILED_IN_ROW_MAX, _sleep_until, _update_code, seconds_until

CHECKS_PER_DAY = 10
WINDOW_START_HOUR = 7
GAP_MIN = (24 - WINDOW_START_HOUR) * 60 / CHECKS_PER_DAY  # 102 minutes
JITTER_MIN = 5
FIRST_CHECK_MIN = (2, 10)    # the day's first check: 07:02-07:10
BACKFILL_PAUSE_S = 60        # between checks while the first collection runs
BUDGET_MIN = 330             # a 6-hour job limit minus one check and setup
CHECK_TIMEOUT_S = 40 * 60
PENDING = 10                 # tracker.lens_tick's exit code while the first collection runs


def next_check(last, pending, rng):
    """The next check after one at `last`; past midnight, the next day's first one."""
    if pending:
        when = last + timedelta(seconds=BACKFILL_PAUSE_S)
    else:
        when = last + timedelta(minutes=GAP_MIN + rng.uniform(-JITTER_MIN, JITTER_MIN))
    if when.hour < WINDOW_START_HOUR:
        when = when.replace(hour=WINDOW_START_HOUR, minute=0, second=0, microsecond=0) + timedelta(
            minutes=rng.uniform(*FIRST_CHECK_MIN))
    return when


def first_check(start, given, rng):
    """The run's first check: the time the previous run handed over (at once if it has passed), else
    now; never at night."""
    when = max(given, start) if given else start
    return when if when.hour >= WINDOW_START_HOUR else next_check(when, True, rng)


def run_loop(now_fn, sleep_fn, check_fn, force=False, first=None, budget_min=BUDGET_MIN, log=print, rng=None):
    """Checks until the budget ends. Returns (the number of failed checks, the time of the next check,
    for the next run). first: the first check's time (handed over by the previous run). A run that has
    not checked yet (night) sleeps until its budget ends, so runs never chain in a tight loop."""
    rng = rng or random.Random()
    start = now_fn()
    deadline = (start.astimezone(timezone.utc) + timedelta(minutes=budget_min)).astimezone(start.tzinfo)
    failures, in_row, checked = 0, 0, False
    when = start if force else first_check(start, first, rng)
    log(f"lens loop: started, hands over by {deadline:%Y-%m-%d %H:%M} (Berlin)")
    while True:
        if seconds_until(when, deadline) > 0:
            if not checked:
                log(f"lens loop: next check {when:%Y-%m-%d %H:%M} is after this run; sleeping until hand-over")
                _sleep_until(deadline, now_fn, sleep_fn)
            log(f"lens loop: handing over to the next run (next check {when:%Y-%m-%d %H:%M})")
            return failures, when
        _sleep_until(when, now_fn, sleep_fn)
        code = check_fn()
        checked = True
        ok = code in (0, PENDING)
        failures += 0 if ok else 1
        in_row = 0 if ok else in_row + 1
        if in_row >= FAILED_IN_ROW_MAX:
            log(f"lens loop: {in_row} checks failed in a row; handing over to a new run (a new machine)")
            return failures, now_fn()
        # a failed check retries soon, as during the first collection
        when = next_check(now_fn(), code != 0, rng)
        log(f"lens loop: next check {when:%H:%M}")


def _check():
    _update_code()
    try:
        return subprocess.run([sys.executable, "-m", "tracker.lens_tick"], timeout=CHECK_TIMEOUT_S).returncode
    except subprocess.TimeoutExpired:
        print("lens loop: check timed out")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Lens checks for one Actions run.")
    parser.add_argument("--force", action="store_true", help="check at once, even outside the window")
    parser.add_argument("--chained", action="store_true", help="started by the previous run")
    parser.add_argument("--next-check", default="", help="the first check's time, from the previous run (ISO)")
    args = parser.parse_args()

    def check():
        code = _check()
        sys.stdout.flush()
        return code

    rng = random.Random()
    first = None
    if args.next_check:
        first = datetime.fromisoformat(args.next_check).astimezone(env.BERLIN)
    elif args.chained:  # the previous run said nothing: a usual gap from this run's start
        first = next_check(env.now_berlin(), False, rng)
    failures, when = run_loop(env.now_berlin, time.sleep, check, force=args.force, first=first, rng=rng)
    if os.environ.get("GITHUB_OUTPUT"):  # for the step that starts the next run
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(f"next_check={when.isoformat(timespec='seconds')}\n")
    if failures:
        print(f"lens loop: {failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
