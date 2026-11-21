"""T-230 stage A-F: observation schema, independent checks and the writer (synthetic, no network)."""
import json
import shutil
import sqlite3
from pathlib import Path

from reality_engine.v2 import observations as obs

STORE = Path(".tmp/t230/test_c_store.db")
DECK = "D:/RealityEngine/raw/pilot60_history/NAVKARCORP/investor_presentation/deck.pdf"

PAGE = (
    "JSW Infrastructure Investor Presentation May 2025\n177\n292\n400\nFY25\nFY28E\nFY30E\n"
    "Projects Approved\nProjects Under Review\nPipeline of Potential Projects\nAll fig. in mtpa\n"
    "Jatadhar Port, Odisha\n30\nLiquid Berths at JNPA\n4.5\nLPG at Jaigarh\n2.0\n"
    "Container (New Mangalore)\n1.8\nKeni Port, Karnataka\n30\nPotential Projects\n45\n"
)
KNOWN_AT = "2025-05-13T15:27:33"


def reply(**kw):
    base = {"series_id": "s1", "series_title": "", "measure": "capacity.add", "printed_label": "",
            "printed_axis": "", "value_text": "30", "unit": "mtpa", "scale": 1, "period": "",
            "period_kind": "", "segment": "", "product": "", "geography": "", "plant": "", "customer": "",
            "group_path": "", "group_source": "", "stage": "", "entity_scope": "company", "is_total": False}
    base.update(kw)
    return base


def build(rows, page_text=PAGE, words=(), owner=""):
    return obs.build_observations(symbol="NAVKARCORP", doc_key=DECK, page=14, known_at=KNOWN_AT,
                                  page_text=page_text, words=words, reply_rows=rows,
                                  doc_owner_symbol=owner)


def test_schema_has_every_contract_column_and_the_dictionary():
    con = obs.create_db(":memory:")
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"observation", "measure_dict", "dim_vocab"} <= tables
    cols = {r[1] for r in con.execute("PRAGMA table_info(observation)")}
    assert {"symbol", "doc_key", "page", "region", "known_at", "measure", "printed_label", "printed_axis",
            "value", "value_text", "unit", "scale", "adjusted", "period", "period_kind", "segment", "product",
            "geography", "plant", "customer", "group_path", "group_source", "group_check", "stage", "series_id",
            "entity_scope", "status", "status_reason"} <= cols
    assert {"measure_proposal", "http_429", "measure_alias"} <= tables
    assert {r[1] for r in con.execute("PRAGMA table_info(measure_dict)")} == {"id", "name", "unit_family",
                                                                             "driver_node"}
    assert {r[1] for r in con.execute("PRAGMA table_info(dim_vocab)")} == {"kind", "canonical", "aliases"}
    assert con.execute("SELECT COUNT(*) FROM measure_dict WHERE id='capacity.add'").fetchone()[0] == 1
    con.close()


def test_value_label_group_and_region_are_checked_and_kept():
    words = [(10.0, 20.0, 30.0, 40.0, "30")]
    rows = build([reply(printed_label="Jatadhar Port, Odisha", printed_axis="FY28E", period="FY28E",
                        period_kind="estimate", group_path="Projects Under Review", group_source="printed",
                        geography="Odisha")], words=words)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "verified", row["status_reason"]
    assert row["value"] == 30.0 and row["value_text"] == "30"
    assert row["region"] == "10.0,20.0,30.0,40.0"
    assert row["period_kind"] == "estimate"
    assert row["geography"] == "Odisha"
    assert row["known_at"] == KNOWN_AT


def test_value_not_printed_on_the_page_is_quarantined():
    rows = build([reply(value_text="99")])
    assert rows[0]["status"] == "quarantined"
    assert "not in the page text layer" in rows[0]["status_reason"]


def test_page_with_no_text_layer_is_unverified():
    rows = build([reply()], page_text="")
    assert rows[0]["status"] == "unverified"
    assert "no text layer" in rows[0]["status_reason"]


def test_label_not_printed_is_unverified_not_repaired():
    rows = build([reply(printed_label="Imaginary Port")])
    assert rows[0]["status"] == "unverified"
    assert "printed_label" in rows[0]["status_reason"]


def test_number_boundary_so_30_is_not_found_inside_2030():
    assert obs.text_has("30 mtpa", "30") is True
    assert obs.text_has("2030 Road Map", "30") is False


def test_unit_families():
    assert obs.infer_unit_family("mtpa") == "capacity"
    assert obs.infer_unit_family("MT / Month") == "capacity"
    assert obs.infer_unit_family("Metric Tons per Month") == "capacity"
    assert obs.infer_unit_family("Rs crore") == "money"
    assert obs.infer_unit_family("Cr Ltrs.") == "count"
    assert obs.infer_unit_family("₹ per tonne per km") == "money_per_unit"
    assert obs.infer_unit_family("%") == "percent"
    assert obs.infer_unit_family("thousand units") == "count"
    assert obs.infer_unit_family("Thousands") == "count"
    assert obs.infer_unit_family("x") == "ratio"
    assert obs.infer_unit_family("") == ""
    assert obs.family_ok("count", "capacity") is True
    assert obs.family_ok("capacity", "percent") is False


def test_a_percent_value_never_takes_the_table_money_scale():
    page = "Consolidated (in INR Cr.) Q4FY25 EBITDA Margin % 10.3%"
    rows = build([reply(measure="ebitda_margin", value_text="10.3%", unit="%", scale=1e7,
                        printed_label="EBITDA Margin %", printed_axis="Q4FY25",
                        period="Q4FY25")], page_text=page)
    assert rows[0]["scale"] == 1
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]


def test_a_composed_axis_is_unverified_and_a_verbatim_axis_passes():
    composed = "FY21 Revenue from Operations 620.4 Consolidated (in INR Cr.)"
    rows = build([reply(measure="revenue_from_operations", value_text="620.4", unit="INR Cr",
                        printed_label="Revenue from Operations",
                        printed_axis="Consolidated (in INR Cr.) FY21", period="FY21")], page_text=composed)
    assert rows[0]["status"] == "unverified"
    assert "printed_axis" in rows[0]["status_reason"]


