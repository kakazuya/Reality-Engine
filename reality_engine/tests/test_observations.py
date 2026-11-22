"""T-230 stage A-F: observation schema, independent checks and the writer (synthetic, no network)."""
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

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
            "value", "value_text", "unit", "scale", "adjusted", "value_kind", "is_total", "period", "period_kind",
            "segment", "product", "geography", "plant", "customer", "group_path", "group_source", "group_check",
            "stage", "series_id", "entity_scope", "status", "status_reason"} <= cols
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


def test_value_printed_only_in_the_page_image_is_unverified_never_quarantined():
    rows = build([reply(value_text="99")])
    assert rows[0]["status"] == "unverified"
    assert "image_text" in rows[0]["status_reason"]


def test_ocr_text_of_the_page_image_verifies_a_value_the_layer_lacks():
    page = "Dealer network (an image, its numbers are not in this text layer)"
    rows = obs.build_observations(symbol="NAVKARCORP", doc_key=DECK, page=14, known_at=KNOWN_AT,
                                  page_text=page,
                                  reply_rows=[reply(value_text="37", period="FY25", series_title="Dealer network")],
                                  ocr_text="Industrial Supply Dealers 37 FY25")
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]
    assert rows[0]["text_source"] == "ocr"


# --------------------------------------------------------------------------- T-238: an OCR-routed page
OCR_STORE = Path(".tmp/t230/test_c_ocr_store.db")
OCR_DECK = "D:/RealityEngine/raw/pilot60_history/SOMANYCERA/investor_presentation/deck.pdf"
OCR_PAGE = ["Particulars INR Cr FY25 FY24 FY23",
            "Revenue from operations 1,268 1,150 1,020",
            "EBITDA 178 165 140", "Profit after tax 90 84 70"]
JUMBLED_LAYER = "XKCDQW RTYPSD MNBVCZ WQRTPS KLMNZ BDFGH 999 888"


def _ocr_words(lines):
    words, y = [], 72.0
    for line in lines:
        x = 72.0
        for token in line.split():
            words.append([round(x, 2), y, round(x + 6.0 * len(token), 2), y + 10.0, token, 0.95])
            x += 6.0 * len(token) + 4.0
        y += 16.0
    return words


def _make_ocr_store():
    """A store whose page text layer is jumbled, with the page's OCR words in the sibling ``_ocr.db``."""
    OCR_STORE.parent.mkdir(parents=True, exist_ok=True)
    for path in (OCR_STORE, OCR_STORE.with_name(OCR_STORE.stem + "_ocr.db")):
        path.unlink(missing_ok=True)
    con = sqlite3.connect(OCR_STORE)
    con.execute("CREATE TABLE company (symbol TEXT, name TEXT)")
    con.execute("CREATE TABLE doc (doc_key TEXT, title TEXT, symbol TEXT, doc_type TEXT, known_at TEXT, "
                "pages INTEGER, source_key TEXT)")
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT, method TEXT, "
                "PRIMARY KEY (doc_key, page))")
    con.execute("INSERT INTO company VALUES ('SOMANYCERA','Somany Ceramics Limited')")
    con.execute("INSERT INTO doc VALUES (?,?,?,?,?,?,?)",
                (OCR_DECK, "Somany Investor Presentation", "SOMANYCERA", "deck", KNOWN_AT, 1, "missing/deck.pdf"))
    con.execute("INSERT INTO doc_page VALUES (?,?,?,?)", (OCR_DECK, 1, JUMBLED_LAYER, "needs_ocr"))
    con.commit()
    con.close()
    words = _ocr_words(OCR_PAGE)
    ocon = sqlite3.connect(OCR_STORE.with_name(OCR_STORE.stem + "_ocr.db"))
    ocon.execute("CREATE TABLE ocr_page (symbol TEXT, doc_key TEXT, page INTEGER, doc_type TEXT, known_at TEXT, "
                 "text TEXT, words_json TEXT, ocr_conf REAL, n_boxes INTEGER, dpi INTEGER, seconds REAL, "
                 "method TEXT, PRIMARY KEY (symbol, doc_key, page))")
    ocon.execute("INSERT INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("SOMANYCERA", OCR_DECK, 1, "deck", KNOWN_AT, " ".join(OCR_PAGE), json.dumps(words), 0.95,
                  len(words), 300, 1.0, "ocr_rapid"))
    ocon.commit()
    ocon.close()


def test_an_ocr_routed_page_reads_and_checks_the_ocr_words(monkeypatch):
    """T-238: the reader gets the OCR text layer (not the jumbled one) and the row carries text_source='ocr'."""
    try:
        _make_ocr_store()
        seen = {}

        def fake_reader(prompt, image_b64, doc_key="", page=0):
            seen["prompt"] = prompt
            return {"output": json.dumps({
                "series_id": "s1", "series_title": "", "measure": "revenue_from_operations",
                "printed_label": "Revenue from operations", "printed_axis": "Particulars INR Cr FY25",
                "value_text": "1,268", "unit": "INR Cr", "scale": 1e7, "period": "FY25",
                "period_kind": "actual", "segment": "", "product": "", "geography": "", "plant": "",
                "customer": "", "group_path": "", "group_source": "", "stage": "",
                "entity_scope": "company", "is_total": False}), "error": None, "seconds": 1.0,
                "in_tok": 1, "out_tok": 1}

        monkeypatch.setattr(obs, "call_reader", fake_reader)
        monkeypatch.setattr(obs.page_reader, "_page_image", lambda *args, **kwargs: (b"image", 1.0))
        result = obs.process_page(str(OCR_STORE), OCR_DECK, 1)
        assert result["ocr_read"] is True
        assert "Revenue from operations 1,268" in seen["prompt"]      # the OCR text layer
        assert "XKCDQW" not in seen["prompt"]                          # never the jumbled layer
        assert len(result["rows"]) == 1
        row = result["rows"][0]
        assert row["text_source"] == "ocr"
        assert row["status"] == "verified", row["status_reason"]
    finally:
        for path in (OCR_STORE, OCR_STORE.with_name(OCR_STORE.stem + "_ocr.db")):
            path.unlink(missing_ok=True)


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


def test_measure_must_be_in_the_dictionary_or_declared_new():
    rows = build([reply(measure="made.up")])
    assert rows[0]["status"] == "unverified"
    assert "undeclared_new" in rows[0]["status_reason"]


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


def test_recheck_restores_a_parts_sum_proof_from_the_stored_total():
    page = "Revenue FY25 Total 100 North 60 South 40"
    try:
        _make_store(pages=(page,), first_page=14)
        con = obs.create_db(":memory:")
        rows = build([
            reply(measure="revenue.value", value_text="100", printed_label="Total", printed_axis="FY25",
                  period="FY25", unit="Rs Cr", is_total=True),
            reply(measure="revenue.value", value_text="60", printed_label="North", printed_axis="FY25",
                  period="FY25", unit="Rs Cr"),
            reply(measure="revenue.value", value_text="40", printed_label="South", printed_axis="FY25",
                  period="FY25", unit="Rs Cr"),
        ], page_text=page)
        assert all(row["status"] == "verified" for row in rows), [r["status_reason"] for r in rows]
        # simulate a DB written before is_total was a column: the total flag is gone and every row lost its proof
        for row in rows:
            row.update({"is_total": 0, "entity_scope": "", "status": "unverified",
                        "status_reason": "entity_scope not stated"})
        obs.write_rows(con, rows)
        stats = obs.recheck_db(con, [str(STORE)])
        statuses = [r[0] for r in con.execute("SELECT status FROM observation ORDER BY observation_id")]
        totals = [r[0] for r in con.execute("SELECT is_total FROM observation ORDER BY observation_id")]
        assert statuses == ["verified", "verified", "verified"], statuses
        assert totals == [1, 0, 0]
        assert stats["parts_sum_restored"] == 3
        con.close()
    finally:
        _cleanup_store()


