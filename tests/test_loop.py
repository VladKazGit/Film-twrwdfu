"""Tick loop timing on a fake clock. Run: python -m tests.test_loop"""
import random
from datetime import datetime, timedelta, timezone

from tracker.env import BERLIN
from tracker.loop import BUDGET_MIN, run_loop


class FakeClock:
    """Real time kept in UTC; ticks take 4 minutes, quick checks 1, cheap checks half a minute."""

    def __init__(self, berlin_start):
        self.utc = berlin_start.replace(tzinfo=BERLIN).astimezone(timezone.utc)
        self.ticks, self.quick, self.cheap, self.slept = [], [], [], 0.0

    def now(self):
        return self.utc.astimezone(BERLIN)

    def sleep(self, seconds):
        self.slept += seconds
        self.utc += timedelta(seconds=seconds)

    def tick(self, ok=True, mode="tick"):
        {"tick": self.ticks, "quick": self.quick, "cheap": self.cheap}[mode].append(self.now())
        self.utc += timedelta(minutes={"tick": 4, "quick": 1, "cheap": 0.5}[mode])
        return ok


def run(start, tick_now=False, fail=False, seed=1):
    """fail: True (every tick fails) or the numbers of the ticks that fail."""
    clock = FakeClock(start)

    def tick(mode):
        failing = fail is True or (mode == "tick" and fail and len(clock.ticks) in fail)
        return clock.tick(not failing, mode)

    failures = run_loop(clock.now, clock.sleep, tick, tick_now=tick_now, log=lambda _: None, rng=random.Random(seed))
    return clock, failures


def minutes(a, b):
    return (b - a).total_seconds() / 60


def main():
    # Daytime run: ticks 13-18 minutes apart at uneven times, two quick checks in each gap.
    for seed in range(5):
        c, f = run(datetime(2026, 10, 16, 12, 40), seed=seed)
        gaps = [minutes(a, b) for a, b in zip(c.ticks, c.ticks[1:])]
        assert 18 <= len(c.ticks) <= 26 and all(13 <= g <= 18.01 for g in gaps), gaps
        assert len({round(g, 1) for g in gaps}) > 5 and len({t.second for t in c.ticks}) > 5, "not on the clock"
        assert len(c.quick) == 2 * len(c.ticks), (len(c.quick), len(c.ticks))
        # cheap checks every ~2-3 minutes; the one right after a 4-minute tick is late and skipped
        assert 2 * len(c.ticks) <= len(c.cheap) <= 3 * len(c.ticks), (len(c.cheap), len(c.ticks))
        events = sorted(c.ticks + c.quick + c.cheap)
        assert all(minutes(a, b) >= 1.2 for a, b in zip(events, events[1:])), "no bunching"
        assert minutes(c.ticks[0], c.now()) < 330 and f == 0

    # Manual evening start: ticks now, then until midnight; nothing at night.
    c, f = run(datetime(2026, 10, 16, 21, 0), tick_now=True)
    assert c.ticks[0].strftime("%H:%M") == "21:00" and c.ticks[-1].hour == 23, c.ticks[-1]
    assert all(t.hour >= 7 for t in c.ticks + c.quick)

    # Night run: no tick fits, so it sleeps the whole budget instead of chaining in a tight loop.
    c, f = run(datetime(2026, 10, 16, 23, 58))
    assert c.ticks == c.quick == c.cheap == [] and c.slept == BUDGET_MIN * 60, (c.ticks, c.slept)

    # Morning run started by the night run: the day starts with a tick at 07:03-07:12, no quick check before.
    for seed in range(5):
        c, f = run(datetime(2026, 10, 17, 5, 27), seed=seed)
        first = c.ticks[0]
        assert (7, 3) <= (first.hour, first.minute) <= (7, 12) and min(c.quick) > first, first

    # DST night (25.10): the budget is real minutes, so the job limit holds.
    c, f = run(datetime(2026, 10, 24, 23, 58))
    assert c.ticks == [] and c.slept == BUDGET_MIN * 60 and c.now().strftime("%H:%M") == "04:28", c.now()

    # A failed tick is counted (the run fails, GitHub e-mails) and the loop goes on;
    # two failed ticks in a row hand over at once (a new machine, a new address).
    c, f = run(datetime(2026, 10, 16, 12, 40), fail={3, 7})
    assert f == 2 and len(c.ticks) > 15, "single failures: the loop goes on"
    c, f = run(datetime(2026, 10, 16, 12, 40), fail={3, 4})
    assert f == 2 and len(c.ticks) == 5, len(c.ticks)
    c, f = run(datetime(2026, 10, 16, 12, 40), tick_now=True, fail=True)
    assert f == 2 and len(c.ticks) == 2 and len(c.quick) <= 2, "blocked from the start: hands over after two"
    print("loop tests passed")


if __name__ == "__main__":
    main()
