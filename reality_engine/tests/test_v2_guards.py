"""T-241: the five v2 transcript number guards (Wolf's fy27_v2 ckpt_0001 grade) and --reparse from page_reply."""
from __future__ import annotations

import sqlite3

from reality_engine.v2 import observations as obs

DOC = "D:/x/concall_transcript/abc.pdf"


def _rows(page_text, reply, page=4, v2=True):
    return obs.build_observations(symbol="BESTAGRO", doc_key=DOC, page=page, known_at="2026-08-10T10:00:00",
                                  page_text=page_text, reply_rows=reply, transcript_v2=v2)


def test_guard1_negative_in_words_negates_a_level():
    text = "EBITDA for the quarter stood at negative Rs27 crore against Rs40 crore last year."
    rows = _rows(text, [{"type": "number", "measure": "ebitda", "printed_label": "EBITDA for the quarter stood at",
                         "value_text": "Rs27 crore", "unit": "crore", "period": "Q1 FY27"}])
    assert rows[0]["value"] == -27.0
    pos = _rows("PAT stood at Rs40 crore.", [{"type": "number", "measure": "pat", "printed_label": "PAT stood at",
                                             "value_text": "Rs40 crore", "unit": "crore", "period": "Q1 FY27"}])
    assert pos[0]["value"] == 40.0


def test_guard2_a_period_label_is_never_a_value():
    text = "We expect to break even by H1FY28 and revenue of Rs 500 crore in FY27."
    rows = _rows(text, [
        {"type": "number", "measure": "revenue_from_operations", "printed_label": "break even by",
         "value_text": "H1FY28", "unit": ""},
        {"type": "guidance", "measure": "NEW:breakeven", "low": "H1FY28", "unit": "", "period": "H1 FY28",
         "text": "We expect to break even by H1FY28 and revenue of Rs 500 crore in FY27.",
         "new_definition": "x", "new_driver_node": "none"}])
    assert rows == [] or all(r["value_text"] != "H1FY28" for r in rows)
    assert obs.PERIOD_VALUE_RE.match("Q2") and obs.PERIOD_VALUE_RE.match("FY27") and not obs.PERIOD_VALUE_RE.match("27")


def test_guard3_a_cover_letter_page_gives_no_rows():
    text = ("Scrip Code: 532921 Sub: Transcript of the earnings call. Dear Sir/Madam, please find enclosed the "
            "transcript of the call held on 5 August 2026 for the quarter ended 30 June 2026.")
    reply = [{"type": "statement", "measure": "NEW:filing", "text": "Please find enclosed the transcript of the call.",
              "speaker": ""},
             {"type": "number", "measure": "NEW:scrip", "printed_label": "Scrip Code:", "value_text": "532921"}]
    assert _rows(text, reply, page=1) == []
    assert _rows(text, reply, page=1, v2=False) != []          # v1 rows are unchanged


def test_guard4_and_5_ranges():
    text = "Margins should be 20% or 10% lower. We target $23 billion to $25 billion and 60% to 65% utilisation."
    rows = _rows(text, [
        {"type": "number", "measure": "NEW:margin_target", "printed_label": "Margins should be",
         "value_text": "20%", "high_text": "10%", "unit": "%", "new_definition": "x", "new_driver_node": "none"},
        {"type": "number", "measure": "NEW:market_size", "printed_label": "We target", "value_text": "$23 billion",
         "unit": "USD billion", "new_definition": "x", "new_driver_node": "none"},
        {"type": "number", "measure": "capacity.utilisation", "printed_label": "and", "value_text": "60%",
         "unit": "%"}])
    got = {r["value_text"]: r["value_high"] for r in rows}
    assert got["20%"] is None and got["$23 billion"] == 25.0 and got["60%"] == 65.0


def test_reparse_rebuilds_rows_from_page_reply(tmp_path, monkeypatch):
    out = tmp_path / "o.db"
    con = obs.create_db(out)
    v2_fp = __import__("hashlib").sha256(f"{obs.OBS_READER}\n{obs.PROMPT_TRANSCRIPT_V2}".encode()).hexdigest()[:12]
    raw = ('{"type": "number", "measure": "ebitda", "printed_label": "EBITDA stood at", '
           '"value_text": "Rs27 crore", "unit": "crore", "period": "Q1 FY27"}')
    con.execute("INSERT INTO page_reply VALUES (?,?,?,?,?)", (DOC, 4, f"transcript:{v2_fp}", raw, "t"))
    con.commit()
    store = tmp_path / "c1.db"
    s = sqlite3.connect(store)
    s.execute("CREATE TABLE doc (doc_key TEXT, symbol TEXT, doc_type TEXT, known_at TEXT)")
    s.execute("INSERT INTO doc VALUES (?,?,?,?)", (DOC, "BESTAGRO", "transcript", "2026-08-10"))
    s.commit()
    s.close()
    monkeypatch.setattr(obs, "company_index", lambda dbs: {})
    monkeypatch.setattr(obs, "page_meta", lambda db, key: {"symbol": "BESTAGRO", "doc_type": "transcript",
                                                           "known_at": "2026-08-10"})
    monkeypatch.setattr(obs, "page_text_of", lambda db, key, page: "EBITDA stood at negative Rs27 crore.")
    stats = obs.reparse_db(con, [str(store)])
    assert stats["pages"] == 1 and stats["v2_pages"] == 1
    rows = con.execute("SELECT value FROM observation WHERE doc_key=?", (DOC,)).fetchall()
    assert rows == [(-27.0,)]
    assert con.execute("SELECT outcome, rows FROM page_read").fetchall() == [("rows", 1)]
    con.close()


def test_guard5_both_ends_share_a_unit():
    f = obs.printed_range_high
    assert f("PAT rose by 11% to INR34.5 crores.", "11%", 11.0) is None      # a growth then a level
    assert f("not more than 3% to 4%.", "3%", 3.0) == 4.0
    assert f("about INR310-325 crores", "INR310", 310.0) == 325.0
    assert f("Rs. 58 to Rs. 60, that", "Rs. 58", 58.0) == 60.0
    assert f("60 to 65% utilisation", "60", 60.0) == 65.0


def test_guards_6_to_9_inner_range_fraction_bare_label_cost_of_funds():
    text = ("We are borrowing at 6.3% now. 1/3 of revenue is exports. Margin 40%-45%. "
            "Guidance INR310 to INR320 crore.")
    rows = _rows(text, [
        {"type": "number", "measure": "nim", "printed_label": "We are borrowing at", "value_text": "6.3%", "unit": "%"},
        {"type": "number", "measure": "mix.share", "printed_label": "of revenue", "value_text": "1/3",
         "segment": "exports"},
        {"type": "number", "measure": "ebitda_margin", "printed_label": "Margin", "value_text": "40%-45%", "unit": "%"},
        {"type": "number", "measure": "ebitda", "printed_label": "to", "value_text": "INR320", "unit": "crore"}])
    got = [(r["measure"], r["value"], r["value_high"], r["unit"]) for r in rows]
    assert ("cost_of_funds", 6.3, None, "%") in got
    assert ("mix.share", 33.33, None, "%") in got
    assert ("ebitda_margin", 40.0, 45.0, "%") in got
    assert not [g for g in got if g[1] == 320.0]
    assert obs.inner_range("2024-25") is None and obs.inner_range("12%") is None