def test_recheck_never_turns_a_stored_total_on_without_a_printed_label():
    assert obs.derive_is_total({"printed_label": "Total Revenue"})
    assert obs.derive_is_total({"printed_label": "Overall"})
    assert obs.derive_is_total({"printed_label": "Consolidated total"})
    assert obs.derive_is_total({"printed_label": "North", "is_total": 1})
    assert not obs.derive_is_total({"printed_label": "North"})


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
    page = "Global Capacity (KTPA) 1,000 2,000 3,000 4,000 5,000 6,000"
    rows = build([reply(measure="capacity.total", printed_label="Global Capacity (KTPA)",
                        series_title="Global Capacity (KTPA)", value_text="6,000", unit="KTPA",
                        period="2024")], page_text=page)
    assert rows[0]["status"] == "unverified"
    assert "axis_tick" in rows[0]["status_reason"]


def test_a_data_label_off_the_tick_ladder_is_not_a_tick():
    page = "Axis 0 1,000 2,000 3,000 4,000\nGlobal Capacity (KTPA) 4,500"
    rows = build([reply(measure="capacity.total", printed_label="Global Capacity (KTPA)",
                        series_title="Global Capacity (KTPA)", value_text="4,500", unit="KTPA",
                        period="2024")], page_text=page)
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]
    assert "axis_tick" not in rows[0]["status_reason"]


def test_a_ladder_extracted_one_tick_per_line_still_cannot_verify():
    page = ("Expected Capacity\n0\n1,000\n2,000\n3,000\n4,000\n5,000\n6,000\n7,000\n8,000\n9,000\n2019\n2020\n")
    rows = build([reply(measure="capacity.total", printed_label="Global Capacity (KTPA)",
                        series_title="Expected Capacity", value_text="7,000", unit="KTPA", period="2023")],
                 page_text=page)
    assert rows[0]["status"] == "unverified"
    assert "axis_tick" in rows[0]["status_reason"]


def test_a_four_value_run_is_not_an_axis_ladder():
    assert not obs._tick_ladder([0.20, 0.21, 0.22, 0.23])
    assert obs._tick_ladder([0.10, 0.30, 0.50, 0.70, 0.90, 1.10])
    page = "VA Stability\n0.20\n0.21\n0.22\n0.23\nChina VA\n"
    rows = build([reply(measure="value_addition_per_kg", value_text="0.23", unit="$/Kg",
                        printed_label="China VA", series_title="VA Stability", period="Q1 16-17",
                        entity_scope="industry")], page_text=page)
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]
    assert "axis_tick" not in rows[0]["status_reason"]

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


def test_pages_from_store_reads_a_needs_ocr_page_only_when_its_ocr_words_exist():
    """T-238: a `needs_ocr` row is readable once the store's own `<stem>_ocr.db` holds the page."""
    _make_ar_store(["Revenue 100", "Profit 50"])
    with (STORE_F.parent / "routes.csv").open("w", newline="", encoding="utf-8") as fh:
        fh.write("doc_key,page,route,doc_type\n")
        fh.write("ar.pdf,1,needs_ocr,annual_report\n")
        fh.write("ar.pdf,2,needs_ocr,annual_report\n")
    ocr = obs.page_words.sibling_ocr_db(STORE_F)
    try:
        assert obs.pages_from_store(STORE_F, doc_types=("annual_report",)) == []      # no OCR words yet
        con = sqlite3.connect(ocr)
        con.execute("CREATE TABLE ocr_page (doc_key TEXT, page INTEGER, words_json TEXT, method TEXT)")
        con.execute("INSERT INTO ocr_page VALUES (?,?,?,?)", ("ar.pdf", 1, "[]", "ocr_rapid"))
        con.commit()
        con.close()
        obs._ocr_pages.cache_clear()          # the store's OCR db arrived after the first look
        pages = obs.pages_from_store(STORE_F, doc_types=("annual_report",))
        assert [p["page"] for p in pages] == [1]
    finally:
        for path in (STORE_F, ocr, STORE_F.parent / "routes.csv"):
            path.unlink(missing_ok=True)
        obs._ocr_pages.cache_clear()


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


# --------------------------------------------------------------------------- stage H (T-230): picture reading

def test_a_waterfall_keeps_its_opening_and_closing_bars_as_levels():
    page = ("Normalized EBITDA Bridge Q4 23-24 to Q1 24-25 USD million Normalised EBITDA - Q4 23-24 16.4 "
            "Volume VA variance ( 1.5 ) Rate VA variance 1.6 Other Film & Chips Contribution 4.2 "
            "Other Variable Cost ( 0.1 ) Fixed Cost 4.0 Other Income ( 0.1 ) Normalised EBITDA - Q1 24-25 24.5")
    rows = build([
        reply(measure="ebitda", printed_label="Normalised EBITDA - Q4 23-24", value_text="16.4",
              unit="USD million", period="Q4 23-24", series_title="Normalized EBITDA Bridge"),
        reply(measure="ebitda", printed_label="Volume VA variance", value_text="( 1.5 )", unit="USD million",
              period="Q1 24-25", series_title="Normalized EBITDA Bridge"),
        reply(measure="ebitda", printed_label="Fixed Cost", value_text="4.0", unit="USD million",
              period="Q1 24-25", series_title="Normalized EBITDA Bridge"),
        reply(measure="ebitda.delta", printed_label="Normalised EBITDA - Q1 24-25", value_text="24.5",
              unit="USD million", period="Q1 24-25", series_title="Normalized EBITDA Bridge"),
    ], page_text=page)
    assert rows[0]["series_kind"] == "bridge"
    assert rows[0]["measure"] == "ebitda"            # the opening level stays a level
    assert rows[1]["measure"] == "ebitda.delta"      # the middle step is a delta
    assert "bridge step" in rows[1]["status_reason"]
    assert rows[3]["measure"] == "ebitda"            # the closing level is a level, not a step


def test_a_bridge_on_the_page_does_not_turn_another_series_into_a_bridge():
    page = ("Adj. EBITDA Bridge (Rs. in M) CY 23 Adj. EBITDA 2,452 Improved Utilisation 444 CY 24 Adj. EBITDA 2,910 "
            "Financials Trend Revenue 4,163 4,166 4,320")
    rows = build([
        reply(measure="revenue.value", printed_label="Revenue", value_text="4,163", unit="Rs. M",
              period="Q4 23", series_id="s1", series_title="Financials Trend"),
        reply(measure="revenue.value", printed_label="Revenue", value_text="4,166", unit="Rs. M",
              period="Q1 24", series_id="s1", series_title="Financials Trend"),
        reply(measure="revenue.value", printed_label="Revenue", value_text="4,320", unit="Rs. M",
              period="Q2 24", series_id="s1", series_title="Financials Trend"),
    ], page_text=page)
    assert all(r["series_kind"] == "level" for r in rows)
    assert all(r["measure"] == "revenue.value" for r in rows)


