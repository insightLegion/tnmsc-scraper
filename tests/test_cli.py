"""The crawl command end to end with a fake transport (no network, no real waits)."""
import sqlite3

import pytest

from conftest import FakeSession, Resp, page
from tnmsc_scraper import cli, fetch

BLACKLIST = page("tnmsc-blacklist.html").encode("utf-8")


@pytest.fixture
def site(monkeypatch, tmp_path):
    """A fake site: the blacklist page with a Last-Modified header; 304 when the client sends If-Modified-Since."""
    monkeypatch.chdir(tmp_path)
    sess = FakeSession(lambda: 0.0, lambda url, h, n: Resp(304, b"") if "If-Modified-Since" in h else
                       Resp(200, BLACKLIST, {"Content-Type": "text/html; charset=UTF-8", "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT"}))
    monkeypatch.setattr(fetch, "new_session", lambda proxy=None, ca=None: sess)
    return sess


def run(*args):
    return cli.main(["crawl", "--only", "blacklist", "--delay", "0", "--jitter", "0", "--out", "out", *args])


def db(tmp_path):
    return sqlite3.connect(tmp_path / "out" / "tnmsc.sqlite")


def test_crawl_then_not_modified_then_export(site, tmp_path):
    assert run() == 0
    assert run() == 0
    c = db(tmp_path)
    assert c.execute("SELECT count(*) FROM records WHERE kind = 'blacklist'").fetchone()[0] == 93
    assert c.execute("SELECT status, n_records FROM pages").fetchall() == [(304, 93)]
    assert c.execute("SELECT requests, records, not_modified, stop_reason FROM runs ORDER BY id").fetchall() == \
        [(1, 93, 0, "finished"), (1, 93, 1, "finished")]
    assert cli.main(["export", "--csv", "csv", "--out", "out"]) == 0
    assert len((tmp_path / "csv" / "blacklist.csv").read_text(encoding="utf-8-sig").splitlines()) == 94
    assert (tmp_path / "out" / "logs" / "tnmsc-scraper.log").exists()
    assert cli.main(["status", "--out", "out"]) == 0


def test_stop_file_ends_run_with_code_2(site, tmp_path):
    (tmp_path / "STOP").write_text("")
    assert run() == 2 and site.calls == []
    assert db(tmp_path).execute("SELECT stop_reason FROM runs").fetchone()[0].startswith("STOP file")


def test_max_requests_ends_run_with_code_2(site, tmp_path):
    assert run("--max-requests", "0") == 2
    assert "max requests" in db(tmp_path).execute("SELECT stop_reason FROM runs").fetchone()[0]


def test_unknown_kind(site):
    assert cli.main(["crawl", "--only", "blacklist,nope", "--out", "out"]) == 1


def test_doc_path_is_safe_on_windows():
    assert cli.doc_path("https://tnmsc.tn.gov.in/linkfiles/contracts_awarded/CA 1:x.pdf").as_posix() == "docs/contracts_awarded/CA_1_x.pdf"


def test_docs_are_downloaded_once(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    nf = page("tnmsc-notifications-2027.html").encode("utf-8")

    def answer(url, h, n):
        if url.endswith(".pdf"):
            return Resp(200, b"%PDF-1.4 " + url.encode())
        return Resp(304, b"") if "If-Modified-Since" in h else Resp(200, nf if "dt=2027" in url else b"<html></html>",
                                                                  {"Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT"})
    sess = FakeSession(lambda: 0.0, answer)
    monkeypatch.setattr(fetch, "new_session", lambda proxy=None, ca=None: sess)
    args = ["crawl", "--only", "notifications", "--docs", "--delay", "0", "--jitter", "0", "--out", "out"]
    assert cli.main(args) == 0
    assert len(sess.calls) == 4 + 3                        # four years of notifications, three PDFs
    assert (tmp_path / "out" / "docs" / "tender_notifications" / "NF1808.pdf").read_bytes().startswith(b"%PDF")
    assert cli.main(args) == 0
    assert len(sess.calls) == 7 + 4                        # pages again (304), no PDF again
