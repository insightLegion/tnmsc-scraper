"""Command line: crawl, export, status.

    python -m tnmsc_scraper crawl [--only blacklist,drugrc,equipmentrc,awards,notifications] [--max-requests N] [--delay S] [--out DIR]
    python -m tnmsc_scraper export --csv DIR [--out DIR]
    python -m tnmsc_scraper status [--out DIR]

Exit codes: 0 = finished, 2 = stopped early (a limit, the STOP file, too many errors or refusals, or Ctrl-C), 1 = a program error.
"""
import argparse
import logging
import re
import signal
import sys
from collections import Counter
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__, fetch, parse
from .store import Store

log = logging.getLogger("tnmsc_scraper")
KINDS = ["blacklist", "drugrc", "equipmentrc", "awards", "notifications"]
DOC_KINDS = ("awards", "notifications")


def setup_logging(out):
    if hasattr(sys.stderr, "reconfigure"):                 # a redirected Windows console may not take Tamil text
        sys.stderr.reconfigure(errors="backslashreplace")
    (out / "logs").mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler()
    logfile = RotatingFileHandler(out / "logs" / "tnmsc-scraper.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in [h for h in root.handlers if getattr(h, "tnmsc", False)]:   # main() called again in the same process (tests)
        root.removeHandler(h)
        h.close()
    for h in (console, logfile):
        h.setFormatter(fmt)
        h.tnmsc = True
        root.addHandler(h)


def doc_path(url):
    """'.../linkfiles/contracts_awarded/CA1.pdf' -> docs/contracts_awarded/CA1.pdf (safe on Windows)."""
    parts = [re.sub(r"[^A-Za-z0-9._-]+", "_", p) for p in urlsplit(url).path.split("/") if p][-2:]
    return Path("docs", *parts)


def crawl(args, out):
    kinds = [k.strip() for k in args.only.split(",")] if args.only else KINDS
    bad = set(kinds) - set(KINDS)
    if bad:
        log.error("unknown kind(s) for --only: %s (choose from %s)", ", ".join(sorted(bad)), ", ".join(KINDS))
        return 1
    lim = fetch.Limits(delay=args.delay, jitter=args.jitter, max_requests=args.max_requests, max_per_host=args.max_per_host,
                       max_seconds=args.max_minutes * 60, max_bytes=int(args.max_mb * fetch.MB),
                       max_file_bytes=int(args.max_file_mb * fetch.MB), max_errors=args.max_errors, max_refusals=args.max_refusals,
                       timeout=args.timeout)
    f = fetch.Fetcher(lim, fetch.new_session(args.proxy, args.ca_bundle), stop_files=[Path("STOP"), out / "STOP"])
    st = Store(out / "tnmsc.sqlite")
    run_id = st.start_run(vars(args))
    counts, reason, code = Counter(), "finished", 0

    def on_ctrl_c(sig, frame):
        f.interrupted = True
        log.warning("Ctrl-C: stopping after the current request (press Ctrl-C again to quit at once)")
        signal.signal(signal.SIGINT, signal.default_int_handler)

    old_handler = signal.signal(signal.SIGINT, on_ctrl_c)
    log.info("crawl %s into %s (max %d requests, %.0f min, delay %.1f-%.1f s)", ",".join(kinds), out, lim.max_requests,
             args.max_minutes, lim.delay, lim.delay + lim.jitter)
    try:
        doc_rows = []
        for kind, arg in [p for p in parse.PAGES if p[0] in kinds]:
            url = parse.url_of(kind, arg)
            old = st.page(url)
            has_copy = old is not None and old["body"] is not None
            res = f.get(url, *((old["etag"], old["last_modified"]) if has_copy else (None, None)))
            if res is None or res.status not in (200, 304) or (res.status == 304 and not has_copy):
                log.warning("%s: no page (HTTP %s)", url, res.status if res else "skipped")
                counts["failed"] += 1
                if res is not None:
                    with st.db:
                        st.save_page(url, kind, arg, res)
                continue
            body = res.body if res.status == 200 else old["body"]
            rows = parse.parse(kind, fetch.Result(url, 200, body, res.headers).text(), arg)
            with st.db:                                    # page and its records in one transaction
                st.save_page(url, kind, arg, res, body=body, n_records=len(rows))
                st.upsert(rows)
            counts["pages"] += 1
            counts["records"] += len(rows)
            log.info("%s %s: %d records%s", kind, arg or "", len(rows), " (not modified)" if res.status == 304 else "")
            if not rows:
                log.warning("%s: the page has no rows (it may be empty on the site now)", url)
            if args.docs and kind in DOC_KINDS:
                doc_rows += rows
        if args.docs:
            download_docs(f, st, out, doc_rows, counts)
    except fetch.StopRun as e:
        reason, code = str(e), 2
        log.warning("stopped: %s", reason)
    finally:
        signal.signal(signal.SIGINT, old_handler)
        counts.update({k: f.counts[k] for k in ("requests", "bytes", "errors", "refusals", "not_modified")})
        st.end_run(run_id, counts, reason)
        st.close()
    log.info("run %d: %s; %d requests, %.1f MB, %d pages, %d records, %d failed", run_id, reason, counts["requests"],
             counts["bytes"] / fetch.MB, counts["pages"], counts["records"], counts["failed"])
    return code


def download_docs(f, st, out, rows, counts):
    """Linked PDFs of awards and notifications. A PDF already on disk is not fetched again."""
    for url in parse.doc_urls(rows):
        old = st.page(url)
        if old is not None and old["path"] and (out / old["path"]).exists():
            continue
        res = f.get(url)
        if res is None or res.status != 200:
            counts["failed"] += 1
            if res is not None:
                with st.db:
                    st.save_page(url, "doc", None, res)
            continue
        rel = doc_path(url)
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        tmp = (out / rel).with_suffix(".part")
        tmp.write_bytes(res.body)
        tmp.replace(out / rel)                             # a file on disk is always complete
        with st.db:
            st.save_page(url, "doc", None, res, path=rel.as_posix())
        counts["docs"] += 1


def export(args, out):
    st = Store(out / "tnmsc.sqlite")
    for kind, n in st.export_csv(args.csv).items():
        log.info("%s.csv: %d rows", kind, n)
    st.close()
    return 0


def status(args, out):
    st = Store(out / "tnmsc.sqlite")
    kinds, (n_pages, n_ok, last), runs = st.status()
    st.close()
    print(f"database: {out / 'tnmsc.sqlite'}")
    print(f"pages: {n_pages} ({n_ok or 0} with HTTP 200), last checked {last or '-'}")
    for k, n in kinds.items():
        print(f"  {k}: {n} records")
    for r in runs:
        print(f"run {r['id']} {r['started_at']} -> {r['ended_at'] or '?'}: {r['requests']} requests, {r['records']} records, "
              f"{r['stop_reason']}")
    return 0


def build_parser():
    d = fetch.Limits()
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", default="data", help="folder for the database, logs and documents (default: data)")
    p = argparse.ArgumentParser(prog="tnmsc-scraper", description="Polite scraper for tnmsc.tn.gov.in public lists.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crawl", parents=[common], help="fetch the list pages and store the records")
    c.add_argument("--only", help=f"comma-separated kinds: {','.join(KINDS)} (default: all)")
    c.add_argument("--docs", action="store_true", help="also download the PDFs linked from awards and notifications")
    c.add_argument("--delay", type=float, default=d.delay, help=f"minimum seconds between requests (default {d.delay})")
    c.add_argument("--jitter", type=float, default=d.jitter, help=f"random extra seconds 0..N (default {d.jitter})")
    c.add_argument("--max-requests", type=int, default=d.max_requests, help=f"default {d.max_requests}")
    c.add_argument("--max-per-host", type=int, default=d.max_per_host, help=f"default {d.max_per_host}")
    c.add_argument("--max-minutes", type=float, default=d.max_seconds / 60, help=f"default {d.max_seconds / 60:.0f}")
    c.add_argument("--max-mb", type=float, default=d.max_bytes / fetch.MB, help="MB downloaded per run (default 500)")
    c.add_argument("--max-file-mb", type=float, default=d.max_file_bytes / fetch.MB, help="largest file in MB (default 50)")
    c.add_argument("--max-errors", type=int, default=d.max_errors, help=f"consecutive errors before stopping (default {d.max_errors})")
    c.add_argument("--max-refusals", type=int, default=d.max_refusals,
                   help=f"consecutive 403/429/503 before stopping (default {d.max_refusals})")
    c.add_argument("--timeout", type=float, default=d.timeout, help=f"seconds per request (default {d.timeout:.0f})")
    c.add_argument("--proxy", help="proxy URL (default: HTTPS_PROXY / HTTP_PROXY from the environment)")
    c.add_argument("--ca-bundle", help="CA certificates file (PEM) instead of certifi's")
    e = sub.add_parser("export", parents=[common], help="write one CSV file per record kind")
    e.add_argument("--csv", required=True, help="folder for the CSV files")
    sub.add_parser("status", parents=[common], help="show what the database holds and the last runs")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = Path(args.out)
    setup_logging(out)
    return {"crawl": crawl, "export": export, "status": status}[args.cmd](args, out)