def test_a_series_that_is_no_longer_a_bridge_gives_its_steps_back_to_levels():
    rows = [{"measure": "ebitda.delta", "series_kind": "bridge", "series_id": "s2", "series_title": "Adj. EBITDA",
             "value_text": "Rs. 2,611 mn", "printed_label": "the EBITDA for Year 2024", "value": 2611.0,
             "status": "unverified", "status_reason": "", "group_path": ""},
            {"measure": "ebitda", "series_kind": "bridge", "series_id": "s2", "series_title": "Adj. EBITDA",
             "value_text": "₹2,910M", "printed_label": "Adj. EBITDA", "value": 2910.0,
             "status": "verified", "status_reason": "", "group_path": ""},
            {"measure": "ebitda", "series_kind": "bridge", "series_id": "s2", "series_title": "Adj. EBITDA",
             "value_text": "₹ 2,451mn", "printed_label": "EBITDA of", "value": 2451.0,
             "status": "unverified", "status_reason": "", "group_path": ""}]
    obs.apply_series_kind(rows, "no bridge word on the page")
    assert rows[0]["measure"] == "ebitda" and rows[0]["series_kind"] == "level"


def test_a_stacked_segment_is_a_part_with_its_own_label_never_the_total():
    page = ("Capacity Expansion Ready for Future Growth Existing Addition Total 2012 12,000 5,500 17,500")
    rows = build([
        reply(measure="capacity.total", value_text="12,000", segment="Existing", period="2012"),
        reply(measure="capacity.add", value_text="5,500", segment="Addition", period="2012"),
        reply(measure="capacity.total", value_text="17,500", printed_label="Total", period="2012", is_total=True),
    ], page_text=page)
    existing = [r for r in rows if r["value_text"] == "12,000"][0]
    total = [r for r in rows if r["value_text"] == "17,500"][0]
    assert existing["printed_label"] == "Existing"          # the segment's printed name, not an empty total label
    assert "stacked_part" in existing["status_reason"]
    assert total["printed_label"] == "Total"


def test_a_rank_is_a_count_not_a_share():
    page = ("Low customer concentration risk with top 10 film customers accounting for 26% of total FY26 turnover")
    rows = build([
        reply(measure="mix.share", printed_label="top 10 film customers", value_text="10", unit="%", period="FY26"),
        reply(measure="mix.share", printed_label="top 10 film customers", value_text="26%", unit="%", period="FY26",
              series_id="s2"),
    ], page_text=page)
    rank = [r for r in rows if r["value_text"] == "10"][0]
    share = [r for r in rows if r["value_text"] == "26%"][0]
    assert rank["measure"] == "count.customers"
    assert "rank_count" in rank["status_reason"]
    assert share["measure"] == "mix.share"


MAP_WORDS = [
    (10.0, 10.0, 40.0, 20.0, "Punjab"), (45.0, 10.0, 55.0, 20.0, "12"),
    (10.0, 30.0, 45.0, 40.0, "Haryana"), (50.0, 30.0, 60.0, 40.0, "03"),
    (10.0, 50.0, 30.0, 60.0, "Goa"), (35.0, 50.0, 45.0, 60.0, "21"),
    (10.0, 70.0, 45.0, 80.0, "Kerala"), (50.0, 70.0, 60.0, 80.0, "01"),
    (10.0, 90.0, 35.0, 100.0, "Bihar"), (40.0, 90.0, 50.0, 100.0, "73"),
    (10.0, 110.0, 50.0, 120.0, "Rajasthan"), (55.0, 110.0, 65.0, 120.0, "07"),
    (10.0, 130.0, 40.0, 140.0, "Assam"), (45.0, 130.0, 55.0, 140.0, "45"),
    (300.0, 300.0, 320.0, 310.0, "99"),
    (10.0, 150.0, 80.0, 160.0, "Industrial Supply"),
]
MAP_PAGE = ("Industrial Supply Punjab 12 Haryana 03 Goa 21 Kerala 01 Bihar 73 Rajasthan 07 Assam 45 99 "
            "Total 310")


def _pin(value_text, geography, series_title="Industrial Supply", series_id="s1"):
    return reply(measure="count.customers", value_text=value_text, unit="customers", geography=geography,
                 series_title=series_title, series_id=series_id)


def test_a_map_callout_is_bound_to_the_place_printed_next_to_it():
    rows = build([_pin("12", "Punjab"), _pin("03", "Haryana"), _pin("21", "Goa"), _pin("01", "Kerala"),
                  _pin("73", "Bihar"), _pin("07", "Assam"), _pin("45", "Rajasthan")],
                 page_text=MAP_PAGE, words=MAP_WORDS)
    by_value = {r["value_text"]: r for r in rows}
    assert by_value["45"]["geography"] == "Assam"        # the nearest printed name wins, not the model's neighbour
    assert by_value["07"]["geography"] == "Rajasthan"


def test_a_map_pin_with_no_printed_place_loses_its_geography():
    rows = build([_pin("12", "Punjab"), _pin("03", "Haryana"), _pin("21", "Goa"), _pin("01", "Kerala"),
                  _pin("73", "Bihar"), _pin("45", "Assam"), _pin("99", "Rajasthan")],
                 page_text=MAP_PAGE, words=MAP_WORDS)
    unbound = [r for r in rows if r["value_text"] == "99"][0]
    assert unbound["geography"] == ""
    assert "geography_not_printed" in unbound["status_reason"]


def test_a_map_panel_with_no_place_name_is_dropped_not_stored_unbound():
    rows = build([reply(measure="count.banking_outlets_by_state", value_text=value, unit="",
                        series_title="Pan India Presence") for value in ("12", "6", "15", "3", "2")],
                 page_text="Pan India Presence 12 6 15 3 2")
    assert rows == []


def test_a_count_row_needs_no_printed_unit():
    page = "Pan India Presence Banking Outlets 831"
    rows = build([reply(measure="count.outlets", printed_label="Banking Outlets", value_text="831", unit="",
                        series_title="Pan India Presence", period="FY26")], page_text=page)
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]
    assert "no_unit" not in rows[0]["status_reason"]


def test_three_maps_on_one_page_become_three_series():
    rows = build([_pin("12", "Punjab", "Industrial Supply", "s1"), _pin("03", "Haryana", "Industrial Supply", "s1"),
                  _pin("21", "Goa", "HoReCa", "s1"), _pin("01", "Kerala", "HoReCa", "s1"),
                  _pin("73", "Bihar", "Dealers", "s1"), _pin("45", "Assam", "Dealers", "s1")],
                 page_text=MAP_PAGE + " HoReCa Dealers", words=MAP_WORDS)
    assert len({r["series_id"] for r in rows}) == 3
    assert {r["segment"] for r in rows} == {"Industrial Supply", "HoReCa", "Dealers"}


def test_a_cagr_printed_right_after_its_value_is_a_cagr():
    page = ("Revenue from Operations (INR Crores) FY22 FY23 FY24 FY25 297.5 488.6 620.3 620.4 27.8% CAGR")
    rows = build([reply(measure="revenue_growth_yoy", value_text="27.8%", unit="%",
                        series_title="Revenue from Operations (INR Crores)")], page_text=page)
    assert rows[0]["measure"] == "revenue_growth_cagr"


# ---------------------------------------------------------------- T-230 stage G dictionary expansion
T248_TREE = frozenset({
    "revenue.volume", "revenue.price", "revenue.total", "revenue.order_book", "revenue.mix",
    "cost.raw_material", "cost.employee", "cost.power_fuel", "cost.other",
    "margin.ebitda", "margin.gross", "capex.amount", "capacity.add",
    "debt.level", "debt.cost", "equity.shares", "equity.dividend", "working_capital.days",
})