def test_unit_family_must_match_the_measure_dictionary():
    rows = build([reply(unit="%")])
    assert rows[0]["status"] == "unverified"
    assert "unit family" in rows[0]["status_reason"]


def test_measure_must_be_in_the_dictionary():
    rows = build([reply(measure="made.up")])
    assert rows[0]["status"] == "unverified"
    assert "measure is not in the dictionary" in rows[0]["status_reason"]


def test_scale_kept_only_when_printed():
    page = "Sale units (in Thousands) 705 899 Indian Tractor Industry"
    good = build([reply(measure="volume.sales", value_text="705", unit="thousand units", scale=1000,
                        printed_label="Indian Tractor Industry", printed_axis="Sale units (in Thousands)",
                        period="FY20", entity_scope="industry")], page_text=page)
    assert good[0]["scale"] == 1000
    assert good[0]["status"] == "verified", good[0]["status_reason"]
    bad = build([reply(measure="volume.sales", value_text="705", unit="units", scale=1e7,
                       printed_label="Indian Tractor Industry", printed_axis="FY20", period="FY20",
                       entity_scope="industry")], page_text="Indian Tractor Industry 705 FY20")
    assert bad[0]["scale"] == 1
    assert bad[0]["status"] == "unverified"
    assert "scale" in bad[0]["status_reason"]


def test_industry_figure_keeps_its_scope_and_an_unattributed_one_is_unverified():
    page = "Indian Tractor Industry 705 FY20 Sale units (in Thousands)"
    industry = build([reply(measure="volume.sales", value_text="705", unit="thousand units",
                            printed_label="Indian Tractor Industry", printed_axis="FY20", period="FY20",
                            entity_scope="industry")], page_text=page)
    assert industry[0]["entity_scope"] == "industry" and industry[0]["status"] == "verified"
    missing = build([reply(measure="volume.sales", value_text="705", unit="thousand units",
                           printed_label="Indian Tractor Industry", printed_axis="FY20", period="FY20",
                           entity_scope="")], page_text=page)
    assert missing[0]["status"] == "unverified"
    assert "entity_scope" in missing[0]["status_reason"]


def test_parts_summing_to_the_printed_total_verifies_and_a_mismatch_does_not():
    page = "Total capacity 100 Approved 40 Under Review 30 Potential 30 in mtpa FY25"
    rows = [reply(measure="capacity.total", printed_label="Total capacity", value_text="100", is_total=True,
                  period="FY25"),
            reply(printed_label="Approved", value_text="40", period="FY25"),
            reply(printed_label="Under Review", value_text="30", period="FY25"),
            reply(printed_label="Potential", value_text="30", period="FY25")]
    passed = build(rows, page_text=page)
    assert [r["status"] for r in passed] == ["verified"] * 4
    assert all("parts sum to the printed total 100" in r["status_reason"] for r in passed)

    rows[3] = reply(printed_label="Potential", value_text="20", period="FY25")
    failed = build(rows, page_text=page + " 20")
    assert all(r["status"] == "unverified" for r in failed)
    assert "parts sum to 90" in failed[0]["status_reason"]


def test_parts_sum_never_fires_on_an_unmarked_total():
    page = "Total capacity 100 Approved 40 Under Review 30 Potential 30 in mtpa"
    rows = [reply(measure="capacity.total", printed_label="Total capacity", value_text="100"),
            reply(printed_label="Approved", value_text="40"),
            reply(printed_label="Under Review", value_text="30")]
    rows = build(rows, page_text=page)
    assert all("parts sum" not in r["status_reason"] for r in rows)


def test_scale_abbreviation_cr_is_printed():
    page = "INR Cr. 1,268.8 Total Revenue FY25"
    rows = build([reply(measure="total_income", value_text="1,268.8", unit="INR Cr.", scale=1e7,
                        printed_label="Total Revenue", period="FY25")], page_text=page)
    assert rows[0]["scale"] == 1e7
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]


def test_scale_comes_from_the_printed_unit_when_the_reply_says_one():
    page = "Particulars (Rs in Crs) Mar-24 Total Equity 3.7"
    rows = build([reply(measure="total_equity", value_text="3.7", unit="Rs in Crs", scale=1,
                        printed_axis="Particulars (Rs in Crs)", printed_label="Total Equity",
                        period="Mar-24")], page_text=page)
    assert rows[0]["scale"] == 1e7
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]


def test_group_path_checks_each_printed_heading():
    page = "Greenfield Port Jatadhar Port Phase I Capacity 30 mtpa FY25"
    rows = build([reply(printed_label="Phase I Capacity", group_source="printed", period="FY25",
                        group_path="Greenfield Port > Jatadhar Port")], page_text=page)
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]
    rows = build([reply(printed_label="Phase I Capacity", group_source="printed", period="FY25",
                        group_path="Greenfield Port > Imaginary Port")], page_text=page)
    assert rows[0]["status"] == "unverified"
    assert "group_path" in rows[0]["status_reason"]


def test_parts_sum_ignores_a_group_holding_another_measure():
    page = "Total Revenue 334.4 EBITDA 34.3 PAT 13.5 INR Cr."
    rows = build([reply(measure="revenue.value", printed_label="Total Revenue", value_text="334.4", is_total=True),
                  reply(measure="ebitda", printed_label="EBITDA", value_text="34.3"),
                  reply(measure="pat", printed_label="PAT", value_text="13.5")], page_text=page)
    assert all("parts sum" not in r["status_reason"] for r in rows)


def test_script_label_table_overrides_the_model_measure():
    page = "Particulars (Rs in Crs) Mar-24 (ii) Trade payables 16.0"
    rows = build([reply(printed_label="(ii) Trade payables", value_text="16.0", unit="Rs in Crs",
                        measure="mystery.line", printed_axis="Particulars (Rs in Crs)", period="Mar-24")],
                 page_text=page)
    assert rows[0]["measure"] == "trade_payables"
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]


def test_retryable_errors_and_ist_clock():
    assert obs.RETRYABLE.search("HTTP 429: rate limit exceeded")
    assert obs.RETRYABLE.search("HTTP 502: bad gateway")
    assert not obs.RETRYABLE.search("HTTP 401: unauthorized")
    assert obs.ist_now().endswith("+05:30")
    assert obs.retry_after_seconds("8832") == 8832
    assert obs.retry_after_seconds(12.5) == 12.5
    assert obs.retry_after_seconds(None) is None
    assert obs.retry_after_seconds("Wed, 21 Oct 2026 07:28:00 GMT") is None


