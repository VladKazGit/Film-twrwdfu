"""Tick loop timing on a fake clock. Run: python -m tests.test_loop"""
from datetime import datetime, timedelta, timezone

from tracker.env import BERLIN
from tracker.loop import BUDGET_MIN, run_loop


class FakeClock:
    """Real time kept in UTC; ticks take 2 minutes."""

    def __init__(self, berlin_start):
        self.utc = berlin_start.replace(tzinfo=BERLIN).astimezone(timezone.utc)
        self.ticks = []
        self.slept = 0.0

    def now(self):
        return self.utc.astimezone(BERLIN)

    def sleep(self, seconds):
        self.slept += seconds
        self.utc += timedelta(seconds=seconds)

    def tick(self, ok=True):
        self.ticks.append(self.now().strftime("%m-%d %H:%M"))
        self.utc += timedelta(minutes=2)
        return ok


def run(start, tick_now=False, fail=False):
    clock = FakeClock(start)
    failures = run_loop(clock.now, clock.sleep, lambda: clock.tick(not fail), tick_now=tick_now, log=lambda _: None)
    return clock, failures


def main():
    # Chained daytime run: waits for the next slot, ticks every 15 min, hands over right after a tick.
    c, f = run(datetime(2026, 10, 16, 12, 40))
    assert c.ticks[0] == "10-16 12:52" and c.ticks[-1] == "10-16 18:07" and len(c.ticks) == 22, c.ticks
    assert c.now().strftime("%H:%M") == "18:09" and f == 0
    gaps = {(datetime.strptime(b, "%m-%d %H:%M") - datetime.strptime(a, "%m-%d %H:%M")).seconds // 60
            for a, b in zip(c.ticks, c.ticks[1:])}
    assert gaps == {15}, gaps

    # Manual evening start: ticks now, then on slots until 23:52, hands over (night follows).
    c, f = run(datetime(2026, 10, 16, 21, 0), tick_now=True)
    assert c.ticks[0] == "10-16 21:00" and c.ticks[1] == "10-16 21:07" and c.ticks[-1] == "10-16 23:52", c.ticks
    assert c.now().strftime("%H:%M") == "23:54"

    # Night run: no tick fits, so it sleeps the whole budget instead of chaining in a tight loop.
    c, f = run(datetime(2026, 10, 16, 23, 55))
    assert c.ticks == [] and c.slept == BUDGET_MIN * 60, (c.ticks, c.slept)

    # Morning run started by the night run: first tick at 07:07.
    c, f = run(datetime(2026, 10, 17, 5, 27))
    assert c.ticks[0] == "10-17 07:07" and c.ticks[-1] == "10-17 10:52", c.ticks

    # DST night (25.10): the budget is real minutes, so the job limit holds.
    c, f = run(datetime(2026, 10, 24, 23, 55))
    assert c.ticks == [] and c.slept == BUDGET_MIN * 60 and c.now().strftime("%H:%M") == "04:25", c.now()

    # Failed ticks are counted (the run fails, GitHub e-mails), the loop goes on.
    c, f = run(datetime(2026, 10, 16, 12, 40), fail=True)
    assert f == len(c.ticks) == 22
    print("loop tests passed")


if __name__ == "__main__":
    main()
