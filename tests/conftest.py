"""A fake clock and a fake HTTP transport: the tests never touch the network or really sleep."""
from pathlib import Path

import pytest
from requests.structures import CaseInsensitiveDict

PAGES = Path(__file__).parent / "pages"


def page(name):
    return (PAGES / name).read_text(encoding="utf-8")


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Resp:
    def __init__(self, status=200, body=b"x" * 600, headers=None):
        self.status_code, self.body, self.headers = status, body, CaseInsensitiveDict(headers or {})

    def iter_content(self, n):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]

    def close(self):
        pass


class FakeSession:
    """`answer(url, headers, n)` gives a Resp or an exception to raise; every call is kept with the clock time."""

    def __init__(self, clock, answer=lambda url, headers, n: Resp()):
        self.clock, self.answer, self.calls = clock, answer, []

    def get(self, url, headers=None, **kw):
        self.calls.append((self.clock(), url, dict(headers or {})))
        a = self.answer(url, headers or {}, len(self.calls))
        if isinstance(a, Exception):
            raise a
        return a


@pytest.fixture
def clock():
    return FakeClock()