def test_every_measure_has_a_driver_node_or_a_stated_none():
    assert len(obs.MEASURES) == 276
    assert len({m[0] for m in obs.MEASURES}) == len(obs.MEASURES)
    for mid, _name, _family, node in obs.MEASURES:
        assert node in T248_TREE or node.startswith("none: "), f"{mid}: {node!r}"


def test_stage_g_aliases_and_label_maps_point_at_a_dictionary_id():
    families = {m[0]: m[2] for m in obs.MEASURES}
    for alias, target in obs.MEASURE_ALIASES.items():
        assert alias not in families, f"{alias} is both an alias and a dictionary id"
        assert target in families, f"{alias} -> {target} is not a dictionary id"
    for label, mid in obs.SCRIPT_LABELS.items():
        assert mid in families, f"{label} -> {mid} is not a dictionary id"


def test_stage_g_aliases_split_by_printed_unit_family():
    assert obs.canonical_measure("return_on_equity", "", "", "", "%", "") == "roe"
    assert obs.canonical_measure("count.banking_outlets", "", "", "", "", "") == "count.outlets"
    assert obs.canonical_measure("gnpa_percent", "", "", "", "%", "") == "gnpa_pct"
    assert obs.canonical_measure("gnpa", "GNPA", "", "", "%", "") == "gnpa_pct"
    assert obs.canonical_measure("gnpa", "GNPA", "", "", "₹ Cr", "") == "gnpa.value"
    assert obs.canonical_measure("gross_npa", "Gross NPAs at the end of period/year", "", "", "%", "") == \
        "gnpa_pct"
    assert obs.canonical_measure("gross_npa", "Gross NPAs at the end of period/year", "", "", "INR Cr", "") == \
        "gnpa.value"
    # a mixed-family id is not aliased wholesale: its money rows stay on the model's measure
    assert obs.canonical_measure("net_debt_equity_ratio", "Net Debt Equity ratio", "", "", "INR crores", "") == \
        "net_debt_equity_ratio"
    assert obs.canonical_measure("net_debt_equity_ratio", "Net Debt Equity ratio", "", "", "", "") == \
        "net_debt_equity"


def test_a_label_map_applies_only_when_the_unit_family_fits():
    assert obs.canonical_measure("mix.share", "Employee Cost", "", "", "%", "") == "mix.share"
    assert obs.canonical_measure("mix.share", "Employee Cost", "", "", "Rs Crs", "") == "employee_benefits_expense"
    assert obs.canonical_measure("tax_growth_yoy", "Tax", "", "", "%", "") == "tax_growth_yoy"
    assert obs.canonical_measure("whatever", "Tax", "", "", "Rs Crs", "") == "total_tax_expense"


def test_norm_label_keeps_a_leading_roman_letter_and_still_drops_list_marks():
    assert obs.norm_label("Investments") == "investments"
    assert obs.norm_label("Depreciation") == "depreciation"
    assert obs.norm_label("Cost of goods sold") == "cost of goods sold"
    assert obs.norm_label("i) Revenue") == "revenue"
    assert obs.norm_label("(ii) Investments") == "investments"
    assert obs.norm_label("3. Revenue") == "revenue"
    assert obs.script_measure("Depreciation") == "depreciation_and_amortisation_expense"


def test_unit_families_energy_and_bps():
    assert obs.infer_unit_family("MU") == "energy"
    assert obs.infer_unit_family("MWh") == "energy"
    assert obs.infer_unit_family("GWh") == "energy"
    assert obs.infer_unit_family("bps") == "bps"
    assert obs.family_ok("percent", "bps")            # stage-C rows stored a bps unit under percent
    assert not obs.family_ok("bps", "percent")
    families = {m[0]: m[2] for m in obs.MEASURES}
    assert families["generation.volume"] == "energy"
    assert families["ebitda_margin_change_bps"] == "bps"
    assert families["pat_margin_change_bps"] == "bps"
    for mid in ("working_capital_days", "inventory_days", "debtor_days", "payable_days", "cash_conversion_cycle"):
        assert families[mid] == "time"


def test_outlets_atms_and_stores_take_the_deck_period():
    for mid in ("count.outlets", "count.atms", "count.stores", "count.branches", "gnpa_pct", "gnpa.value"):
        assert obs.is_stock_measure(mid), mid
    assert not obs.is_stock_measure("capacity.utilisation")
    assert not obs.is_stock_measure("count.countries")


def test_an_energy_row_verifies_only_with_its_printed_unit():
    measures = obs.measure_index()
    page = obs.norm_space("Generation 1200 MU FY24")
    row = {"measure": "generation.volume", "printed_label": "Generation", "value_text": "1200", "unit": "MU",
           "unit_family": "energy", "period": "FY24", "entity_scope": "company", "scale": 1}
    status, reasons = obs.evaluate_status(dict(row), page, measures)
    assert status == "verified", reasons
    row["unit"] = ""
    row["unit_family"] = ""
    status, reasons = obs.evaluate_status(dict(row), page, measures)
    assert status == "unverified" and "no_unit" in "; ".join(reasons)


def test_create_db_seeds_the_stage_g_dictionary_aliases_and_nodes():
    con = obs.create_db(":memory:")
    try:
        assert con.execute("SELECT COUNT(*) FROM measure_dict").fetchone()[0] == len(obs.MEASURES)
        assert con.execute("SELECT COUNT(*) FROM measure_alias").fetchone()[0] == len(obs.MEASURE_ALIASES)
        assert con.execute("SELECT driver_node FROM measure_dict WHERE id='nim'").fetchone()[0] == "revenue.price"
        assert con.execute("SELECT unit_family FROM measure_dict WHERE id='generation.volume'").fetchone()[0] == \
            "energy"
        assert con.execute("SELECT canonical FROM measure_alias WHERE alias='count.banking_outlets'").fetchone()[0] \
            == "count.outlets"
    finally:
        con.close()


# --------------------------------------------------------------------------- stage I (new-company read)


def test_a_per_unit_figure_never_takes_the_crore_scale():
    page = "Financial Highlights\nEPS (INR)\n4.57\nH1-FY25\nPPA Realisation\n5.53\n₹/ kWh\nFY26\nRs Cr\n"
    rows = build([
        reply(measure="eps", value_text="4.57", unit="INR", printed_label="EPS (INR)", printed_axis="H1-FY25",
              period="H1-FY25", scale=10000000),
        reply(measure="revenue.price", value_text="5.53", unit="₹/ kWh", printed_label="PPA Realisation",
              printed_axis="FY26", period="FY26", scale=10000000),
    ], page_text=page)
    assert [row["scale"] for row in rows] == [1, 1]


def test_a_trillion_unit_is_1e12_and_not_a_missing_scale():
    page = "Strong Construction Industry Outlook\nConstruction Industry (₹ tn)\n38.5\nFY28E\n"
    rows = build([reply(measure="market.value", value_text="38.5", unit="₹ tn", printed_label="",
                        printed_axis="Construction Industry (₹ tn)", period="FY28E", period_kind="estimate",
                        entity_scope="industry")], page_text=page)
    assert rows[0]["scale"] == 1e12


