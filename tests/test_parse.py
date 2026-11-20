"""Parsers on saved pages (2026-11-14; long lists trimmed, contact column removed)."""
from conftest import page
from tnmsc_scraper import htmltables as H
from tnmsc_scraper import parse as tnmsc


def test_blacklist():
    rows = tnmsc.parse_blacklist(page("tnmsc-blacklist.html"))
    assert len(rows) == 93 and len({r for r, _ in rows}) == 93
    assert {d["list"] for _, d in rows} == {"drug-item", "drug-firm", "equipment-firm"}
    first = rows[0][1]
    assert first["bl_code"] == "BL2425020" and first["firm"] == "SAI PARENTERALS LTD" and first["firm_code"] == "U0810"
    assert first["product"] == "MEROPENEM INJECTION IP - 500MG" and first["product_code"] == "749"
    assert first["from"] == "2024-11-25" and first["to"] == "2026-11-24" and first["nsq"] is True
    abbott = next(d for _, d in rows if d["bl_code"] == "BL2223002")
    assert abbott["list"] == "drug-firm" and abbott["product"] is None and "Pharmaceutical division" in abbott["note"]
    assert sum(d["nsq"] for _, d in rows) == 50


def test_awards_and_notifications():
    aw = tnmsc.parse_awards(page("tnmsc-awards-2014.html"), 2014)
    assert len(aw) == 51 and aw[0][0] == "award:CA1"
    assert aw[0][1]["url"] == "https://tnmsc.tn.gov.in/linkfiles/contracts_awarded/CA1.pdf" and aw[0][1]["ref_date"] == "2009-05-21"
    nf = tnmsc.parse_notifications(page("tnmsc-notifications-2027.html"), 2027)
    assert [r for r, _ in nf] == ["notification:NF1808", "notification:NF1807", "notification:NF1806"]
    assert nf[0][1]["period"] == "2026-2027" and nf[0][1]["url"].endswith("/linkfiles/tender_notifications/NF1808.pdf")
    assert len(tnmsc.doc_urls(aw + nf)) == 54


def test_drug_rate_contract_with_tenderers():
    rows = tnmsc.parse_drug_rc(page("tnmsc-drugrc-t25048.html"), "t25048")
    drugs = [d for _, d in rows if d["kind"] == "drugrc"]
    bids = [d for _, d in rows if d["kind"] == "drugrc-bid"]
    assert len(drugs) == 12 and len(rows) == len({r for r, _ in rows})
    assert drugs[0]["tender"] == "T25048" and drugs[0]["tender_ref_no"] == "E-022/M(P)/SPL-DRUGS/TNMSC/2025"
    assert drugs[0]["tender_title"] == "Speciality Drug Rate Contract Details"
    b = next(d for d in bids if d["drug_code"] == "G6")
    assert b["firm"] == "NIXI LABORATORIES PVT LTD" and b["firm_code"] == "U1565" and b["rate"] == 12.65 and b["order_pct"] == 100.0
    old = tnmsc.parse_drug_rc(page("tnmsc-drugrc-t18033.html"), "t18033")
    assert len(old) == 3 and old[0][1]["tender_title"].startswith("Surgical Item - Validity from")


def test_equipment_rate_contract_breakups():
    rows = tnmsc.parse_equipment_rc(page("tnmsc-equipmentrc.html"), "EQUIPMENT")
    assert len(rows) == len({r for r, _ in rows})
    first = rows[0][1]
    assert (first["equipment"], first["make"], first["rate_ex_gst"], first["rate"], first["valid_upto"]) == \
        ("Dissection Microscope", "Kwality Micro Scientific", 1280.0, 1510.4, "2026-09-24")
    item4 = rows[3][0]
    assert rows[4][1]["breakup_of"] == item4 and rows[4][1]["sl"] is None


def test_empty_page_gives_no_rows():
    assert tnmsc.parse("drugrc", "<html><body>Drug List --> </body></html>", "t21083") == []


def test_helpers():
    assert H.iso_date("Wed Mar 09 13:30:00 IST 2016") == "2016-03-09" and H.iso_date("26-OCT-2026") == "2026-10-26"
    assert H.num("2,37,000.00") == 237000.0 and H.num("-") is None
    assert tnmsc.url_of("equipmentrc", "REAGENTS/KITS/CONSUMABLES").endswith("group=REAGENTS%2FKITS%2FCONSUMABLES")
    assert len(tnmsc.PAGES) == 31
