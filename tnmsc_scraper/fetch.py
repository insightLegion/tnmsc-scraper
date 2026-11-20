"""A polite HTTP client: one session, one request at a time, a delay with jitter between requests, conditional GET, and hard
stops (requests, run time, bytes, consecutive errors or refusals, a STOP file, Ctrl-C). Nothing here writes to disk."""
import logging
import random
import time
from collections import Counter
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

import certifi
import requests

from . import __version__

log = logging.getLogger(__name__)

# Put a real contact page or e-mail address here before long runs, so the site's administrators can reach you.
USER_AGENT = f"tnmsc-scraper/{__version__} (public procurement data research; +https://example.invalid/contact)"
MB = 1024 * 1024
REFUSALS = {403, 429, 503}


@dataclass
class Limits:
    delay: float = 3.0              # minimum seconds between the end of one request and the start of the next
    jitter: float = 2.0             # plus a random 0..jitter seconds
    max_requests: int = 300         # per run, all hosts
    max_per_host: int = 300         # per run, per host
    max_seconds: float = 30 * 60    # run time
    max_bytes: int = 500 * MB       # downloaded per run
    max_file_bytes: int = 50 * MB   # one response; a larger one is skipped, not stored
    max_errors: int = 5             # consecutive connection errors, timeouts or 5xx answers
    max_refusals: int = 5           # consecutive 403 / 429 / 503 answers
    backoff: float = 10.0           # first back-off after an error or refusal; doubles each time
    max_wait: float = 300.0         # longest back-off; a longer Retry-After stops the run
    timeout: float = 60.0           # connect and read timeout per request


class StopRun(Exception):
    """A hard stop. The message is the stop reason."""


class TooLarge(Exception):
    pass


@dataclass
class Result:
    url: str
    status: int
    body: bytes
    headers: "requests.structures.CaseInsensitiveDict"

    def text(self):
        """The body as text: the declared charset, else UTF-8, else Windows-1252."""
        ct = (self.headers.get("Content-Type") or "").lower()
        cs = ct.split("charset=")[1].split(";")[0].strip() if "charset=" in ct else None
        for enc in [cs, "utf-8"] if cs else ["utf-8"]:
            try:
                return self.body.decode(enc)
            except (LookupError, UnicodeDecodeError):
                pass
        return self.body.decode("cp1252", errors="replace")