def test_an_axis_tick_on_a_statement_table_is_not_a_tick():
    table = ("Consolidated Balance Sheet\nParticulars (Rs. In Cr)\nMar-24\n0\n1\n2\n3\n4\n"
             "Intangible assets\n3\n")
    chart = "Mar-24\nIntangible assets\n0\n1\n2\n3\n4\n3\n"
    row = reply(measure="other_intangible_assets", value_text="3", unit="Rs. In Cr", printed_label="Intangible assets",
                printed_axis="Mar-24", period="Mar-24")
    table_rows = build([row], page_text=table)
    assert table_rows[0]["status"] == "verified", table_rows[0]["status_reason"]
    chart_rows = build([row], page_text=chart)
    assert chart_rows[0]["status"] == "unverified" and "axis_tick" in chart_rows[0]["status_reason"]


def test_a_comparison_word_is_never_a_period():
    page = "Segment Results of the Company (YOY)\nY-O-Y Growth (%)\n37.5%\n"
    rows = build([reply(measure="revenue_growth_yoy", value_text="37.5%", unit="%",
                        printed_label="Real Estates and Other Income", printed_axis="Y-O-Y Growth (%)",
                        period="Y-O-Y")], page_text=page)
    assert rows[0]["period"] == ""
    assert rows[0]["status"] == "unverified" and "no_period" in rows[0]["status_reason"]
    page2 = "Segment Results\nMar-25\n37.5%\n"
    rows = build([reply(measure="revenue_growth_yoy", value_text="37.5%", unit="%",
                        printed_label="Real Estates and Other Income", printed_axis="Mar-25",
                        period="QoQ")], page_text=page2)
    assert rows[0]["period"] == "Mar-25"


def test_lakh_sq_ft_is_area_and_billion_units_is_energy():
    assert obs.infer_unit_family("Lakhs sq ft") == "area"
    assert obs.infer_unit_family("mn sq. ft.") == "area"
    assert obs.infer_unit_family("Billion units") == "energy"
    assert obs.infer_unit_family("BU") == "energy"
    page = "Year wise Deliveries\nChennai Shubham\nUnsold Area (Lakhs sq ft)\n0.07\nFY26\n"
    rows = build([reply(measure="area.unsold", value_text="0.07", unit="Lakhs sq ft",
                        printed_label="Chennai Shubham", printed_axis="Unsold Area (Lakhs sq ft)",
                        period="FY26")], page_text=page)
    assert rows[0]["unit_family"] == "area"
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]


def test_a_unicode_hyphen_matches_an_ascii_hyphen_in_a_label():
    page = "Historical Consolidated Balance Sheet\nTotal Non \u2010 Current Liabilities\n2,421.8\nSept-25\n"
    rows = build([reply(measure="total_non_current_liabilities", value_text="2,421.8", unit="Rs. Lacs.",
                        printed_label="Total Non - Current Liabilities", printed_axis="Sept-25",
                        period="Sept-25")], page_text=page)
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]
    assert obs.text_has("Total Non \u2013 Current Liabilities", "Total Non - Current Liabilities")


def test_the_dictionary_covers_area_delivered_esg_intensity_and_peak_demand():
    measures = obs.measure_index()
    for mid in ("area.delivered", "area.under_construction", "water_intensity", "water_intensity_reduction",
                "energy_intensity", "energy_intensity_reduction", "demand.peak"):
        assert mid in measures, mid
    assert obs.MEASURE_ALIASES["area_delivered_recognized_for_revenue"] == "area.delivered"
    assert obs.MEASURE_ALIASES["water_consumption_intensity_reduction"] == "water_intensity_reduction"
    assert obs.MEASURE_ALIASES["peak_demand"] == "demand.peak"
    page = "Quarter wise Performance\nArea Delivered & Recognized for Revenue\n6.91\nQ3FY26\nTotal\n"
    rows = build([reply(measure="area_delivered_recognized_for_revenue", value_text="6.91",
                        unit="Lakhs Sq. ft.", printed_label="Total",
                        printed_axis="Area Delivered & Recognized for Revenue", period="Q3FY26")],
                 page_text=page)
    assert rows[0]["measure"] == "area.delivered"
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]


def test_a_crossed_threshold_is_a_lower_bound_never_the_actual_figure():
    page = "Takyon Story: From Inception to Today\nCrossed revenue milestone of\n₹35 Crores\n2018-19\n"
    rows = build([reply(measure="revenue.value", value_text="₹35 Crores", unit="Crores",
                        printed_label="Crossed revenue milestone of", period="2018-19")], page_text=page)
    assert rows[0]["value_kind"] == "lower_bound"
    assert rows[0]["status"] == "unverified" and "lower_bound" in rows[0]["status_reason"]
    count_row = reply(measure="count.employees", value_text="156", unit="",
                      printed_label="Members with more than 5 years with us", period="FY24")
    assert obs.lower_bound_kind(dict(count_row, value_text="156")) == ""


def test_peak_demand_is_its_own_measure_and_a_country_figure():
    page = "India Power Demand Growth\nPeak Demand (GW)\n243\n2023-24\n"
    rows = build([reply(measure="capacity.total", value_text="243", unit="GW",
                        printed_label="Peak Demand (GW)", printed_axis="Peak Demand (GW)",
                        series_title="India Power Demand Growth", period="2023-24", entity_scope="industry")],
                 page_text=page)
    assert rows[0]["measure"] == "demand.peak"
    assert rows[0]["entity_scope"] == "country"


def test_a_footnote_basis_overrides_the_page_basis_for_its_period():
    page = ("Particulars (Rs Cr.)\nFY23*\nFY24*\nFY25**\nExpenses\nEmployee benefit expenses\n21.28\n28.91\n47.28\n"
            "* FY23 & FY24 financial numbers are on Standalone basis \n"
            "** FY25 financial numbers are on consolidated basis on account of conversion of HKRP Innovations "
            "Limited from a limited liability partnership to a public limited company.\n")
    rows = build([
        reply(measure="employee_benefits_expense", value_text="28.91", unit="Rs Cr.",
              printed_label="Employee benefit expenses", printed_axis="FY24*", period="FY24",
              group_path="Expenses", group_source="printed"),
        reply(measure="employee_benefits_expense", value_text="47.28", unit="Rs Cr.",
              printed_label="Employee benefit expenses", printed_axis="FY25**", period="FY25",
              group_path="Expenses", group_source="printed"),
    ], page_text=page)
    assert [row["basis"] for row in rows] == ["standalone", "consolidated"]


# ---------------------------------------------------------------- T-230 stage K aliases and printed column headers

def _printed_line(x, y, text):
    words, cursor = [], float(x)
    for token in text.split():
        words.append((cursor, float(y), cursor + 6.0 * len(token), float(y) + 10.0, token))
        cursor += 6.5 * len(token) + 3
    return words


def test_stage_k_dictionary_adds_the_driver_measures_the_annual_report_printed():
    families = {m[0]: m[2] for m in obs.MEASURES}
    for mid in ("dividend_per_share", "accumulated_depreciation", "gross_block", "count.shares", "dscr",
                "inventory_turnover", "receivable_turnover", "payable_turnover", "net_capital_turnover",
                "other_operating_revenue"):
        assert mid in families, mid
    assert families["dividend_per_share"] == "money_per_unit"
    assert families["count.shares"] == "count"


