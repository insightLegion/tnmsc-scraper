"""SQLite state and data: fetched pages (body, sha256, ETag / Last-Modified), records by kind (upsert on the site's stable id),
and one row per run with its counters and stop reason. CSV export per record kind."""
import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url TEXT PRIMARY KEY, kind TEXT, arg TEXT, status INTEGER, etag TEXT, last_modified TEXT, sha256 TEXT, bytes INTEGER,
    fetched_at TEXT, checked_at TEXT, body BLOB, path TEXT, n_records INTEGER);
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, data TEXT NOT NULL, first_seen TEXT, last_seen TEXT, changed_at TEXT);
CREATE INDEX IF NOT EXISTS records_kind ON records(kind);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY, started_at TEXT, ended_at TEXT, args TEXT, requests INTEGER, bytes INTEGER, pages INTEGER,
    records INTEGER, errors INTEGER, refusals INTEGER, not_modified INTEGER, failed INTEGER, stop_reason TEXT);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    def page(self, url):
        return self.db.execute("SELECT * FROM pages WHERE url = ?", (url,)).fetchone()

    def save_page(self, url, kind, arg, res, body=None, path=None, n_records=None):
        """A 200 replaces the stored copy; any other status only updates status and checked_at."""
        t = now()
        if res.status == 200:
            self.db.execute(
                "INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (url, kind, None if arg is None else str(arg), res.status, res.headers.get("ETag"), res.headers.get("Last-Modified"),
                 hashlib.sha256(res.body).hexdigest(), len(res.body), t, t, body, path, n_records))
        else:
            self.db.execute(
                "INSERT INTO pages (url, kind, arg, status, checked_at, n_records) VALUES (?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE "
                "SET status = excluded.status, checked_at = excluded.checked_at, n_records = coalesce(excluded.n_records, n_records)",
                (url, kind, None if arg is None else str(arg), res.status, t, n_records))

    def upsert(self, rows):
        """rows: [(id, data)]. Same id again replaces the data; changed_at moves only when the data differs."""
        t = now()
        self.db.executemany(
            "INSERT INTO records (id, kind, data, first_seen, last_seen, changed_at) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE "
            "SET kind = excluded.kind, last_seen = excluded.last_seen, "
            "changed_at = CASE WHEN records.data <> excluded.data THEN excluded.last_seen ELSE records.changed_at END, "
            "data = excluded.data",
            [(rid, d.get("kind", rid.split(":")[0]), json.dumps(d, ensure_ascii=False), t, t, t) for rid, d in rows])
        return len(rows)

    def start_run(self, args):
        with self.db:
            return self.db.execute("INSERT INTO runs (started_at, args) VALUES (?, ?)",
                                   (now(), json.dumps(args, default=str))).lastrowid

    def end_run(self, run_id, counts, reason):
        c = {k: int(counts.get(k, 0)) for k in ("requests", "bytes", "pages", "records", "errors", "refusals", "not_modified", "failed")}
        with self.db:
            self.db.execute("UPDATE runs SET ended_at = ?, requests = ?, bytes = ?, pages = ?, records = ?, errors = ?, refusals = ?, "
                            "not_modified = ?, failed = ?, stop_reason = ? WHERE id = ?", (now(), *c.values(), reason, run_id))

    def export_csv(self, folder):
        """One <kind>.csv per record kind (UTF-8 with BOM, so Excel shows Tamil text). Lists and dicts are JSON text."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        out = {}
        for (kind,) in self.db.execute("SELECT DISTINCT kind FROM records ORDER BY kind").fetchall():
            rows = [json.loads(d) for (d,) in self.db.execute("SELECT data FROM records WHERE kind = ? ORDER BY id", (kind,))]
            cols = list(dict.fromkeys(k for r in rows for k in r))
            with open(folder / f"{kind}.csv", "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                for r in rows:
                    w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in r.items()})
            out[kind] = len(rows)
        return out

    def status(self):
        kinds = dict(self.db.execute("SELECT kind, count(*) FROM records GROUP BY kind ORDER BY kind").fetchall())
        pages = self.db.execute("SELECT count(*), sum(status = 200), max(checked_at) FROM pages").fetchone()
        runs = self.db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 5").fetchall()
        return kinds, tuple(pages), [dict(r) for r in runs]
