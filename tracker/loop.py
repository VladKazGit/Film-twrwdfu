"""Ticks every 15 minutes inside one GitHub Actions job (up to ~5.5 hours).

GitHub's cron is best-effort (late or skipped runs), so the workflow keeps
itself going instead: this loop runs ticks at :07, :22, :37, :52 Berlin time
inside the 07:00-00:00 window, quick checks (catalog page 1) every 5 minutes in
between, and right before its time budget ends the workflow starts the next run,
which waits for the next slot.

Before each tick the latest code from main is fetched, so code changes take
effect within one tick, not one run.

Run: python -m tracker.loop [--tick-now] [--force]
"""
import argparse
import subprocess
import sys
import time
from datetime import timedelta, timezone

from . import env

SLOT_MINUTES = (7, 22, 37, 52)
QUICK_MINUTES = (2, 12, 17, 27, 32, 42, 47, 57)  # every 5 minutes between the ticks
WINDOW_START_HOUR = 7
BUDGET_MIN = 330  # a 6-hour job limit minus one tick and setup
TICK_TIMEOUT_S = 14 * 60
QUICK_TIMEOUT_S = 4 * 60


def next_slot(now):
    """Next tick or quick check after now, inside the Berlin window; a day starts with a tick."""
    slot = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    while not _in_window(slot):
        slot += timedelta(minutes=1)
    return slot


def is_quick(slot):
    return slot.minute in QUICK_MINUTES


def _in_window(slot):
    if slot.minute not in SLOT_MINUTES + QUICK_MINUTES or slot.hour < WINDOW_START_HOUR:
        return False
    return not (slot.hour == WINDOW_START_HOUR and slot.minute < SLOT_MINUTES[0])  # no quick check before 07:07


def seconds_until(moment, now):
    """Real seconds between two Berlin times (DST-safe)."""
    return (moment.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()


def run_loop(now_fn, sleep_fn, tick_fn, tick_now=False, budget_min=BUDGET_MIN, log=print):
    """Tick on slots until the budget ends. Returns the number of failed ticks.

    After a tick, hand over as soon as the next slot is past the budget, so the
    next run has time to start. A run that has not ticked yet (night) sleeps
    until its budget ends instead, so runs never chain in a tight loop.
    """
    start = now_fn()
    # Real minutes, not wall-clock: the DST night must not stretch the run past the job limit.
    deadline = (start.astimezone(timezone.utc) + timedelta(minutes=budget_min)).astimezone(start.tzinfo)
    failures, ticked = 0, False
    log(f"loop: started, hands over by {deadline:%Y-%m-%d %H:%M} (Berlin)")
    if tick_now:
        failures += 0 if tick_fn(False) else 1
        ticked = True
    while True:
        now = now_fn()
        slot = next_slot(now)
        if seconds_until(slot, deadline) > 0:
            if not ticked:
                log(f"loop: next tick {slot:%Y-%m-%d %H:%M} is after this run; sleeping until hand-over")
                _sleep_until(deadline, now_fn, sleep_fn)
            log("loop: handing over to the next run")
            return failures
        if not is_quick(slot):
            log(f"loop: next tick {slot:%H:%M}")
        _sleep_until(slot, now_fn, sleep_fn)
        failures += 0 if tick_fn(is_quick(slot)) else 1
        ticked = True


def _sleep_until(moment, now_fn, sleep_fn):
    while True:
        left = seconds_until(moment, now_fn())
        if left <= 0:
            return
        sleep_fn(min(left, 300))


def _update_code():
    """Fetch the latest main so a pushed fix applies from the next tick."""
    for args in (["fetch", "--quiet", "--depth", "1", "origin", "main"], ["reset", "--quiet", "--hard", "FETCH_HEAD"]):
        if subprocess.run(["git", *args], capture_output=True).returncode != 0:
            print("loop: code update failed, keeping the current code")
            return


def _tick(force, quick=False):
    _update_code()
    cmd = [sys.executable, "-m", "tracker.tick"] + (["--force"] if force else []) + (["--quick"] if quick else [])
    try:
        return subprocess.run(cmd, timeout=QUICK_TIMEOUT_S if quick else TICK_TIMEOUT_S).returncode == 0
    except subprocess.TimeoutExpired:
        print(f"loop: {'quick check' if quick else 'tick'} timed out")
        return False


def main():
    parser = argparse.ArgumentParser(description="Ticks every 15 minutes for one Actions run.")
    parser.add_argument("--tick-now", action="store_true", help="tick right away (manual start)")
    parser.add_argument("--force", action="store_true", help="first tick ignores the time window")
    args = parser.parse_args()

    first = {"force": args.force}

    def tick(quick):
        ok = _tick(first.pop("force", False), quick)
        sys.stdout.flush()
        return ok

    failures = run_loop(env.now_berlin, time.sleep, tick, tick_now=args.tick_now)
    if failures:
        print(f"loop: {failures} tick(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