def test_stage_k_aliases_map_only_same_meaning_names_and_leave_governance_alone():
    assert obs.canonical_measure("interest_cost", "Interest cost", "", "", "crores", "") == "finance_cost"
    assert obs.canonical_measure("net_block", "Net Block", "", "", "₹ in Lakhs", "") == \
        "property_plant_and_equipment"
    assert obs.canonical_measure("debt_service_coverage_ratio", "Debt Service Coverage Ratio", "", "", "", "") == \
        "dscr"
    assert obs.canonical_measure("inventory_turnover_ratio", "Inventory Turnover Ratio", "", "", "", "") == \
        "inventory_turnover"
    assert obs.canonical_measure("equity_shares_outstanding", "Outstanding at the end of the year", "", "",
                                 "Number", "") == "count.shares"
    assert obs.canonical_measure("dividend_per_share", "Dividend per share (₹)", "", "", "₹", "") == \
        "dividend_per_share"
    # a governance / compliance name is never mapped onto a driver measure
    for name in ("shareholding_percentage", "sitting_fees", "csr_amount_spent", "count.workers",
                 "statutory_dues_disputed", "annual_general_meeting_number", "section_reference"):
        assert obs.canonical_measure(name, "", "", "", "", "") == name


def test_stage_k_basis_comes_from_the_column_header_over_the_value():
    words = _printed_line(60, 100, "Standalone") + _printed_line(300, 100, "Consolidated")
    assert obs.column_basis(words, "60.0,200.0,120.0,210.0") == "standalone"
    assert obs.column_basis(words, "300.0,200.0,380.0,210.0") == "consolidated"


def test_stage_k_one_printed_basis_heading_covers_the_rows_below_it():
    words = _printed_line(60, 100, "Consolidated:") + [(300.0, 200.0, 380.0, 210.0, "5,678")]
    assert obs.column_basis(words, "300.0,200.0,380.0,210.0") == "consolidated"


def test_stage_k_no_header_above_the_value_is_no_basis_never_a_guess():
    words = [(300.0, 200.0, 380.0, 210.0, "5,678")] + _printed_line(300, 300, "Consolidated")
    assert obs.column_basis(words, "300.0,200.0,380.0,210.0") == ""
    assert obs.column_basis(words, "") == ""


def test_stage_k_period_comes_from_the_column_header_above_the_value():
    words = _printed_line(300, 100, "31 March 2025") + [(300.0, 200.0, 350.0, 210.0, "5,678")]
    assert obs.column_period(words, "300.0,200.0,350.0,210.0") == "March 2025"
    assert obs.column_period(words, "60.0,200.0,120.0,210.0") == ""


def test_stage_k_a_paragraph_mentioning_a_year_is_not_a_column_header():
    words = _printed_line(60, 90, "Revenue grew in 2024-25 by 10%") + [(60.0, 200.0, 120.0, 210.0, "1,234")]
    assert obs.column_period(words, "60.0,200.0,120.0,210.0") == ""


def test_stage_k_a_fy_span_header_keeps_the_span_not_just_the_first_year():
    assert obs.period_header("FY 2024-25") == "2024-25"
    assert obs.period_header("2024-25") == "2024-25"
    assert obs.period_header("FY25") == "FY25"
    assert obs.period_header("Revenue grew in 2024-25 by 10%") == ""


def test_stage_k_a_row_with_no_period_takes_the_printed_column_header_year():
    page = ("Statement of Profit and Loss\nRevenue\n1,234\nConsolidated Financial Statements\nNote 3\n"
            "5,678\nDisclosure\n")
    words = _printed_line(300, 100, "FY 2024-25") + [(300.0, 200.0, 350.0, 210.0, "5,678")]
    rows = build([reply(measure="revenue.value", printed_label="Revenue", value_text="5,678",
                        unit="₹ crore", period="", series_id="s1")], page_text=page, words=words)
    assert rows[0]["period"] == "2024-25", rows[0]["period"]
    assert rows[0]["period_source"] == "column_header"
    assert "no_period" not in rows[0]["status_reason"]


def test_stage_k_a_row_with_no_basis_takes_the_printed_section_heading():
    page = ("Statement of Profit and Loss\nRevenue\n1,234\nConsolidated Financial Statements\nNote 3\n"
            "5,678\nDisclosure\n")
    words = _printed_line(300, 100, "Consolidated") + [(300.0, 200.0, 350.0, 210.0, "5,678")]
    rows = build([reply(measure="revenue.value", printed_label="Revenue", value_text="5,678",
                        unit="₹ crore", period="FY25", series_id="s1")], page_text=page, words=words)
    assert rows[0]["basis"] == "consolidated"
    assert "basis_conflict" not in rows[0]["status_reason"]


# ---------------------------------------------------------------- T-230 stage L proof and label gates

def _unproven(measure, label, value, period="FY25", **kw):
    """A row whose only defect is a group with no printed source: a parts proof could verify it, a label cannot."""
    base = dict(measure=measure, printed_label=label, value_text=value, unit="Rs Cr", period=period,
                group_path="Revenue", group_source="")
    base.update(kw)
    return reply(**base)


def test_stage_l_a_parts_sum_needs_two_nonzero_distinct_parts():
    page = ("Revenue FY25 Total 0 North 0 South 0 Total 20 East 10 West 10 Total 100 North 100 South 0.01 "
            "North 60 South 40")
    zero = build([
        _unproven("revenue.value", "Total", "0", is_total=True),
        _unproven("revenue.value", "North", "0"),
        _unproven("revenue.value", "South", "0"),
    ], page_text=page)
    assert all(row["status"] == "unverified" for row in zero), [r["status_reason"] for r in zero]
    assert all("parts sum to the printed total" not in row["status_reason"] for row in zero)
    equal = build([
        _unproven("revenue.value", "Total", "20", is_total=True),
        _unproven("revenue.value", "East", "10"),
        _unproven("revenue.value", "West", "10"),
    ], page_text=page)
    assert all("parts sum to the printed total" not in row["status_reason"] for row in equal)
    own_part = build([
        _unproven("revenue.value", "Total", "100", is_total=True),
        _unproven("revenue.value", "North", "100"),
        _unproven("revenue.value", "South", "0.01"),
    ], page_text=page)
    assert all("parts sum to the printed total" not in row["status_reason"] for row in own_part)
    valid = build([
        _unproven("revenue.value", "Total", "100", is_total=True),
        _unproven("revenue.value", "North", "60"),
        _unproven("revenue.value", "South", "40"),
    ], page_text=page)
    assert all(row["status"] == "verified" for row in valid), [r["status_reason"] for r in valid]


def test_stage_l_a_generic_label_verifies_only_when_the_heading_names_the_measure():
    page = ("BRSR minimum wages\nEmployees\nTotal Permanent Workers\nMale\nFemale\n"
            "Total employees / workers in respective category (A)\nFY 2024-25\n4648\n1\n"
            "Interest Cost\nChange in Present Value of Obligation\n₹ in Lakhs\n54.41\n"
            "Total Employees\nTotal (A)\n175\n")
    rows = build([
        reply(measure="count.employees", printed_label="Male", value_text="4648", period="FY 2024-25",
              group_path="Total Permanent Workers", group_source="printed"),
        reply(measure="count.employees", printed_label="Female", value_text="1", period="FY 2024-25",
              group_path="Employees > Permanent", group_source="printed"),
        reply(measure="finance_cost", printed_label="Interest Cost", value_text="54.41", unit="₹ in Lakhs",
              period="FY 2024-25", group_path="Change in Present Value of Obligation", group_source="printed"),
    ], page_text=page)
    assert all("generic_label" in row["status_reason"] for row in rows), [r["status_reason"] for r in rows]
    assert all(row["status"] == "unverified" for row in rows)
    named = build([reply(measure="count.employees", printed_label="Total Employees", value_text="175",
                         printed_axis="Total (A)", period="FY 2024-25", group_path="Employees",
                         group_source="printed")], page_text=page)
    assert "generic_label" not in named[0]["status_reason"], named[0]["status_reason"]
    assert named[0]["status"] == "verified", named[0]["status_reason"]