def test_a_quota_window_stops_calls_without_hammering():
    obs.set_quota(8832)
    try:
        result = obs.call_reader("prompt", None, "deck.pdf", 1)
        assert result.get("quota") == 8832
        assert result["error"] == "quota window"
    finally:
        with obs._QUOTA_LOCK:
            obs._QUOTA["seconds"] = 0.0


def test_missing_pages_skips_pages_a_stopped_run_already_wrote():
    con = obs.create_db(":memory:")
    rows = build([reply(printed_label="Jatadhar Port, Odisha")])
    obs.write_rows(con, rows)
    pages = [{"store": "s", "doc_key": DECK, "page": 14}, {"store": "s", "doc_key": DECK, "page": 15}]
    assert obs.missing_pages(con, pages) == [{"store": "s", "doc_key": DECK, "page": 15}]
    con.close()


def test_propose_with_no_limit_does_nothing():
    con = obs.create_db(":memory:")
    assert obs.propose_measures(con, 0) == {"labels": 0, "proposed": 0, "quota": False}
    con.close()


def test_proposals_stop_during_a_quota_window():
    con = obs.create_db(":memory:")
    page = "Some Label 12"
    rows = build([reply(measure="mystery.line", printed_label="Some Label", value_text="12")], page_text=page)
    obs.write_rows(con, rows)
    obs.set_quota(8832)
    try:
        assert obs.propose_measures(con, 5) == {"labels": 1, "proposed": 0, "quota": True}
    finally:
        with obs._QUOTA_LOCK:
            obs._QUOTA["seconds"] = 0.0
    con.close()


def test_junk_measures_are_dropped():
    rows = build([reply(measure="postal_code", value_text="400026", printed_label="Regd. Office, Mumbai")],
                 page_text="Regd. Office, Mumbai 400026")
    assert rows == []


def test_stage_is_read_from_a_printed_group_heading():
    rows = build([reply(group_path="Projects Under Review", group_source="printed",
                        printed_label="Keni Port, Karnataka")])
    assert rows[0]["stage"] == "under_review"
    rows = build([reply(group_path="Pipeline of Potential Projects", group_source="printed",
                        printed_label="Murbe Port, Maharashtra")])
    assert rows[0]["stage"] == "potential"


def test_legend_inferred_group_never_verifies():
    rows = build([reply(group_path="Projects Approved", group_source="legend_inferred",
                        printed_label="Jatadhar Port, Odisha")])
    assert rows[0]["group_source"] == "legend_inferred"
    assert rows[0]["status"] == "unverified"
    assert "colour/legend" in rows[0]["status_reason"]


def test_a_group_without_its_source_is_unverified():
    rows = build([reply(group_path="Projects Approved", printed_label="Jatadhar Port, Odisha")])
    assert rows[0]["status"] == "unverified"
    assert "group source" in rows[0]["status_reason"]


def test_legend_headings_override_a_printed_group_claim():
    page = ("Projects Approved Projects Under Review Pipeline of Potential Projects "
            "Jatadhar Port 30 Keni Port 30 Murbe Port 33 Potential Projects 45 mtpa")
    words = [
        (100.0, 380.0, 190.0, 392.0, "Projects"), (192.0, 380.0, 260.0, 392.0, "Approved"),
        (100.0, 400.0, 190.0, 412.0, "Projects"), (192.0, 400.0, 225.0, 412.0, "Under"),
        (227.0, 400.0, 270.0, 412.0, "Review"),
        (100.0, 420.0, 150.0, 432.0, "Pipeline"), (152.0, 420.0, 200.0, 432.0, "of"),
        (202.0, 420.0, 250.0, 432.0, "Potential"), (252.0, 420.0, 310.0, 432.0, "Projects"),
        (250.0, 300.0, 260.0, 310.0, "30"),
    ]
    rows = build([reply(printed_label="Jatadhar Port", value_text="30", group_path="Projects Approved",
                        group_source="printed"),
                  reply(printed_label="Murbe Port", value_text="33", group_path="Projects Under Review",
                        group_source="printed"),
                  reply(printed_label="Potential Projects", value_text="45",
                        group_path="Pipeline of Potential Projects", group_source="printed")],
                 page_text=page, words=words)
    assert [r["group_source"] for r in rows] == ["legend_inferred"] * 3
    assert all(r["status"] == "unverified" for r in rows)
    assert all("colour/legend" in r["status_reason"] for r in rows)


def test_path_sum_reproduces_a_printed_running_path():
    page = ("FY25 177 FY28E 292 FY30E 400 mtpa Jatadhar Port 30 Keni Port 30 Box 85 "
            "Murbe Port 33 Potential Projects 45")
    base = dict(measure="capacity.add", unit="mtpa", printed_axis="All fig. in mtpa", group_source="printed")
    rows = [
        reply(measure="capacity.total", value_text="177", period="FY25", printed_axis="All fig. in mtpa"),
        reply(measure="capacity.total", value_text="292", period="FY28E", printed_axis="All fig. in mtpa"),
        reply(measure="capacity.total", value_text="400", period="FY30E", printed_axis="All fig. in mtpa"),
        reply(printed_label="Jatadhar Port", value_text="30", stage="approved", group_path="Projects Approved",
              **base),
        reply(printed_label="Keni Port", value_text="30", stage="approved", group_path="Projects Approved", **base),
        reply(printed_label="Box", value_text="85", stage="approved", group_path="Projects Approved", **base),
        reply(printed_label="Murbe Port", value_text="33", stage="under_review",
              group_path="Projects Under Review", **base),
        reply(printed_label="Potential Projects", value_text="45", stage="potential",
              group_path="Pipeline of Potential Projects", **base),
    ]
    rows = build(rows, page_text=page)
    assert len(rows) == 8
    assert [r["group_check"] for r in rows] == ["path_sum"] * 8


