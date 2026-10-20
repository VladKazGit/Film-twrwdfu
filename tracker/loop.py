"""Ticks every 13-18 minutes (at random, not on the clock) inside one GitHub Actions job
(up to ~5.5 hours).

GitHub's cron is best-effort (late or skipped runs), so the workflow keeps
itself going instead: this loop runs ticks 13-18 minutes apart inside the 07:00-00:00
Berlin window (the day's first one at 07:03-07:12), two quick checks (catalog page 1)
in each gap, and right before its time budget ends the workflow starts the next run,
which goes on with the same rhythm.

Before each tick the latest code from main is fetched, so code changes take
effect within one tick, not one run.

Run: python -m tracker.loop [--tick-now] [--force]
"""
import argparse
import random
import subprocess
import sys
import time
from datetime import timedelta, timezone

from . import env

GAP_MIN, GAP_MAX = 13, 18  # minutes between ticks, at random
FIRST_TICK_MIN = (3, 12)  # the day's first tick: 07:03-07:12
QUICK_JITTER_S = 40  # quick checks at ~1/3 and ~2/3 of a gap, give or take
LATE_S = 30  # a check this late after its time (the previous one overran) is skipped
WINDOW_START_HOUR = 7
BUDGET_MIN = 330  # a 6-hour job limit minus one tick and setup
TICK_TIMEOUT_S = 14 * 60
QUICK_TIMEOUT_S = 4 * 60


def next_tick(after, rng):
    """A tick 13-18 minutes after `after`; past midnight, the next day's first one (07:03-07:12)."""
    tick = after + timedelta(seconds=rng.uniform(GAP_MIN * 60, GAP_MAX * 60))
    if tick.hour < WINDOW_START_HOUR:
        tick = tick.replace(hour=WINDOW_START_HOUR, minute=0, second=0, microsecond=0) + timedelta(
            seconds=rng.uniform(FIRST_TICK_MIN[0] * 60, FIRST_TICK_MIN[1] * 60))
    return tick


# Between two ticks: quick checks at ~1/3 and ~2/3, cheap checks (listings at 20 EUR or less) in between.
CHECKS = ((1 / 6, "cheap"), (1 / 3, "quick"), (1 / 2, "cheap"), (2 / 3, "quick"), (5 / 6, "cheap"))


def quick_times(last, tick, rng):
    """The checks between ticks of one evening/day (none across the night): [(time, mode)]."""
    gap = seconds_until(tick, last)
    if gap > (GAP_MAX + 1) * 60:
        return []
    return [(last + timedelta(seconds=gap * share + rng.uniform(-QUICK_JITTER_S, QUICK_JITTER_S) / (2 if mode == "cheap" else 1)),
             mode) for share, mode in CHECKS]


def seconds_until(moment, now):
    """Real seconds between two Berlin times (DST-safe)."""
    return (moment.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()


def run_loop(now_fn, sleep_fn, tick_fn, tick_now=False, budget_min=BUDGET_MIN, log=print, rng=None):
    """Tick 13-18 minutes apart until the budget ends. Returns the number of failed ticks.

    After a tick, hand over as soon as the next tick is past the budget, so the
    next run has time to start (it counts its first gap from its own start, a
    minute after the last tick). A run that has not ticked yet (night) sleeps
    until its budget ends instead, so runs never chain in a tight loop.
    """
    rng = rng or random.Random()
    start = now_fn()
    # Real minutes, not wall-clock: the DST night must not stretch the run past the job limit.
    deadline = (start.astimezone(timezone.utc) + timedelta(minutes=budget_min)).astimezone(start.tzinfo)
    failures, ticked, last = 0, False, start
    log(f"loop: started, hands over by {deadline:%Y-%m-%d %H:%M} (Berlin)")
    if tick_now:
        failures += 0 if tick_fn("tick") else 1
        ticked = True
    while True:
        tick = next_tick(last, rng)
        if seconds_until(tick, deadline) > 0:
            if not ticked:
                log(f"loop: next tick {tick:%Y-%m-%d %H:%M} is after this run; sleeping until hand-over")
                _sleep_until(deadline, now_fn, sleep_fn)
            log("loop: handing over to the next run")
            return failures
        log(f"loop: next tick {tick:%H:%M:%S}")
        for when, mode in quick_times(last, tick, rng):
            # A check more than half a minute late follows right on the previous one: skipped.
            if seconds_until(when, now_fn()) > -LATE_S and seconds_until(tick, when) > 60:
                _sleep_until(when, now_fn, sleep_fn)
                tick_fn(mode)  # a slow or failed check is not a failed run: the next tick tells
        _sleep_until(tick, now_fn, sleep_fn)
        last = now_fn()  # gaps count from the real start: an overrun tick does not bunch the next ones
        failures += 0 if tick_fn("tick") else 1
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


def _tick(force, mode="tick"):
    _update_code()
    cmd = [sys.executable, "-m", "tracker.tick"] + (["--force"] if force else []) + ([f"--{mode}"] if mode != "tick" else [])
    try:
        return subprocess.run(cmd, timeout=TICK_TIMEOUT_S if mode == "tick" else QUICK_TIMEOUT_S).returncode == 0
    except subprocess.TimeoutExpired:
        print(f"loop: {mode} check timed out")
        return False


def main():
    parser = argparse.ArgumentParser(description="Ticks every 13-18 minutes for one Actions run.")
    parser.add_argument("--tick-now", action="store_true", help="tick right away (manual start)")
    parser.add_argument("--force", action="store_true", help="first tick ignores the time window")
    args = parser.parse_args()

    first = {"force": args.force}

    def tick(mode):
        ok = _tick(first.pop("force", False), mode)
        sys.stdout.flush()
        return ok

    failures = run_loop(env.now_berlin, time.sleep, tick, tick_now=args.tick_now)
    if failures:
        print(f"loop: {failures} tick(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