def test_stage_l_a_gratuity_interest_cost_is_never_finance_cost():
    page = ("Gratuity\nChange in Present Value of Obligation\nInterest Cost\nYear ended March 31, 2025\n"
            "₹ in Lakhs\n54.41\n")
    rows = build([reply(measure="finance_cost", printed_label="Interest Cost", value_text="54.41",
                        unit="₹ in Lakhs", period="Year ended March 31, 2025",
                        group_path="Change in Present Value of Obligation", group_source="printed")],
                 page_text=page)
    assert "defined-benefit interest cost" in rows[0]["status_reason"]
    assert rows[0]["status"] == "unverified"


def test_stage_l_a_generic_category_word_must_match_the_measure():
    page = "Total Workers\nFY 2023-24\n494\nEmployees\n175\n"
    wrong = build([reply(measure="count.beneficiaries", printed_label="Total Workers", value_text="494",
                         period="FY 2023-24")], page_text=page)
    assert "generic_label" in wrong[0]["status_reason"], wrong[0]["status_reason"]
    right = build([reply(measure="count.employees", printed_label="Total Workers", value_text="494",
                         period="FY 2023-24", group_path="Employees", group_source="printed")],
                  page_text=page)
    assert "generic_label" not in right[0]["status_reason"], right[0]["status_reason"]
    assert right[0]["status"] == "verified", right[0]["status_reason"]


def test_stage_l_a_page_section_heading_sets_the_basis_when_no_header_does():
    page = ("Annual Report 2025-26\nNote 47 Capital Management\nNet debt\nAs at 31 March 2025\n967.58\n"
            "NOTES TO CONSOLIDATED FINANCIAL STATEMENTS (CONTD.)\nFOR THE YEAR ENDED MARCH 31, 2027\n"
            "(All amounts in ₹ Million unless otherwise stated)\nAnnual Report 2025-26\n182\n")
    assert obs.page_basis("Notes to Consolidated Financial Statements") == "consolidated"
    assert obs.page_basis("The Group") == "consolidated"
    assert obs.page_basis("Standalone Financial Statements") == "standalone"
    assert obs.page_basis("Standalone Financial Statements\nNotes to Consolidated Financial Statements") == ""
    rows = build([reply(measure="net_debt", printed_label="Net debt", value_text="967.58",
                        printed_axis="As at 31 March 2025", unit="₹ crores",
                        period="As at 31 March 2025")], page_text=page)
    assert rows[0]["basis"] == "consolidated", rows[0]["status_reason"]


def test_stage_l_a_date_inside_an_inline_comparative_is_not_the_period():
    page = ("Quoted instruments\nAs at 31 March 2025\n1,14,062.01\nUnits 1,14,062.01 (31 March 2024 : NIL)\n")
    assert obs.comparative_period("March 2024", page)
    assert not obs.comparative_period("March 2025", page)
    assert obs.comparative_period("March 2024", page, "Units 1,14,062.01 (31 March 2024 : NIL)")
    assert not obs.comparative_period("March 2025", page, "As at March 2025 (31 March 2024 : NIL)")
    rows = build([reply(measure="investment_units", printed_label="Aditya Birla Sun Life MoneyManager Fund",
                        printed_axis="Units 1,14,062.01 (31 March 2024 : NIL)", value_text="1,14,062.01",
                        unit="Units", period="March 2024", series_title="Quoted instruments")], page_text=page)
    assert rows[0]["period"] == "", rows[0]["period"]
    assert "no_period" in rows[0]["status_reason"], rows[0]["status_reason"]


def test_stage_l_an_as_at_closing_balance_is_a_point_in_time_period():
    page = ("Capital Management\nClosing as on 31st March 2024\n967.58\n"
            "01.04.2023 - 31.03.2024\n₹ crore\n")
    assert obs.apply_instant_period({"printed_label": "Closing as on 31st March 2024",
                                     "printed_axis": "", "period": "01.04.2023 - 31.03.2024"})
    rows = build([reply(measure="net_debt", printed_label="Closing as on 31st March 2024",
                        printed_axis="01.04.2023 - 31.03.2024", value_text="967.58", unit="₹ crore",
                        period="01.04.2023 - 31.03.2024")], page_text=page)
    assert rows[0]["period_kind"] == "instant", rows[0]["period_kind"]
    assert "March 2024" in rows[0]["period"]
    flow = build([reply(measure="profit_before_exceptional_items_and_tax", printed_label="Profit before tax",
                        printed_axis="As on March 31, 2024", value_text="56.18", unit="INR in Crore",
                        period="As on March 31, 2024", period_kind="actual")],
                 page_text="Profit before tax\nAs on March 31, 2024\n56.18\n")
    assert flow[0]["period_kind"] == "actual", flow[0]["status_reason"]


def test_stage_l_recheck_downgrades_a_stage_k_generic_label_and_a_degenerate_proof():
    page = "Employees Total Permanent Workers Male 4648 FY 2024-25 Revenue Total 0 North 0 South 0"
    try:
        _make_store(pages=(page,), first_page=14)
        con = obs.create_db(":memory:")
        rows = build([
            reply(measure="count.employees", printed_label="Male", value_text="4648", period="FY 2024-25",
                  group_path="Total Permanent Workers", group_source="printed"),
            _unproven("revenue.value", "Total", "0", is_total=True),
            _unproven("revenue.value", "North", "0"),
            _unproven("revenue.value", "South", "0"),
        ], page_text=page)
        for row in rows:                      # simulate the stage-K rows: written as verified
            row.update({"status": "verified", "status_reason": ""})
        obs.write_rows(con, rows)
        stats = obs.recheck_db(con, [str(STORE)])
        statuses = [r[0] for r in con.execute("SELECT status FROM observation ORDER BY observation_id")]
        assert statuses == ["unverified"] * 4, statuses
        assert stats["generic_labels"] == 1
        assert stats["parts_degenerate"] == 1
        con.close()
    finally:
        _cleanup_store()


# --------------------------------------------------------------------------- stage M: declared new measures, transcripts


def test_stage_m_a_new_measure_needs_its_definition_and_driver_node():
    rows = build([reply(measure="NEW:jv_pbt", new_definition="Profit before tax of the joint venture",
                        new_driver_node="margin", printed_label="Jatadhar Port, Odisha",
                        printed_axis="FY28E", period="FY28E")])
    assert rows[0]["measure"] == "NEW:jv_pbt"
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]
    for raw, reason in ((dict(measure="NEW:jv_pbt", new_driver_node="margin"), "new_definition_missing"),
                        (dict(measure="NEW:jv_pbt", new_definition="JV PBT"), "new_driver_node_missing"),
                        (dict(measure="NEW:123", new_definition="JV PBT", new_driver_node="margin"),
                         "new_id_bad"),
                        (dict(measure="jv_pbt", new_definition="JV PBT", new_driver_node="margin"),
                         "undeclared_new")):
        bad = build([reply(**raw)])
        assert bad[0]["status"] == "unverified", raw
        assert reason in bad[0]["status_reason"], (raw, bad[0]["status_reason"])


