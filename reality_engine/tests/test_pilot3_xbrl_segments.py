"""Segment reader (night loop 2): Ind AS, life-insurer and single-segment instance shapes, name mapping, reconcile."""
from __future__ import annotations

import sqlite3

from reality_engine.pilot3 import kpi, xbrl_segments as xs

NS = ('xmlns="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
      'xmlns:in-capmkt="http://x/in-capmkt"')


def _ctx(cid, axis=None, member=None, start="2026-07-01", end="2026-09-30", instant=False):
    period = f"<instant>{end}</instant>" if instant else f"<startDate>{start}</startDate><endDate>{end}</endDate>"
    dim = f'<xbrldi:explicitMember dimension="in-capmkt:{axis}">in-capmkt:{member}</xbrldi:explicitMember>' if axis else ""
    seg = f"<segment>{dim}</segment>" if dim else ""
    return f'<context id="{cid}"><entity><identifier scheme="x">1</identifier>{seg}</entity><period>{period}</period></context>'


def _fact(concept, cid, value):
    return f'<in-capmkt:{concept} contextRef="{cid}">{value}</in-capmkt:{concept}>'


def _write(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(f"<xbrl {NS}>{body}</xbrl>", encoding="utf-8")
    return path


def _indas(tmp_path):
    body = "".join([
        _ctx("OneD"), _ctx("FourD", start="2026-04-01"),
        _ctx("R1", "ReportableSegmentsAxis", "ReportableSegments1Member"),
        _ctx("R2", "ReportableSegmentsAxis", "ReportableSegments2Member"),
        _ctx("Y1", "ReportableSegmentsAxis", "ReportableSegments1Member", start="2026-04-01"),
        _ctx("F1", "ReportableSegmentsFinanceCostsAxis", "ReportableSegments1Member"),
        _ctx("A1D", "ReportableSegmentAssetsAxis", "ReportableSegments1Member"),
        _ctx("A1I", "ReportableSegmentAssetsAxis", "ReportableSegments1Member", instant=True),
        _fact("DescriptionOfReportableSegment", "R1", "(a) EPC"), _fact("SegmentRevenue", "R1", "49414400000"),
        _fact("DescriptionOfReportableSegment", "R2", "Others"), _fact("SegmentRevenue", "R2", "6133000000"),
        _fact("DescriptionOfReportableSegment", "Y1", "(a) EPC"), _fact("SegmentRevenue", "Y1", "95366500000"),
        _fact("DescriptionOfReportableSegment", "F1", "EPC"),
        _fact("SegmentProfitLossBeforeTaxAndFinanceCosts", "F1", "2376400000"),
        _fact("DescriptionOfReportableSegment", "A1D", "EPC"), _fact("SegmentAssets", "A1I", "229409300000"),
        _fact("InterSegmentRevenue", "OneD", "870300000"),
        _fact("SegmentRevenueFromOperations", "OneD", "54677100000"),
    ])
    return _write(tmp_path, "indas.xml", body)


def test_indas_segments_and_reconcile(tmp_path):
    parsed = xs.parse_file(_indas(tmp_path))
    rows = xs.segment_rows(parsed, "2026-09-30")
    got = {(r["metric"], xs.normalise(r["name"]), xs.period_label(r["start"], r["end"])[1]): r["value"] for r in rows}
    assert got[("segment_revenue", "epc", "Q2FY27")] == 49414400000
    assert got[("segment_revenue", "others", "Q2FY27")] == 6133000000
    assert got[("segment_revenue", "epc", "H1FY27")] == 95366500000
    assert got[("segment_ebit", "epc", "Q2FY27")] == 2376400000
    assert got[("segment_assets", "epc", "Q2FY27")] == 229409300000  # name joined from the sister duration context
    assert xs.reconcile(parsed, rows) == []  # 49414.4 + 6133.0 - 870.3 = 54677.1


def test_reconcile_reports_a_mismatch(tmp_path):
    parsed = xs.parse_file(_indas(tmp_path))
    parsed["totals"]["SegmentRevenueFromOperations"][("2026-07-01", "2026-09-30")] = 99e9
    fails = xs.reconcile(parsed, xs.segment_rows(parsed, "2026-09-30"))
    assert len(fails) == 1 and fails[0]["filing_total"] == 99e9


def test_life_insurer_revenue_is_sum_of_parts(tmp_path):
    body = "".join([
        _ctx("I1", "SegmentRevenueAxis", "ReportableSegmentsMember1"),
        _ctx("S1", "SegmentSurplusDeficitAxis", "ReportableSegmentsMember1"),
        _fact("DescriptionOfReportableSegments", "I1", "Participating Life"),
        _fact("NetPremium", "I1", "100"), _fact("IncomeFormInvestments", "I1", "20"), _fact("OtherIncome", "I1", "3"),
        _fact("TransferOfFundsFromShareholdersAccount", "I1", "0"),
        _fact("DescriptionOfReportableSegments", "S1", "Participating Life"), _fact("SurplusDeficit", "S1", "-7"),
    ])
    rows = {r["metric"]: r for r in xs.segment_rows(xs.parse_file(_write(tmp_path, "li.xml", body)), "2026-09-30")}
    assert rows["segment_revenue"]["value"] == 123 and rows["segment_revenue"]["is_reported"] == 0
    assert "NetPremium=100" in rows["segment_revenue"]["raw_value"]
    assert rows["segment_ebit"]["value"] == -7 and rows["segment_ebit"]["is_reported"] == 1
    assert rows["segment_ebit"]["label"] == "SurplusDeficit"


def test_single_segment_filing(tmp_path):
    body = "".join([
        _ctx("OneD"), _fact("IsCompanyReportingMultisegmentOrSingleSegment", "OneD", "Single segment"),
        _fact("DescriptionOfSingleSegment", "OneD", "NBFC"), _fact("RevenueFromOperations", "OneD", "500"),
        _fact("Income", "OneD", "520"), _fact("ProfitBeforeTax", "OneD", "90"), _fact("FinanceCosts", "OneD", "40"),
    ])
    parsed = xs.parse_file(_write(tmp_path, "single.xml", body))
    assert xs.segment_rows(parsed, "2026-09-30") == []
    rows = {r["metric"]: r for r in xs.single_rows(parsed, "2026-09-30")}
    assert rows["segment_revenue"]["value"] == 500 and rows["segment_ebit"]["value"] == 130
    assert rows["segment_revenue"]["label"] == "NBFC" and rows["segment_revenue"]["is_reported"] == 0


def test_name_normalisation_and_mapping():
    assert xs.normalise("(a) Novelis") == xs.normalise("Novelis") == "novelis"
    assert xs.normalise("Hi-Tech") == xs.normalise("Hi Tech") == "hi_tech"
    mapping = xs._canonical([("2026-09", ["fiancial_services", "linked_group_life"]), ("2026-06", ["financial_services", "linked_group"])])
    assert mapping["financial_services"] == "fiancial_services"  # ratio >= 0.85: the latest spelling
    assert mapping["linked_group"] == "linked_group"  # ratio 0.83: kept apart


def test_period_label():
    assert xs.period_label("2026-07-01", "2026-09-30") == ("Q", "Q2FY27")
    assert xs.period_label("2026-04-01", "2026-09-30") == ("H1", "H1FY27")
    assert xs.period_label("2025-04-01", "2025-12-31") == ("9M", "9MFY26")
    assert xs.period_label("2025-04-01", "2026-03-31") == ("FY", "FY26")
    assert xs.period_label(None, "2026-09-30") == ("Q", "Q2FY27")


def test_kpi_rebuild_keeps_segment_rows(tmp_path):
    db = tmp_path / "k.db"
    con = sqlite3.connect(db)
    con.executescript(kpi.SCHEMA)
    for name, ddl in kpi.NEW_COLS:
        try:
            con.execute(f"ALTER TABLE kpi_series ADD COLUMN {name} {ddl}")
        except sqlite3.OperationalError:
            pass
    ins = ("INSERT INTO kpi_series(symbol,metric,value,unit,period_type,fiscal_period,doc_key,page,quote,extractor_rule,source_type) "
           "VALUES('X','segment_revenue',1,'inr','Q','Q2FY27','f.xml',0,'','xbrl_segment','xbrl_segment')")
    con.execute(ins)
    con.execute(ins.replace("'segment_revenue'", "'order_book'").replace("'xbrl_segment')", "'')").replace("'xbrl_segment','", "'t','"))
    con.commit()
    con.execute("DELETE FROM kpi_series WHERE symbol=? AND source_type<>'xbrl_segment'", ("X",))
    assert [r[0] for r in con.execute("SELECT metric FROM kpi_series")] == ["segment_revenue"]