def test_path_sum_collapses_a_printed_box_total_and_its_parts():
    page = ("FY25 177 FY28E 292 FY30E 400 mtpa Box 85 A 30 B 4.5 C 7 D 1.8 E 2 F 4 G 36 "
            "Jatadhar 30 Keni 30 Murbe 33 Potential 45")
    rows = [
        reply(measure="capacity.total", value_text="177", period="FY25", printed_axis="All fig. in mtpa"),
        reply(measure="capacity.total", value_text="292", period="FY28E", printed_axis="All fig. in mtpa"),
        reply(measure="capacity.total", value_text="400", period="FY30E", printed_axis="All fig. in mtpa"),
        reply(printed_label="Box", value_text="85", stage="approved", group_path="Projects Approved"),
        reply(printed_label="A", value_text="30", stage="approved", group_path="Projects Approved"),
        reply(printed_label="B", value_text="4.5", stage="approved", group_path="Projects Approved"),
        reply(printed_label="C", value_text="7", stage="approved", group_path="Projects Approved"),
        reply(printed_label="D", value_text="1.8", stage="approved", group_path="Projects Approved"),
        reply(printed_label="E", value_text="2", stage="approved", group_path="Projects Approved"),
        reply(printed_label="F", value_text="4", stage="approved", group_path="Projects Approved"),
        reply(printed_label="G", value_text="36", stage="approved", group_path="Projects Approved"),
        reply(printed_label="Jatadhar", value_text="30", stage="approved", group_path="Projects Approved"),
        reply(printed_label="Keni", value_text="30", stage="approved", group_path="Projects Approved"),
        reply(printed_label="Murbe", value_text="33", stage="under_review", group_path="Projects Under Review"),
        reply(printed_label="Potential", value_text="45", stage="potential",
              group_path="Pipeline of Potential Projects"),
    ]
    # every row needs a printed group source for this test's purpose, but status is not what it checks
    for row in rows:
        if row.get("group_path"):
            row["group_source"] = "printed"
    built = build(rows, page_text=page)
    assert built[3]["group_check"] == "path_sum"          # the box row is in the passing set
    assert sum(1 for r in built if r["group_check"] == "path_sum") >= 5


def test_a_footnote_sentence_is_not_a_label_and_the_row_is_dropped():
    rows = build([reply(printed_label="Further approval of 4 MTPA is under process.", value_text="4")])
    assert rows == []


def test_known_at_is_never_taken_from_the_model():
    rows = build([reply(known_at="1999-01-01T00:00:00")])
    assert rows[0]["known_at"] == KNOWN_AT


def test_parse_reply_handles_jsonl_fences_and_a_single_object():
    fenced = "```json\n" + json.dumps({"value_text": "30"}) + "\n" + json.dumps({"value_text": "31"}) + "\n```"
    rows, bad = obs.parse_reply(fenced)
    assert len(rows) == 2 and bad == 0
    rows, bad = obs.parse_reply(json.dumps({"observations": [{"value_text": "30"}]}))
    assert rows == [{"value_text": "30"}] and bad == 0
    assert obs.parse_reply("I cannot read this page.") == ([], 0)


def test_write_rows_stores_the_checked_row_and_keeps_known_at():
    con = obs.create_db(":memory:")
    rows = build([reply(printed_label="Jatadhar Port, Odisha", printed_axis="FY28E",
                        group_path="Projects Under Review", group_source="printed")])
    assert obs.write_rows(con, rows) == 1
    got = con.execute("SELECT symbol, doc_key, page, known_at, measure, value_text, value, status "
                      "FROM observation").fetchone()
    assert got == ("NAVKARCORP", DECK, 14, KNOWN_AT, "capacity.add", "30", 30.0, "verified")
    obs.write_rows(con, rows)                     # re-running a page replaces its rows
    assert con.execute("SELECT COUNT(*) FROM observation").fetchone()[0] == 1
    con.close()


def test_region_is_empty_when_the_same_number_is_printed_twice():
    words = [(10.0, 20.0, 30.0, 40.0, "30"), (100.0, 200.0, 120.0, 220.0, "30")]
    rows = build([reply(value_text="30")], words=words)
    assert rows[0]["region"] == ""


def test_dim_vocab_canonicalises_a_printed_geography_only():
    rows = build([reply(printed_label="Jatadhar Port, Odisha", geography="Domestic")])
    assert rows[0]["geography"] == "India"
    rows = build([reply(printed_label="Jatadhar Port, Odisha", geography="Somewhere New")])
    assert rows[0]["geography"] == "Somewhere New"       # never guessed away

# --------------------------------------------------------------------------- stage C (T-230)

def _make_store(symbol="NAVKARCORP", name="Navkar Corporation Limited",
                title="As per attached enclosure",
                pages=("JSW Infrastructure Investor Presentation May 2025",), doc_key=DECK,
                first_page=1):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.unlink(missing_ok=True)
    con = sqlite3.connect(STORE)
    con.execute("CREATE TABLE company (symbol TEXT, name TEXT)")
    con.execute("CREATE TABLE doc (doc_key TEXT, title TEXT, symbol TEXT, known_at TEXT)")
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT)")
    con.execute("INSERT INTO company VALUES (?,?)", (symbol, name))
    con.execute("INSERT INTO doc VALUES (?,?,?,?)", (doc_key, title, symbol, KNOWN_AT))
    for number, text in enumerate(pages, first_page):
        con.execute("INSERT INTO doc_page VALUES (?,?,?)", (doc_key, number, text))
    con.commit()
    con.close()


def _cleanup_store():
    STORE.unlink(missing_ok=True)


def test_parent_deck_sets_parent_scope_and_keeps_industry():
    page = "Keni Port, Karnataka 30 FY25 India GDP 7.0 USD Tn"
    rows = build([reply(printed_label="Keni Port, Karnataka", period="FY25"),
                  reply(measure="market.value", printed_label="India GDP", value_text="7.0",
                        unit="USD Tn", printed_axis="GDP", period="FY25", entity_scope="country")],
                 page_text=page, owner="JSWINFRA")
    assert rows[0]["entity_scope"] == "parent"
    assert rows[1]["entity_scope"] == "country"
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]


