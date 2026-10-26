"""Lens checks for one GitHub Actions run (up to ~5.5 hours): the lens chain, like the cameras'
(tracker.loop) but on its own machine. 10 checks a day in the 07:00-00:00 Berlin window, about 100
minutes apart (a few minutes either way, at random); while the first collection runs (a check exits
with code 10), one check right after another. Before each check the latest code from main is fetched;
right before its time budget ends the workflow starts the next run.

Run: python -m tracker.lens_loop [--force]
"""
import argparse
import random
import subprocess
import sys
import time
from datetime import timedelta, timezone

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


def run_loop(now_fn, sleep_fn, check_fn, force=False, budget_min=BUDGET_MIN, log=print, rng=None):
    """Checks until the budget ends. Returns the number of failed checks. A run that has not checked
    yet (night) sleeps until its budget ends, so runs never chain in a tight loop."""
    rng = rng or random.Random()
    start = now_fn()
    deadline = (start.astimezone(timezone.utc) + timedelta(minutes=budget_min)).astimezone(start.tzinfo)
    failures, in_row, checked = 0, 0, False
    when = start if force or start.hour >= WINDOW_START_HOUR else next_check(start, True, rng)
    log(f"lens loop: started, hands over by {deadline:%Y-%m-%d %H:%M} (Berlin)")
    while True:
        if seconds_until(when, deadline) > 0:
            if not checked:
                log(f"lens loop: next check {when:%Y-%m-%d %H:%M} is after this run; sleeping until hand-over")
                _sleep_until(deadline, now_fn, sleep_fn)
            log("lens loop: handing over to the next run")
            return failures
        _sleep_until(when, now_fn, sleep_fn)
        code = check_fn()
        checked = True
        ok = code in (0, PENDING)
        failures += 0 if ok else 1
        in_row = 0 if ok else in_row + 1
        if in_row >= FAILED_IN_ROW_MAX:
            log(f"lens loop: {in_row} checks failed in a row; handing over to a new run (a new machine)")
            return failures
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
    args = parser.parse_args()

    def check():
        code = _check()
        sys.stdout.flush()
        return code

    failures = run_loop(env.now_berlin, time.sleep, check, force=args.force)
    if failures:
        print(f"lens loop: {failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
