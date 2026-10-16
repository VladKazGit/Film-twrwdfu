"""Vinted client retries, blocks and budgets on a fake session. Run: python -m tests.test_vinted"""
import requests

from tracker import vinted


class Resp:
    def __init__(self, code):
        self.status_code, self.content, self.text, self.headers, self.url = code, b"x", "", {}, "u"


def client(answers, **kw):
    c = vinted.VintedClient(delay=(0, 0), **kw)
    seq = list(answers)

    def get(url, params=None, timeout=None):
        a = seq.pop(0)
        if isinstance(a, Exception):
            raise a
        return Resp(a)

    c.session = type("S", (), {"get": staticmethod(get)})()
    return c


def outcome(c):
    try:
        return f"ok {c.fetch('u').status_code}"
    except vinted.BlockedError as exc:
        return f"blocked: {exc}"
    except vinted.VintedError as exc:
        return f"error: {exc}"


def main():
    vinted.RETRY_BACKOFF = (0, 0)
    assert outcome(client([503, 200])) == "ok 200"
    assert outcome(client([requests.ConnectionError(), 200])) == "ok 200"
    assert outcome(client([requests.Timeout()] * 3)) == "blocked: vinted not responding"
    assert outcome(client([429, 429, 429])) == "blocked: vinted not responding"
    c = client([503, 200, 503, 200, 503, 200])  # failures not in a row: no block
    assert [outcome(c) for _ in range(3)] == ["ok 200"] * 3
    assert outcome(client([200], time_budget=0)) == "error: time budget exhausted"
    print("vinted client tests passed")


if __name__ == "__main__":
    main()