def test_doc_owner_finds_a_parent_deck_and_keeps_an_ambiguous_one_company():
    index = {"jsw infrastructure": ("JSWINFRA", "JSW Infrastructure Limited"),
             "navkar": ("NAVKARCORP", "Navkar Corporation Limited")}
    try:
        _make_store()
        assert obs.doc_owner(str(STORE), DECK, index, "NAVKARCORP") == "JSW Infrastructure Limited"
        _make_store(pages=("JSW Infrastructure Investor Presentation May 2025",
                           "Navkar Corporation Limited"))
        assert obs.doc_owner(str(STORE), DECK, index, "NAVKARCORP") == ""
    finally:
        _cleanup_store()


def test_empty_unit_inherits_from_the_printed_header():
    page = "Particulars (INR Mn) Total Equity 3.7"
    rows = build([reply(measure="total_equity", unit="", printed_axis="Particulars (INR Mn)",
                        printed_label="Total Equity", period="FY25", value_text="3.7")], page_text=page)
    assert rows[0]["unit"] == "INR mn"
    assert rows[0]["scale"] == 1e6
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]


def test_empty_unit_without_a_printed_unit_is_unverified():
    page = "FY25 Total Equity 3.7"
    rows = build([reply(measure="total_equity", unit="", printed_axis="FY25",
                        printed_label="Total Equity", period="FY25", value_text="3.7")], page_text=page)
    assert rows[0]["status"] == "unverified"
    assert "no_unit" in rows[0]["status_reason"]


def test_empty_period_inherits_from_the_printed_axis():
    page = "FY22 Other income 9.1 (INR Mn)"
    rows = build([reply(measure="other_income", unit="INR Mn", printed_axis="FY22",
                        printed_label="Other income", value_text="9.1")], page_text=page)
    assert rows[0]["period"] == "FY22"
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]


def test_empty_period_without_a_printed_period_is_unverified():
    page = "Particulars (INR Mn) Other income 9.1"
    rows = build([reply(measure="other_income", unit="INR Mn", printed_axis="Particulars (INR Mn)",
                        printed_label="Other income", value_text="9.1")], page_text=page)
    assert rows[0]["status"] == "unverified"
    assert "no_period" in rows[0]["status_reason"]


def test_disbursement_rows_split_from_the_loan_stock():
    page = "Disbursements Mix (₹ Crs) Q2FY24 Agricultural loans 185"
    rows = build([reply(measure="loans", printed_label="Agricultural loans",
                        printed_axis="Disbursements Mix (₹ Crs)", value_text="185", unit="₹ Crs",
                        period="Q2FY24")], page_text=page)
    assert rows[0]["measure"] == "loans.disbursement_mix"
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]


def test_hypothetical_value_never_verifies_as_the_reported_measure():
    page = "EBITDA margin would have been 7.1% Q3FY26"
    rows = build([reply(measure="ebitda_margin", printed_label="EBITDA margin would have been",
                        value_text="7.1%", unit="%", period="Q3FY26")], page_text=page)
    assert rows[0]["adjusted"] == 1
    assert rows[0]["status"] == "unverified"
    assert "adjusted/hypothetical" in rows[0]["status_reason"]


def test_spindle_capacity_is_not_capex():
    page = "CAPACITY BUILTUP 150,000 Greenfield Capex 2027 spindles"
    rows = build([reply(measure="capex.estimated", printed_label="Greenfield Capex", value_text="150,000",
                        unit="", printed_axis="2027", period="2027")], page_text=page)
    assert rows[0]["measure"] == "capacity.spindles"
    assert rows[0]["status"] == "unverified"          # no unit printed for the collection


def test_measure_alias_maps_a_near_duplicate_id():
    page = "Order book growth 22% FY25"
    rows = build([reply(measure="order_book_growth_yoy", printed_label="Order book growth",
                        value_text="22%", unit="%", period="FY25")], page_text=page)
    assert rows[0]["measure"] == "order.book_growth_yoy"
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]


def test_axis_prompt_asks_for_one_printed_line():
    assert "ONE printed line" in obs.PROMPT
    assert "Never join" in obs.PROMPT


def test_recheck_inherits_a_printed_unit_and_period_and_keeps_the_row_id():
    page = "Particulars (INR Mn) FY25 Total Equity 3.7"
    try:
        _make_store(pages=(page,), first_page=14)
        con = obs.create_db(":memory:")
        rows = build([reply(measure="total_equity", unit="", printed_axis="Particulars (INR Mn)",
                            printed_label="Total Equity", value_text="3.7", period="",
                            series_title="FY25")], page_text=page)
        # simulate the stage B row: no unit, no period, unverified (C2 had not inherited yet)
        rows[0].update({"unit": "", "unit_family": "", "period": "", "period_kind": "",
                        "status": "unverified", "status_reason": "no_unit; no_period"})
        obs.write_rows(con, rows)
        row_id = con.execute("SELECT observation_id FROM observation").fetchone()[0]
        stats = obs.recheck_db(con, [str(STORE)])
        cursor = con.execute("SELECT * FROM observation WHERE observation_id=?", (row_id,))
        record = dict(zip([d[0] for d in cursor.description], cursor.fetchone()))
        assert record["unit"] == "INR mn" and record["period"] == "FY25"
        assert record["status"] == "verified", record["status_reason"]
        assert stats["unit_inherited"] == 1 and stats["period_inherited"] == 1
        con.close()
    finally:
        _cleanup_store()


def test_recheck_refuses_an_upgrade_without_a_new_printed_source():
    page = "Particulars (INR Mn) FY25 Total Equity 3.7"
    try:
        _make_store(pages=(page,), first_page=14)
        con = obs.create_db(":memory:")
        rows = build([reply(measure="total_equity", unit="INR Mn", printed_axis="Particulars (INR Mn)",
                            printed_label="Total Equity", value_text="3.7", period="FY25")], page_text=page)
        rows[0]["status"] = "unverified"
        rows[0]["status_reason"] = "stale manual reason"
        obs.write_rows(con, rows)
        stats = obs.recheck_db(con, [str(STORE)])
        status = con.execute("SELECT status FROM observation").fetchone()[0]
        assert status == "unverified"
        assert stats["unproven_upgrades"] == 1
        assert "stopped" in stats
        con.close()
    finally:
        _cleanup_store()

# --------------------------------------------------------------------------- stage D (T-230)