def new_session(proxy=None, ca_bundle=None):
    """requests also reads HTTPS_PROXY / HTTP_PROXY from the environment; `proxy` overrides them."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en"})
    s.verify = str(ca_bundle) if ca_bundle else certifi.where()
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    return s


def retry_after(headers):
    """Seconds from a Retry-After header (seconds or an HTTP date), or None."""
    v = (headers.get("Retry-After") or "").strip()
    if not v:
        return None
    if v.isdigit():
        return float(v)
    try:
        return max(0.0, parsedate_to_datetime(v).timestamp() - time.time())
    except (TypeError, ValueError):
        return None


class Fetcher:
    """`get()` returns a Result, or None for a file over the size limit; it raises StopRun on a hard stop.
    `clock`, `sleep` and `rand` are injectable so tests run with a fake clock and no network."""

    def __init__(self, limits=None, session=None, stop_files=(), clock=time.monotonic, sleep=time.sleep, rand=random.uniform):
        self.lim = limits or Limits()
        self.s = session or new_session()
        self.stop_files = [Path(p) for p in stop_files]
        self.clock, self._sleep, self.rand = clock, sleep, rand
        self.start = self.next_at = clock()
        self.requests = self.bytes = 0
        self.per_host = Counter()
        self.errors = self.refusals = 0             # consecutive
        self.counts = Counter()                     # totals for the runs table
        self.interrupted = False                    # set by the Ctrl-C handler

    def check(self, host):
        lim = self.lim
        if self.interrupted:
            raise StopRun("interrupted (Ctrl-C)")
        for p in self.stop_files:
            if p.exists():
                raise StopRun(f"STOP file found: {p}")
        if self.requests >= lim.max_requests:
            raise StopRun(f"max requests reached ({lim.max_requests})")
        if self.per_host[host] >= lim.max_per_host:
            raise StopRun(f"max requests per host reached ({host}: {lim.max_per_host})")
        if self.clock() - self.start >= lim.max_seconds:
            raise StopRun(f"max run time reached ({lim.max_seconds:.0f} s)")
        if self.bytes >= lim.max_bytes:
            raise StopRun(f"max bytes reached ({self.bytes})")

    def wait(self, seconds):
        """Sleep in short steps, so Ctrl-C and the STOP file act within half a second."""
        end = self.clock() + seconds
        if end - self.start >= self.lim.max_seconds:
            raise StopRun(f"max run time reached ({self.lim.max_seconds:.0f} s) during a wait")
        while (left := end - self.clock()) > 0:
            if self.interrupted or any(p.exists() for p in self.stop_files):
                self.check("")
            self._sleep(min(0.5, left))

    def get(self, url, etag=None, last_modified=None):
        host = urlsplit(url).hostname or ""
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        while True:
            self.check(host)
            self.wait(self.next_at - self.clock())
            self.check(host)
            self.requests += 1
            self.per_host[host] += 1
            self.counts["requests"] += 1
            res, problem = None, None
            try:
                res = self._fetch(url, headers)
            except TooLarge as e:
                log.warning("%s: skipped, larger than %d bytes (%s)", url, self.lim.max_file_bytes, e)
                self.counts["too_large"] += 1
                return None
            except requests.RequestException as e:
                problem = f"{type(e).__name__}: {e}"[:200]
            finally:
                self.next_at = self.clock() + self.lim.delay + self.rand(0, self.lim.jitter)
            if res is not None and res.status not in REFUSALS and res.status < 500:
                self.errors = self.refusals = 0
                if res.status == 304:
                    self.counts["not_modified"] += 1
                return res
            if res is not None and res.status in REFUSALS:
                self.refusals += 1
                self.counts["refusals"] += 1
                n, limit, what = self.refusals, self.lim.max_refusals, "refusals"
            else:
                self.errors += 1
                self.counts["errors"] += 1
                n, limit, what = self.errors, self.lim.max_errors, "errors"
            last = problem or f"HTTP {res.status}"
            if n >= limit:
                raise StopRun(f"{n} consecutive {what} (last: {last} for {url})")
            pause = min(self.lim.max_wait, self.lim.backoff * 2 ** (n - 1))
            ra = retry_after(res.headers) if res is not None else None
            if ra is not None:
                if ra > self.lim.max_wait:
                    raise StopRun(f"Retry-After {ra:.0f} s is longer than max wait {self.lim.max_wait:.0f} s ({url})")
                pause = max(pause, ra)
            log.warning("%s: %s; %s %d of %d, waiting %.0f s", url, last, what[:-1], n, limit, pause)
            self.next_at = max(self.next_at, self.clock() + pause)

    def _fetch(self, url, headers):
        r = self.s.get(url, headers=headers, timeout=self.lim.timeout, stream=True, allow_redirects=True)
        try:
            size = int(r.headers.get("Content-Length") or 0)
            if size > self.lim.max_file_bytes:
                raise TooLarge(f"Content-Length {size}")
            chunks, n = [], 0
            for chunk in r.iter_content(64 * 1024):
                n += len(chunk)
                self.bytes += len(chunk)
                self.counts["bytes"] += len(chunk)
                if n > self.lim.max_file_bytes:
                    raise TooLarge(f"{n} bytes read")
                if self.bytes > self.lim.max_bytes:
                    raise StopRun(f"max bytes reached ({self.lim.max_bytes}) while reading {url}")
                if self.interrupted:
                    raise StopRun("interrupted (Ctrl-C)")
                chunks.append(chunk)
            return Result(url, r.status_code, b"".join(chunks), r.headers)
        finally:
            r.close()
