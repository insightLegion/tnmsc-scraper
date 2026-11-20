import csv
import sqlite3

from tnmsc_scraper import store as S


def test_upsert_is_idempotent(tmp_path, monkeypatch):
    st = S.Store(tmp_path / "db.sqlite")
    rows = [("blacklist:a", {"kind": "blacklist", "firm": "A"}), ("blacklist:b", {"kind": "blacklist", "firm": "B"})]
    monkeypatch.setattr(S, "now", lambda: "t1")
    with st.db:
        st.upsert(rows)
    monkeypatch.setattr(S, "now", lambda: "t2")
    with st.db:
        st.upsert(rows)
        st.upsert([("blacklist:b", {"kind": "blacklist", "firm": "B2"})])
    got = {r["id"]: dict(r) for r in st.db.execute("SELECT * FROM records")}
    assert len(got) == 2
    assert got["blacklist:a"]["first_seen"] == "t1" and got["blacklist:a"]["last_seen"] == "t2" and got["blacklist:a"]["changed_at"] == "t1"
    assert got["blacklist:b"]["changed_at"] == "t2" and '"B2"' in got["blacklist:b"]["data"]


def test_csv_export_utf8_for_excel(tmp_path):
    st = S.Store(tmp_path / "db.sqlite")
    with st.db:
        st.upsert([("drugrc:x", {"kind": "drugrc", "drug": "பாராசிட்டமால்", "list": [1, 2]}), ("award:CA1", {"kind": "award", "code": "CA1"})])
    assert st.export_csv(tmp_path / "csv") == {"award": 1, "drugrc": 1}
    raw = (tmp_path / "csv" / "drugrc.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with open(tmp_path / "csv" / "drugrc.csv", encoding="utf-8-sig", newline="") as f:
        assert list(csv.DictReader(f)) == [{"kind": "drugrc", "drug": "பாராசிட்டமால்", "list": "[1, 2]"}]
    st.close()
    assert sqlite3.connect(tmp_path / "db.sqlite").execute("SELECT count(*) FROM records").fetchone()[0] == 2