def test_money_scale_words_are_read():
    assert obs.money_scale(["₹ in M"]) == 1e6
    assert obs.money_scale(["Rs Mn"]) == 1e6
    assert obs.money_scale(["Mio"]) is None            # no money context
    assert obs.money_scale(["USD Mio"]) == 1e6
    assert obs.money_scale(["Crore"]) is None
    assert obs.money_scale(["Rs Crore"]) == 1e7
    assert obs.money_scale(["in Lakh"]) == 1e5
    assert obs.money_scale(["USD Bn"]) == 1e9
    assert obs.money_scale(["Rs '000"]) == 1e3


def test_a_money_row_with_a_named_scale_is_fixed_and_verifies():
    page = "Interest expense (20.0) Q2 2024 ₹ in M"
    rows = build([reply(measure="finance_cost", printed_label="Interest expense", value_text="(20.0)",
                        unit="₹ in M", printed_axis="₹ in M", period="Q2 2024")], page_text=page)
    assert rows[0]["scale"] == 1e6
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]


def test_a_money_row_with_a_named_scale_but_scale_one_is_unverified():
    row = {"measure": "finance_cost", "printed_label": "Interest expense", "printed_axis": "₹ in M",
           "series_title": "", "unit": "₹ in M", "unit_family": "money", "scale": 1.0, "period": "Q2 2024",
           "period_kind": "actual", "value_text": "(20.0)", "value": -20.0, "entity_scope": "company",
           "printed_axis_verbatim": True}
    status, reasons = obs.evaluate_status(row, "Interest expense (20.0) Q2 2024 ₹ in M",
                                          obs.measure_index(), "Interest expense (20.0) Q2 2024 ₹ in M")
    assert status == "unverified"
    assert "scale_unread" in "; ".join(reasons)


def test_basis_columns_resolve_a_two_column_conflict():
    page = "Other current assets 660.65 678.70 FY 26-27 Q2"
    words = [(100.0, 100.0, 200.0, 110.0, "STANDALONE"), (400.0, 100.0, 520.0, 110.0, "CONSOLIDATED"),
             (150.0, 200.0, 190.0, 210.0, "660.65"), (450.0, 200.0, 490.0, 210.0, "678.70")]
    rows = build([reply(measure="other_current_assets", printed_label="Other current assets",
                        value_text="660.65", unit="Crores", period="FY 26-27 Q2"),
                  reply(measure="other_current_assets", printed_label="Other current assets",
                        value_text="678.70", unit="Crores", period="FY 26-27 Q2")],
                 page_text=page, words=words)
    assert [r["basis"] for r in rows] == ["standalone", "consolidated"]
    assert all(r["status"] == "verified" for r in rows), [r["status_reason"] for r in rows]


def test_two_values_without_distinct_bases_are_both_unverified():
    page = "Other current assets 660.65 678.70 FY 26-27 Q2"
    rows = build([reply(measure="other_current_assets", printed_label="Other current assets",
                        value_text="660.65", unit="Crores", period="FY 26-27 Q2"),
                  reply(measure="other_current_assets", printed_label="Other current assets",
                        value_text="678.70", unit="Crores", period="FY 26-27 Q2")],
                 page_text=page)
    assert all(r["status"] == "unverified" for r in rows)
    assert all("basis_conflict" in r["status_reason"] for r in rows)


def test_bridge_steps_are_deltas_not_levels():
    page = ("Core Profitability Q2 FY25 Reported EBITDA 14.1% Speciality Chemicals 2.2% "
            "Pet Care -0.7% Rigid Packaging -0.5% Packaging 13.1%")
    rows = build([
        reply(measure="ebitda_margin", printed_label="Reported EBITDA", value_text="14.1%", unit="%",
              period="Q2 FY25"),
        reply(measure="ebitda_margin", printed_label="Speciality Chemicals", value_text="2.2%", unit="%",
              period="Q2 FY25"),
        reply(measure="ebitda_margin", printed_label="Pet Care", value_text="-0.7%", unit="%",
              period="Q2 FY25"),
        reply(measure="ebitda_margin", printed_label="Packaging", value_text="13.1%", unit="%",
              period="Q2 FY25"),
    ], page_text=page)
    assert rows[0]["series_kind"] == "bridge"
    assert rows[0]["measure"] == "ebitda_margin"
    assert rows[1]["measure"] == "ebitda_margin.delta"
    assert rows[1]["status"] == "unverified"
    assert "bridge step" in rows[1]["status_reason"]


def test_a_subsidiary_page_is_scoped_as_subsidiary():
    page = "AGPL's Standalone Profit & Loss Profit before exceptional items and tax 4.39 H1FY26"
    rows = build([reply(measure="profit_before_tax", printed_label="Profit before exceptional items and tax",
                        value_text="4.39", unit="Rs Cr", printed_axis="H1FY26 Unaudited", period="H1FY26",
                        series_title="AGPL's Standalone Profit & Loss")], page_text=page)
    assert rows[0]["entity_scope"] == "subsidiary"


def test_stock_row_takes_the_deck_period_and_flow_stays_no_period():
    page = "Gross Advances Mortgage (Total) GNPA 66.9 ₹Cr"
    stock = build([reply(measure="gnpa", printed_label="Mortgage (Total) GNPA", value_text="66.9",
                         unit="₹Cr")], page_text=page)
    # build() has no deck_asof parameter: call directly
    stock = obs.build_observations(symbol="SURYODAY", doc_key=DECK, page=25, known_at=KNOWN_AT,
                                   page_text=page, reply_rows=[reply(
                                       measure="gnpa", printed_label="Mortgage (Total) GNPA",
                                       value_text="66.9", unit="₹Cr")], deck_asof="March 31, 2026")
    assert stock[0]["period"] == "March 31, 2026"
    assert stock[0]["period_source"] == "deck_period"
    flow = obs.build_observations(symbol="SURYODAY", doc_key=DECK, page=25, known_at=KNOWN_AT,
                                  page_text=page, reply_rows=[reply(
                                      measure="revenue.value", printed_label="Mortgage (Total) GNPA",
                                      value_text="66.9", unit="₹Cr")], deck_asof="March 31, 2026")
    assert flow[0]["period"] == ""
    assert "no_period" in flow[0]["status_reason"]