def test_stage_m_statement_verifies_only_when_its_sentence_is_printed():
    page = ("S. Sharma: We expect 10-12% revenue growth in FY27. Demand is improving in the north. "
            "Operator: Thank you.")
    good = build([{"type": "statement", "measure": "revenue_growth_yoy",
                   "text": "We expect 10-12% revenue growth in FY27.", "speaker": "S. Sharma",
                   "direction": "up"}], page_text=page)
    assert good[0]["record_type"] == "statement"
    assert good[0]["status"] == "verified", good[0]["status_reason"]
    assert good[0]["speaker"] == "S. Sharma" and good[0]["direction"] == "up"
    bad = build([{"type": "statement", "measure": "revenue_growth_yoy",
                  "text": "Margins will expand by 200 basis points.", "speaker": "S. Sharma"}], page_text=page)
    assert bad[0]["status"] == "unverified"
    assert "statement_not_printed" in bad[0]["status_reason"]
    undeclared = build([{"type": "statement", "measure": "margin_surprise",
                         "text": "Demand is improving in the north."}], page_text=page)
    assert "undeclared_new" in undeclared[0]["status_reason"]


def test_stage_m_guidance_verifies_on_its_value_and_period_words():
    page = "We expect 10-12% revenue growth in FY27. Next year will be better."
    good = build([{"type": "guidance", "measure": "revenue_growth_yoy", "period": "FY27",
                   "low": "10", "high": "12", "unit": "%", "direction": "up",
                   "text": "We expect 10-12% revenue growth in FY27."}], page_text=page)
    assert good[0]["record_type"] == "guidance"
    assert good[0]["status"] == "verified", good[0]["status_reason"]
    assert good[0]["value"] == 10 and good[0]["value_high"] == 12
    assert good[0]["period_kind"] == "target"
    wrong_period = build([{"type": "guidance", "measure": "revenue_growth_yoy", "period": "FY28",
                           "low": "10", "high": "12", "unit": "%",
                           "text": "We expect 10-12% revenue growth in FY27."}], page_text=page)
    assert "guidance_period_not_in_sentence" in wrong_period[0]["status_reason"]
    wrong_value = build([{"type": "guidance", "measure": "revenue_growth_yoy", "period": "FY27",
                          "low": "15", "unit": "%",
                          "text": "We expect 10-12% revenue growth in FY27."}], page_text=page)
    assert "guidance_value_not_in_sentence" in wrong_value[0]["status_reason"]
    worded = build([{"type": "guidance", "measure": "revenue_growth_yoy", "period": "FY27",
                     "text": "We expect high single-digit growth in FY27."}], page_text=page)
    assert worded == []                  # no printed number: a statement, not a guidance row


def test_stage_m_index_new_measures_and_cluster_proposed_merges():
    con = obs.create_db(":memory:")
    rows = (("NEW:jv_pbt", "profit before tax of the joint venture", "margin", "money"),
            ("NEW:jv_profit_before_tax", "profit before tax of the joint venture", "margin", "money"),
            ("NEW:order_book_growth", "growth of the order book", "revenue", "percent"))
    for number, (measure, definition, node, family) in enumerate(rows, start=1):
        con.execute("INSERT INTO observation (symbol, doc_key, page, known_at, measure, new_definition, "
                    "new_driver_node, unit_family, status) VALUES (?,?,?,?,?,?,?,?,?)",
                    ("X", "d", number, "2025-01-01", measure, definition, node, family, "verified"))
    con.commit()
    assert obs.index_new_measures(con) == 3
    jv = con.execute("SELECT observations, pages, definition, driver_node FROM measure_new "
                     "WHERE new_id='jv_pbt'").fetchone()
    assert jv[0] == 1 and jv[1] == 1 and "joint venture" in jv[2] and jv[3] == "margin"
    clusters = obs.new_measure_clusters(con)
    assert len(clusters) == 1, clusters
    assert set(clusters[0]["ids"]) == {"jv_pbt", "jv_profit_before_tax"}
    csv_path = Path(".tmp/t230/new_merges_test.csv")
    stats = obs.write_new_merges(con, csv_path)
    try:
        assert stats == {"clusters": 1, "ids": 2, "csv": str(csv_path)}
        text = csv_path.read_text(encoding="utf-8")
        assert text.splitlines()[0].startswith("cluster,")
        assert "jv_profit_before_tax" in text
    finally:
        csv_path.unlink(missing_ok=True)
    con.close()


def test_stage_m_transcript_pages_are_selected_from_doc_page_not_routes():
    store = Path(".tmp/t230/transcript_store.db")
    store.parent.mkdir(parents=True, exist_ok=True)
    store.unlink(missing_ok=True)
    con = sqlite3.connect(store)
    con.execute("CREATE TABLE doc (doc_key TEXT, title TEXT, symbol TEXT, known_at TEXT, doc_type TEXT)")
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT)")
    con.execute("INSERT INTO doc VALUES (?,?,?,?,?)", ("t1", "call", "SOMANYCERA", KNOWN_AT, "transcript"))
    con.execute("INSERT INTO doc_page VALUES (?,?,?)", ("t1", 1, "Management said demand is improving."))
    con.execute("INSERT INTO doc_page VALUES (?,?,?)", ("t1", 2, "Notes to Financial Statements. "
                                                               "We expect 10-12% growth in FY27."))
    con.execute("INSERT INTO doc_page VALUES (?,?,?)", ("t1", 3, ""))
    con.commit()
    con.close()
    try:
        pages = obs.pages_from_store(str(store), doc_types=("transcript",), skip_statements=True)
        assert [(p["doc_key"], p["page"]) for p in pages] == [("t1", 1), ("t1", 2)]
        assert all(p["doc_type"] == "transcript" for p in pages)
    finally:
        store.unlink(missing_ok=True)


def test_stage_m_placeholder_brackets_are_not_part_of_the_id_and_junk_ids_are_dropped():
    rows = build([reply(measure="NEW:<jv_pbt>", new_definition="Profit before tax of the joint venture",
                        new_driver_node="margin", printed_label="Jatadhar Port, Odisha",
                        printed_axis="FY28E", period="FY28E")])
    assert rows[0]["measure"] == "NEW:jv_pbt"
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]
    junk = build([reply(measure="NEW:<postal_code>", new_definition="the pin code printed in the letterhead",
                        new_driver_node="none", printed_label="Regd. Office, Mumbai")],
                 page_text="Regd. Office, Mumbai 400026")
    assert junk == []


def test_stage_m_a_currency_or_percent_marker_is_not_part_of_the_value_token():
    page = "Interest expense ₹ in M FY25 85.50 246.97 2,100"
    rows = build([reply(measure="finance_cost", printed_label="Interest expense", value_text="₹85.50",
                        unit="₹ in M", printed_axis="₹ in M", period="FY25"),
                  reply(measure="revenue_growth_yoy", printed_label="Interest expense", value_text="246.97%",
                        unit="%", printed_axis="₹ in M", period="FY25")], page_text=page)
    assert rows[0]["status"] == "verified", rows[0]["status_reason"]
    assert rows[1]["status"] == "verified", rows[1]["status_reason"]


def test_stage_m_a_prose_period_is_not_a_period():
    assert obs.period_is_printed("currently") is False
    assert obs.period_is_printed("this quarter") is False
    assert obs.period_is_printed("corresponding quarter last year") is False
    assert obs.period_is_printed("FY27") is True


