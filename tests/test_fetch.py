"""Rate limiter and every hard stop, with a fake clock and a fake transport."""
import random

import pytest
import requests

from conftest import FakeSession, Resp
from tnmsc_scraper.fetch import Fetcher, Limits, StopRun

URL = "https://tnmsc.tn.gov.in/x"


def fetcher(clock, answer=None, rand=lambda a, b: b, stop_files=(), **lim):
    s = FakeSession(clock, answer) if answer else FakeSession(clock)
    return Fetcher(Limits(**lim), s, stop_files=stop_files, clock=clock, sleep=clock.sleep, rand=rand), s


def gaps(s):
    t = [c[0] for c in s.calls]
    return [round(b - a, 6) for a, b in zip(t, t[1:])]


def test_delay_with_jitter_between_requests(clock):
    f, s = fetcher(clock, rand=random.Random(1).uniform, delay=3, jitter=2)
    for _ in range(6):
        assert f.get(URL).status == 200
    assert s.calls[0][0] == 0 and len(gaps(s)) == 5
    assert all(3 <= g <= 5 for g in gaps(s)) and len(set(gaps(s))) > 1


def test_max_requests(clock):
    f, s = fetcher(clock, max_requests=3)
    for _ in range(3):
        f.get(URL)
    with pytest.raises(StopRun, match="max requests"):
        f.get(URL)
    assert len(s.calls) == 3


def test_max_per_host(clock):
    f, s = fetcher(clock, max_per_host=2)
    f.get(URL), f.get(URL), f.get("https://other.example/")
    with pytest.raises(StopRun, match="per host"):
        f.get(URL)
    assert len(s.calls) == 3


def test_max_run_time(clock):
    f, s = fetcher(clock, delay=3, jitter=0, max_seconds=10)
    with pytest.raises(StopRun, match="run time"):
        while True:
            f.get(URL)
    assert [c[0] for c in s.calls] == [0, 3, 6, 9]


def test_max_bytes(clock):
    f, s = fetcher(clock, max_bytes=1000)
    f.get(URL)
    with pytest.raises(StopRun, match="max bytes"):
        f.get(URL)                                         # stops while reading the second 600-byte body
    with pytest.raises(StopRun, match="max bytes"):
        f.get(URL)
    assert len(s.calls) == 2


def test_max_file_size_skips_the_file(clock):
    big = {URL: Resp(body=b"x" * 600), URL + "2": Resp(body=b"", headers={"Content-Length": "999999"})}
    f, s = fetcher(clock, lambda url, h, n: big.get(url, Resp(body=b"ok")), max_file_bytes=100)
    assert f.get(URL) is None and f.get(URL + "2") is None
    assert f.get(URL + "3").body == b"ok" and f.counts["too_large"] == 2


def test_consecutive_refusals_back_off_then_stop(clock):
    f, s = fetcher(clock, lambda url, h, n: Resp(429), delay=3, jitter=0)
    with pytest.raises(StopRun, match="5 consecutive refusals"):
        f.get(URL)
    assert gaps(s) == [10, 20, 40, 80] and f.counts["refusals"] == 5


def test_refusals_reset_after_success(clock):
    f, s = fetcher(clock, lambda url, h, n: Resp(200) if n in (4, 8) else Resp(403))
    assert f.get(URL).status == 200 and f.get(URL).status == 200
    assert len(s.calls) == 8


def test_retry_after(clock):
    f, s = fetcher(clock, lambda url, h, n: Resp(503, headers={"Retry-After": "120"}) if n == 1 else Resp(), jitter=0)
    assert f.get(URL).status == 200 and gaps(s) == [120]
    f, s = fetcher(clock, lambda url, h, n: Resp(429, headers={"Retry-After": "3600"}))
    with pytest.raises(StopRun, match="Retry-After"):
        f.get(URL)
    assert len(s.calls) == 1


def test_consecutive_errors(clock):
    f, s = fetcher(clock, lambda url, h, n: requests.ConnectionError("refused") if n % 2 else Resp(500), max_errors=4)
    with pytest.raises(StopRun, match="4 consecutive errors"):
        f.get(URL)
    assert len(s.calls) == 4 and f.counts["errors"] == 4


def test_not_found_is_returned_not_retried(clock):
    f, s = fetcher(clock, lambda url, h, n: Resp(404))
    assert f.get(URL).status == 404 and len(s.calls) == 1


def test_stop_file(clock, tmp_path):
    stop = tmp_path / "STOP"
    f, s = fetcher(clock, stop_files=[stop])
    f.get(URL), f.get(URL)
    stop.write_text("")
    with pytest.raises(StopRun, match="STOP file"):
        f.get(URL)
    assert len(s.calls) == 2


def test_stop_file_during_back_off(clock, tmp_path):
    stop = tmp_path / "STOP"

    def answer(url, h, n):
        stop.write_text("")                                # appears while the client waits to retry
        return Resp(503)
    f, s = fetcher(clock, answer, stop_files=[stop])
    with pytest.raises(StopRun, match="STOP file"):
        f.get(URL)
    assert len(s.calls) == 1 and clock() < 1


def test_ctrl_c_flag(clock):
    f, s = fetcher(clock)
    f.get(URL)
    f.interrupted = True
    with pytest.raises(StopRun, match="interrupted"):
        f.get(URL)
    assert len(s.calls) == 1


def test_conditional_get(clock):
    f, s = fetcher(clock, lambda url, h, n: Resp(304, b"") if "If-Modified-Since" in h else Resp())
    r = f.get(URL, etag='"abc"', last_modified="Wed, 01 Jan 2025 00:00:00 GMT")
    assert r.status == 304 and s.calls[0][2] == {"If-None-Match": '"abc"', "If-Modified-Since": "Wed, 01 Jan 2025 00:00:00 GMT"}
    assert f.counts["not_modified"] == 1