def test_director_experience_is_quarantined():
    page = "S M Sundaram Non Executive Independent Director over 37 years of professional experience"
    rows = build([reply(measure="count.years_professional_experience",
                        printed_label="over 37 years of professional experience", value_text="37",
                        unit="years", period="FY25")], page_text=page)
    assert rows[0]["status"] == "quarantined"
    assert "not_a_measure" in rows[0]["status_reason"]


def test_an_axis_tick_value_is_unverified():
    page = "Global Capacity (KTPA) 1,000 3,000 5,000 6,000 9,000"
    rows = build([reply(measure="capacity.total", printed_label="Global Capacity (KTPA)",
                        series_title="Global Capacity (KTPA)", value_text="6,000", unit="KTPA",
                        period="2024")], page_text=page)
    assert rows[0]["status"] == "unverified"
    assert "axis_tick" in rows[0]["status_reason"]

# --------------------------------------------------------------------------- stage E (T-230)

def _deck_build(rows, page_text, deck_asof):
    return obs.build_observations(symbol="NAVKARCORP", doc_key=DECK, page=14, known_at=KNOWN_AT,
                                  page_text=page_text, reply_rows=rows, deck_asof=deck_asof)


def test_capacity_deck_period_is_gated_by_stage_and_page_words():
    page = "Advait is establishing a greenfield facility for electrolysers 300 MW"
    rows = _deck_build([reply(measure="capacity.total", printed_label="capacity for indigenous electrolysers",
                              value_text="300", unit="MW", printed_axis="September 30, 2025",
                              period="September 30, 2025")], page, "September 30, 2025")
    row = {"measure": "capacity.total", "printed_label": "capacity for indigenous electrolysers",
           "series_title": "", "group_path": "", "stage": ""}
    assert obs.capacity_deck_period_ok(row, page) is False
    assert rows[0]["period"] == "September 30, 2025"      # printed on the row, not the deck

    page2 = "Installed Capacity has been created for 160,000 MT. Can be further enhanced by 50,000 MT"
    row2 = {"measure": "capacity.add", "printed_label": "Can be further enhanced by", "series_title": "",
            "group_path": "", "stage": ""}
    assert obs.capacity_deck_period_ok(row2, page2) is False
    row3 = {"measure": "capacity.add", "printed_label": "Solar 3.8 MWDC", "series_title": "",
            "group_path": "", "stage": ""}
    page3 = "Solar 3.8 MWDC addition commissioned Q4FY25"
    assert obs.capacity_deck_period_ok(row3, page3) is True


def test_capacity_without_a_printed_stock_word_gets_no_deck_period():
    page = "Water EPC Qualification Moat 400+ MLD WTPs built for clients"
    row = {"measure": "capacity.total", "printed_label": "MLD WTPs", "series_title": "SPML 2.0",
           "group_path": "Water EPC Qualification Moat", "stage": ""}
    assert obs.capacity_deck_period_ok(row, page) is False


def test_deck_period_ignores_the_filing_letter_date():
    letter = "To, BSE Limited, Dalal Street. Date: 15.06.2026. Dear Sir, Sub: Investor Presentation."
    cover = "FY26 Investor Presentation"
    try:
        _make_store(pages=(letter, cover), first_page=1)
        assert obs.deck_period(str(STORE), DECK, "some page") == "FY26"
    finally:
        _cleanup_store()


def test_basis_from_a_group_heading_line():
    page = "Consolidated (in INR Cr.) Revenue from Operations 1,263.97 FY23"
    rows = build([reply(measure="revenue_from_operations", printed_label="Revenue from Operations",
                        value_text="1,263.97", unit="INR Cr.", printed_axis="FY23", period="FY23",
                        group_path="Consolidated (in INR Cr.)", group_source="printed")], page_text=page)
    assert rows[0]["basis"] == "consolidated"
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]


def test_basis_from_a_footer_line():
    page = "Deferred tax 5.21 Dec 31 2024\nStandalone- (Figures in Crores)"
    rows = build([reply(measure="deferred_tax", printed_label="Deferred tax", value_text="5.21",
                        unit="Cr", printed_axis="Dec 31 2024", period="Dec 31 2024")], page_text=page)
    assert rows[0]["basis"] == "standalone"


def test_a_two_point_growth_becomes_a_cagr_span():
    page = "195 273 FY21 FY24 +12% Total Income* Rs. In Crores"
    rows = build([reply(measure="revenue_growth_yoy", printed_label="", series_title="Total Income*",
                        value_text="+12%", unit="%", period="FY24")], page_text=page)
    assert rows[0]["measure"] == "revenue_growth_cagr"
    assert rows[0]["period"] == "FY21-FY24"
    assert rows[0]["period_kind"] == "span"


def test_bare_mt_is_ambiguous_until_the_page_resolves_it():
    page = "Cargo handled 1.8 MT Q4 FY25"
    rows = build([reply(measure="volume.sales", printed_label="Cargo handled", value_text="1.8", unit="MT",
                        period="Q4 FY25")], page_text=page)
    assert rows[0]["status"] == "unverified"
    assert "scale_ambiguous" in rows[0]["status_reason"]
    page_mtpa = "Cargo handled 1.8 MT Q4 FY25 at 12 MTPA capacity"
    rows = build([reply(measure="volume.sales", printed_label="Cargo handled", value_text="1.8", unit="MT",
                        period="Q4 FY25")], page_text=page_mtpa)
    assert rows[0]["scale"] == 1e6
    assert "scale_ambiguous" not in rows[0]["status_reason"]

# --------------------------------------------------------------------------- stage F (T-230 annual-report pages)

STATEMENT_PAGES = {
    "balance_sheet": "BALANCE SHEET AS AT 31ST MARCH, 2026\nEquity and liabilities\n1,000",
    "profit_and_loss": "STATEMENT OF PROFIT AND LOSS for the year ended March 31, 2026\nRevenue\n1,000",
    "cash_flow": "CASH FLOW STATEMENT FOR THE YEAR ENDED MARCH 31, 2026\nOperating activities\n500",
    "changes_in_equity": "STATEMENT OF CHANGES IN EQUITY FOR THE YEAR ENDED MARCH 31, 2026\nBalance\n500",
    "notes": "NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS FOR THE YEAR ENDED MARCH 31, 2026\nTrade payables 5",
    "note_no": "Note No. 3: Property, Plant and Equipment\nGross block 1,000",
    "audit_report": "INDEPENDENT AUDITOR'S REPORT\nTo the Members of the Company\nOpinion",
    "aoc1": "FORM AOC-1\nStatement containing salient features of the financial statements",
    "mgt9": "MGT-9\nEXTRACT OF THE ANNUAL RETURN AS ON THE FINANCIAL YEAR ENDED 31ST MARCH, 2026",
    "remuneration": "PARTICULARS OF EMPLOYEES FOR THE FINANCIAL YEAR ENDED 31ST MARCH, 2025\nSalary 50",
    "csr_spend": "CSR amount spent or unspent for the financial year:\nTotal Amount Spent 22,336",
    "shareholding": "Shareholding Pattern as at 31st March, 2026\nPromoter 55.1",
    "share_price": "Share Price Data\nMonth High Low Close",
    "notice": "NOTICE TO THE SHAREHOLDERS\nAnnual General Meeting",
    "secretarial_audit": "SECRETARIAL AUDIT REPORT FOR THE FINANCIAL YEAR ENDED 31ST MARCH, 2026",
    "governance": "REPORT ON CORPORATE GOVERNANCE\nBoard of Directors",
    "related_party": "RELATED PARTY TRANSACTIONS\nName of the related party 2026 2025",
    "brsr": "BUSINESS RESPONSIBILITY AND SUSTAINABILITY REPORT\nSECTION A: GENERAL DISCLOSURES",
}


def test_each_statement_heading_drops_its_page():
    for reason, page in STATEMENT_PAGES.items():
        assert obs.statement_page_reason(page) == reason


def test_an_mda_page_and_a_sentence_mentioning_a_statement_are_kept():
    assert obs.statement_page_reason(
        "Management Discussion and Analysis\nInstalled capacity rose from 12,000 TPA to 40,000 TPA.") == ""
    assert obs.statement_page_reason(
        "The balance sheet remains strong and our net debt is low. Revenue grew 15%.") == ""
    assert obs.statement_page_reason("balance sheet date. We, however, state that this is not an adjustment") == ""
    assert obs.statement_page_reason("Note No. 18 of the Standalone Financial Statements for the year") == ""
    assert obs.statement_page_reason("") == ""


def test_a_segment_note_and_a_plant_brsr_page_are_kept():
    segment = ("NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS\n38. SEGMENT REPORTING UNDER IND AS 108\n"
               "The following are the information relating to geographical segment:\nIndia Others Total\n93,384.25")
    assert obs.statement_page_reason(segment) == ""
    brsr = ("BUSINESS RESPONSIBILITY AND SUSTAINABILITY REPORT\n"
            "Number of locations where plants and/or operations/offices of the entity are situated: 12")
    assert obs.statement_page_reason(brsr) == ""


def test_filter_statement_pages_keeps_the_operating_pages_and_counts_the_reasons():
    pages = [{"doc_key": "d", "page": 1}, {"doc_key": "d", "page": 2}, {"doc_key": "d", "page": 3},
             {"doc_key": "d", "page": 4}]
    texts = {("d", 1): "BALANCE SHEET AS AT 31ST MARCH, 2026",
             ("d", 2): "Business Overview\nNumber of plants 12 in India and 0 outside",
             ("d", 3): "NOTES TO FINANCIAL STATEMENTS FOR THE YEAR ENDED 31ST MARCH, 2024",
             ("d", 5): "never printed"}                       # page 4 has no stored text: kept
    dropped = {}
    kept = obs.filter_statement_pages(pages, texts, dropped)
    assert [p["page"] for p in kept] == [2, 4]
    assert dropped == {"balance_sheet": 1, "notes": 1}


STORE_F = Path(".tmp/t230/test_f_store.db")


def _make_ar_store(pages):
    STORE_F.parent.mkdir(parents=True, exist_ok=True)
    STORE_F.unlink(missing_ok=True)
    con = sqlite3.connect(STORE_F)
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT)")
    for number, text in enumerate(pages, 1):
        con.execute("INSERT INTO doc_page VALUES (?,?,?)", ("ar.pdf", number, text))
    con.commit()
    con.close()
    with (STORE_F.parent / "routes.csv").open("w", newline="", encoding="utf-8") as fh:
        fh.write("doc_key,page,route,doc_type\n")
        for number in range(1, len(pages) + 1):
            fh.write(f"ar.pdf,{number},table_or_chart,annual_report\n")


def test_pages_from_store_skips_statement_pages_only_with_the_flag():
    _make_ar_store(["BALANCE SHEET AS AT 31ST MARCH, 2026",
                    "Management Discussion and Analysis\nCapacity rose to 30 mtpa"])
    try:
        assert len(obs.pages_from_store(STORE_F, doc_types=("annual_report",))) == 2
        dropped = {}
        kept = obs.pages_from_store(STORE_F, doc_types=("annual_report",), skip_statements=True, dropped=dropped)
        assert [p["page"] for p in kept] == [2]
        assert dropped == {"balance_sheet": 1}
    finally:
        STORE_F.unlink(missing_ok=True)
        (STORE_F.parent / "routes.csv").unlink(missing_ok=True)


SEED_ROOT = Path(".tmp/t230/seed_root")


def _make_route_store(name, doc_type):
    store = SEED_ROOT / name
    store.mkdir(parents=True, exist_ok=True)
    (store / f"{name}.db").write_bytes(b"")
    with (store / "routes.csv").open("w", newline="", encoding="utf-8") as fh:
        fh.write("doc_key,page,route,doc_type\n")
        fh.write(f"{name}.pdf,1,table_or_chart,{doc_type}\n")


def test_seed_stores_follows_the_doc_type():
    _make_route_store("a", "deck")
    _make_route_store("b", "annual_report")
    try:
        picked = obs.seed_stores(SEED_ROOT, 5, 11, doc_types=("annual_report",))
        assert [Path(p).parent.name for p in picked] == ["b"]
    finally:
        shutil.rmtree(SEED_ROOT, ignore_errors=True)
