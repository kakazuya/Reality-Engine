"""T-205 round 4: the store menu and the model-written plan, on a fixture store with the model call mocked."""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = REPO_ROOT / "plugins" / "reality-data" / "server"
for path in (str(SERVER), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from reality_engine.answer import evidence_pack as ep  # noqa: E402
from reality_engine.answer import lookups_extra, menu, plan_model  # noqa: E402

SYMBOL = "ACME"
AS_OF = "2026-11-11"
SCHEMA = """
CREATE TABLE company(symbol TEXT, isin TEXT, isin_from TEXT, isin_to TEXT, isin_source TEXT,
                     bse_code TEXT, name TEXT);
CREATE TABLE doc(doc_key TEXT, symbol TEXT, doc_type TEXT, title TEXT, filing_date TEXT, known_at TEXT,
                 pages INTEGER, source TEXT, source_key TEXT);
CREATE TABLE fin_annual_line(symbol TEXT, line_item TEXT, fiscal_year TEXT, basis TEXT, value REAL,
                             unit TEXT, known_at TEXT);
CREATE TABLE fin_quarter_xbrl(symbol TEXT, line_item TEXT, fiscal_period TEXT, basis TEXT, value REAL,
                              known_at TEXT, period_end TEXT);
CREATE TABLE fin_quarter_printed(symbol TEXT, line_item TEXT, fiscal_period TEXT, basis TEXT, value REAL,
                                 known_at TEXT);
CREATE TABLE kpi_series(id INTEGER PRIMARY KEY, symbol TEXT, metric TEXT, fiscal_period TEXT, known_at TEXT);
CREATE TABLE ratio_panel(symbol TEXT, metric TEXT, fiscal_period TEXT, known_at TEXT);
CREATE TABLE guidance(id INTEGER PRIMARY KEY, symbol TEXT, metric TEXT, target_period TEXT, said_on TEXT,
                      known_at TEXT);
CREATE TABLE shp_category(symbol TEXT, category TEXT, quarter_end TEXT, known_at TEXT);
CREATE TABLE price_delivery(symbol TEXT, exchange TEXT, date TEXT, open REAL, high REAL, low REAL,
                            close REAL, prev_close REAL, volume INTEGER, delivery_pct REAL,
                            adj_close REAL, known_at TEXT);
CREATE TABLE share_capital(symbol TEXT, as_of_date TEXT, known_at TEXT);
CREATE TABLE transcript_statement(id INTEGER PRIMARY KEY, symbol TEXT, topics TEXT, call_date TEXT,
                                  known_at TEXT);
CREATE TABLE page_atom(symbol TEXT, period TEXT, known_at TEXT);
CREATE TABLE event(symbol TEXT, kind TEXT, known_at TEXT);
"""


def _fixture(tmp_path: Path) -> Path:
    db = tmp_path / "store.db"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.execute("INSERT INTO company VALUES (?,?,?,?,?,?,?)",
                (SYMBOL, "INE000A01001", "", "", "profile", "500001", "Acme Limited"))
    con.executemany("INSERT INTO fin_annual_line VALUES (?,?,?,?,?,?,?)", [
        (SYMBOL, "cash_flow_from_operations", "FY26", "consolidated", 900.0, "inr_cr", "2026-05-30"),
        (SYMBOL, "revenue_from_operations", "FY26", "consolidated", 4000.0, "inr_cr", "2026-05-30"),
    ])
    con.executemany("INSERT INTO fin_quarter_xbrl VALUES (?,?,?,?,?,?,?)", [
        (SYMBOL, "revenue_from_operations", "Q2FY27", "consolidated", 1100.0, "2026-10-29", "2026-09-30"),
        (SYMBOL, "revenue_from_operations", "Q2FY26", "consolidated", 1000.0, "2025-10-30", "2025-09-30"),
    ])
    con.execute("INSERT INTO fin_quarter_printed VALUES (?,?,?,?,?,?)",
                (SYMBOL, "revenue_from_operations", "Q2FY27", "consolidated", 1100.0, "2026-10-29"))
    con.execute("INSERT INTO kpi_series(symbol, metric, fiscal_period, known_at) VALUES (?,?,?,?)",
                (SYMBOL, "ebitda_margin_pct", "Q2FY27", "2026-10-29"))
    con.execute("INSERT INTO ratio_panel VALUES (?,?,?,?)", (SYMBOL, "roe", "FY26", "2026-05-30"))
    con.execute("INSERT INTO guidance(symbol, metric, target_period, said_on, known_at) VALUES (?,?,?,?,?)",
                (SYMBOL, "ebitda_margin", "FY27", "2026-11-05", "2026-11-05"))
    con.executemany("INSERT INTO shp_category VALUES (?,?,?,?)", [
        (SYMBOL, "promoter", "2026-09-30", "2026-10-20"),
        (SYMBOL, "promoter", "2026-06-30", "2026-07-20"),
    ])
    con.execute("INSERT INTO share_capital VALUES (?,?,?)", (SYMBOL, "2026-09-30", "2026-10-20"))
    con.execute("INSERT INTO transcript_statement(symbol, topics, call_date, known_at) VALUES (?,?,?,?)",
                (SYMBOL, "margin,guidance", "2026-11-05", "2026-11-05"))
    con.execute("INSERT INTO page_atom VALUES (?,?,?)", (SYMBOL, "Q2FY27", "2026-10-30"))
    con.execute("INSERT INTO event VALUES (?,?,?)", (SYMBOL, "dividend", "2026-10-30"))
    con.executemany("INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?)", [
        ("calls/q2.pdf", SYMBOL, "transcript", "Q2 FY27 call", "2026-11-05", "2026-11-05T16:40:50", 18, "raw", "k1"),
        ("results/q2.pdf", SYMBOL, "results", "Q2 FY27 results", "2026-10-29", "2026-10-29T16:13:56", 16, "raw", "k2"),
        ("results/q1.pdf", SYMBOL, "results", "Q1 FY27 results", "2026-10-29", "2026-10-29T10:00:00", 16, "raw", "k3"),
    ])
    con.executemany("INSERT INTO price_delivery VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        (SYMBOL, "NSE", "2026-10-29", 1668.0, 1676.0, 1660.0, 1673.0, 1660.0, 900, 60.0, 1673.0, "2026-10-29"),
        (SYMBOL, "NSE", "2026-10-30", 1660.0, 1670.0, 1620.0, 1627.9, 1673.0, 1496289, 14.07, 1627.9, "2026-10-30"),
        (SYMBOL, "NSE", "2026-11-02", 1630.0, 1645.0, 1625.0, 1640.0, 1627.9, 800, 55.0, 1640.0, "2026-11-02"),
        (SYMBOL, "NSE", "2026-11-06", 99.0, 101.0, 98.0, 100.0, 99.0, 1000, 55.0, 100.0, "2026-11-06"),
        (SYMBOL, "NSE", "2026-11-09", 100.0, 103.0, 99.0, 102.0, 100.0, 1200, 60.0, 102.0, "2026-11-09"),
    ])
    con.commit()
    con.close()
    return db


@pytest.fixture()
def store():
    # a directory under the repo .tmp, not tmp_path: the sandbox cannot write into a mkdtemp dir nor remove a
    # pytest basetemp through its \\?\ path
    here = REPO_ROOT / ".tmp" / f"plan_store_{uuid.uuid4().hex[:10]}"
    here.mkdir(parents=True, exist_ok=True)
    db = _fixture(here)
    old = os.environ.get("REALITY_PILOT3_DB")
    os.environ["REALITY_PILOT3_DB"] = str(db)
    try:
        yield db
    finally:
        if old is None:
            os.environ.pop("REALITY_PILOT3_DB", None)
        else:
            os.environ["REALITY_PILOT3_DB"] = old
        shutil.rmtree(here, ignore_errors=True)


def _menu(store) -> dict:
    return menu.build(store, SYMBOL, AS_OF)


def test_menu_lists_a_cash_flow_line_fin_does_not_serve(store):
    m = _menu(store)
    text = menu.render(m)
    assert "cash_flow_from_operations" in m["financial_lines"]
    assert "cash_flow_from_operations" in m["index"]["fin"]
    # the annual-only line is where the model is told the balance sheet / cash flow lives
    assert "annual ONLY" in text
    assert "cash_flow_from_operations" in text.split("annual ONLY", 1)[1].splitlines()[0]
    assert len(text) < menu.RENDER_LIMIT
    # the quarterly table does not hold it, so a quarter-period fin call cannot serve it
    import lookups_pilot3 as p3
    reply = p3.fin(SYMBOL, "cash_flow_from_operations", period="Q2FY27")
    assert reply["found"] is False


def test_unknown_metric_is_rejected_and_kept_out(store):
    plan = {"parts": [{"id": "p1", "text": "revenue in Q2FY27"}],
            "lookups": [{"part": "p1", "route": "fin", "args": {"measure": "margins_magic", "period": "Q2FY27"}}]}
    ok, rejected = plan_model.validate(plan, _menu(store))
    assert ok == []
    assert any("margins_magic" in r["reason"] and "menu" in r["reason"] for r in rejected)
    assert any("no lookup planned" in r["reason"] for r in rejected)   # the only lookup was rejected


def test_prior_session_lookup_is_kept(store):
    m = _menu(store)
    plan = {"parts": [{"id": "p1", "text": "reaction after Q2FY27 results"},
                      {"id": "p2", "text": "the close before it"}],
            "lookups": [
                {"part": "p1", "route": "tech", "args": {"kind": "reaction", "doc_type": "results"}},
                {"part": "p2", "route": "tech", "args": {"kind": "reaction", "start": "2026-11-06",
                                                          "end": "2026-11-06"}},
                {"part": "p1", "route": "page", "args": {
                    "doc_key": "calls/q2.pdf", "page": 1}},
            ]}
    ok, rejected = plan_model.validate(plan, m)
    assert rejected == []
    assert len(ok) == 3
    prior = [lk for lk in ok if lk["args"].get("start") == "2026-11-06"]
    assert len(prior) == 1 and prior[0]["route"] == "tech"
    assert ok[2]["args"]["doc_key"] == m["doc_prefix"] + "calls/q2.pdf" or ok[2]["args"]["doc_key"] == "calls/q2.pdf"


def test_invalid_json_falls_back_and_is_labelled(store):
    replies = ["sorry, no json here", "still not json"]

    def fake_client(system, user, key):  # noqa: ARG001
        return {"content": replies.pop(0)}

    result = plan_model.write_plan("What was revenue in Q2FY27?", AS_OF, menu.render(_menu(store)),
                                   "beam-free", menu=_menu(store), client=fake_client)
    assert result["planner"] == "script_fallback"
    assert result["model_calls"] == 2
    assert "JSON" in result["reason"]
    assert len(result["raw_replies"]) == 2


def test_repair_call_keeps_a_name_the_menu_prints(store):
    fixed = ('{"parts": [{"id": "p1", "text": "revenue Q2FY27"}], "lookups": '
             '[{"part": "p1", "route": "fin", "args": {"measure": "revenue_from_operations", '
             '"period": "Q2FY27"}}]}')
    replies = [fixed.replace("revenue_from_operations", "turnover"), fixed]

    def fake_client(system, user, key):  # noqa: ARG001
        return {"content": replies.pop(0)}

    result = plan_model.write_plan("What was revenue in Q2FY27?", AS_OF, menu.render(_menu(store)),
                                   "beam-free", menu=_menu(store), client=fake_client)
    assert result["planner"] == "model"
    assert result["model_calls"] == 2
    assert result["rejected"] == []
    assert result["lookups"][0]["args"]["measure"] == "revenue_from_operations"


def test_coverage_has_one_entry_per_part(store):
    parts = [{"id": "p1", "text": "the 52-week range"}, {"id": "p2", "text": "the ROE"}]
    lookups = [{"part": "p1", "route": "tech", "args": {"kind": "range"}},
               {"part": "p2", "route": "ratio", "args": {"ratio": "roe", "period": "FY26"}}]
    pack = ep.gather(store, SYMBOL, {"question": "range and ROE", "periods": ["FY26"], "kind": "all",
                                     "topic_words": []}, AS_OF,
                     lookups=lookups, parts=parts, max_chars=40000)
    assert pack["planner"] == "model"
    assert len(pack["coverage"]) == 2
    assert [c["part"] for c in pack["coverage"]] == ["p1", "p2"]
    assert all(c["lookups"] for c in pack["coverage"])
    tech = pack["coverage"][0]["lookups"][0]
    assert tech["route"] == "tech" and tech["found"] is True
    assert pack["coverage"][0]["status"] in ("found", "some")


def test_reading_copy_prints_each_item_once(store):
    pack = {"as_of": AS_OF, "plan": {"question": "revenue?"},
            "parts": [{"id": "p1", "text": "revenue in Q2FY27"}],
            "coverage": [{"part": "p1", "text": "revenue in Q2FY27", "status": "found", "found": True,
                          "lookups": [
                              {"route": "fin", "args": {"measure": "revenue_from_operations", "period": "Q2FY27"},
                               "base_found": True, "found": True, "items": ["fin-1"], "retries": [], "derived": []}]}],
            "items": [{"id": "fin-1", "route": "fin", "doc_key": "results/q2.pdf", "page": 5,
                       "known_at": "2026-10-29", "lookup": 0, "text": "Revenue from operations 1,100.00",
                       "row": {"value": 1100, "unit": "inr_cr", "period": "Q2FY27", "basis": "consolidated",
                               "measure": "revenue_from_operations"}}]}
    text = ep.reading_text(pack)
    assert text.count("Revenue from operations 1,100.00") == 1
    assert '"value": 1100' not in text       # the item text is printed, not the row beside it
    assert "p1 [found]" in text


# --- round 5 ---------------------------------------------------------------------------------------

def test_union_runs_script_routes_and_plan_lookups(store, monkeypatch):
    def fake_run(p3, sem, tech, route, symbol, args, as_of):  # noqa: ARG001
        if route == "price_rows":
            return {"found": True, "rows": [{"text": "PLAN-EVIDENCE close 100", "known_at": "2026-11-06"}]}
        raise AssertionError(f"unexpected route {route}")

    monkeypatch.setattr(ep, "_run_lookup", fake_run)
    script_plan = ep.plan("What is the 52-week range?", AS_OF, symbol=SYMBOL)
    pack = ep.gather(store, SYMBOL, script_plan, AS_OF, max_chars=180000,
                     lookups=[{"part": "p1", "route": "price_rows", "args": {"dates": ["2026-11-06"]}}],
                     parts=[{"id": "p1", "text": "the prior close"}])
    assert pack["plan_items"] >= 1
    assert pack["script_items"] >= 1            # the round-3 script net still runs
    assert pack["items"][0].get("lookup") is not None   # plan items come first
    reading = ep.reading_text(pack, max_chars=600)
    assert "PLAN-EVIDENCE" in reading
    assert pack.get("reading_cut")                # the script tail was cut to hold the cap
    assert len(reading) <= 600                    # the plan fits, so the copy honours the cap
    assert all(it.get("lookup") is not None for it in pack["items"][:pack["plan_items"]])


def test_zero_lookup_is_retried_without_period_then_words(store, monkeypatch):
    calls = []

    def fake_run(p3, sem, tech, route, symbol, args, as_of):  # noqa: ARG001
        calls.append(dict(args))
        if args.get("terms") == "long phrase of words":
            return {"found": False, "rows": [], "hint": "no row"}
        return {"found": True, "rows": [{"text": f"ROW {args.get('terms')}", "known_at": AS_OF}]}

    monkeypatch.setattr(ep, "_run_lookup", fake_run)
    lookups = [{"part": "p1", "route": "cells",
                "args": {"terms": "long phrase of words", "period": "Q2FY27"}}]
    pack = ep.gather(store, SYMBOL, {"question": "x", "periods": [], "kind": "fact", "metrics": [],
                                     "topic_words": []}, AS_OF, lookups=lookups,
                     parts=[{"id": "p1", "text": "the figure"}])
    entry = pack["coverage"][0]["lookups"][0]
    assert entry["base_found"] is False
    assert entry["found"] is True
    assert entry["retries"]                         # logged retries
    assert any("period" not in r["args"] for r in entry["retries"])
    assert any(r["args"].get("terms") == "long" for r in entry["retries"])
    assert any(r.get("terms") == "allocable"
               for r in ep.retry_args("cells", {"terms": "unallocable", "period": "Q2FY27"}))
    assert pack["coverage"][0]["status"] == "found"


def test_planned_fin_also_fetches_printed_cells(store, monkeypatch):
    def fake_run(p3, sem, tech, route, symbol, args, as_of):  # noqa: ARG001
        return {"found": True, "rows": [{"text": f"{route} row", "known_at": AS_OF}]}

    monkeypatch.setattr(ep, "_run_lookup", fake_run)
    lookups = [{"part": "p1", "route": "fin",
                "args": {"measure": "revenue_from_operations", "period": "Q2FY27"}}]
    pack = ep.gather(store, SYMBOL, {"question": "x", "periods": [], "kind": "fact", "metrics": [],
                                     "topic_words": []}, AS_OF, lookups=lookups,
                     parts=[{"id": "p1", "text": "revenue"}])
    entry = pack["coverage"][0]["lookups"][0]
    assert entry["derived"], "a fin lookup must add its printed cells"
    derived = entry["derived"][0]
    assert derived["route"] == "cells"
    assert derived["args"] == {"terms": "revenue_from_operations", "period": "Q2FY27"}


def test_price_rows_carry_prior_close_and_return(store):
    import lookups_pilot3 as p3
    reply = lookups_extra.price_rows(p3, SYMBOL, AS_OF, dates=["2026-11-06"])
    assert reply["found"] is True
    assert reply["rows"][0]["prev_close"] == 99.0            # the column, not the day's own close
    assert reply["rows"][0]["adj_close"] is not None
    span = lookups_extra.price_rows(p3, SYMBOL, AS_OF, start="2026-11-06", end="2026-11-09")
    assert span["found"] is True and span["n"] == 3          # two sessions plus the return row
    assert span["return_pct"] == 2.0                         # adjusted first-to-last close
    plan = {"parts": [{"id": "p1", "text": "prior close"}],
            "lookups": [{"part": "p1", "route": "price_rows", "args": {"dates": ["2026-11-06"]}}]}
    ok, rejected = plan_model.validate(plan, _menu(store))
    assert rejected == [] and ok[0]["route"] == "price_rows"


def test_menu_lists_price_rows(store):
    assert "price_rows" in menu.render(_menu(store))


def test_reading_copy_is_the_scored_text():
    from reality_engine.answer import pack_recall as pr
    pack = {"as_of": AS_OF, "plan": {"question": "x", "periods": [], "topic_words": []},
            "parts": [], "coverage": [],
            "items": [
                {"id": "pg-0", "route": "page", "lookup": 0, "doc_key": "d", "page": 1, "text": "P" * 500},
                {"id": "topic-1", "route": "topic", "doc_key": "d", "page": 2, "text": "noise " * 40},
                {"id": "topic-2", "route": "topic", "doc_key": "d", "page": 3, "text": "more noise " * 30},
                {"id": "topic-3", "route": "topic", "doc_key": "d", "page": 4, "text": "123.92 crore Q2FY27"},
            ]}
    reading = ep.reading_text(pack, max_chars=700)
    json_text = "\n\n".join(it["text"] for it in pack["items"])
    assert "123.92" not in reading                    # stage (e) dropped the lowest-ranked script item
    assert pr.score_pack(reading, "123.92")[0] == "miss"
    assert pr.score_pack(json_text, "123.92")[0] == "hit"


def test_reading_copy_orders_number_period_then_typed_then_page_then_rest():
    pack = {"as_of": AS_OF, "plan": {"question": "Q2FY27 numbers", "periods": ["Q2FY27"], "topic_words": []},
            "parts": [], "coverage": [],
            "items": [
                {"id": "s1", "route": "search", "lookup": None, "text": "segment revenue 1,100.5 Q2FY27"},
                {"id": "c1", "route": "cells", "lookup": None, "text": "label only cells row"},
                {"id": "p1", "route": "page", "lookup": None, "text": "page text label"},
                {"id": "t1", "route": "topic", "lookup": None, "text": "topic prose"},
            ]}
    text = ep.reading_text(pack, max_chars=60000)
    order = [text.index(m) for m in ("segment revenue", "label only cells row", "page text label", "topic prose")]
    assert order == sorted(order)                     # (a) number+period, (b) typed, then page, then the rest


def test_cap_drops_page_text_before_a_typed_row_that_matches():
    pack = {"as_of": AS_OF, "plan": {"question": "Q2FY27 revenue", "periods": ["Q2FY27"],
                                     "topic_words": ["revenue"]},
            "parts": [], "coverage": [],
            "items": [
                {"id": "fin-0", "route": "fin", "lookup": 0, "doc_key": "d", "page": 1, "text": "P" * 600},
                {"id": "fin-1", "route": "fin", "lookup": None, "doc_key": "d", "page": 2,
                 "text": "TYPED-VALUE 930.40 Q2FY27 revenue"},
                {"id": "pg-1", "route": "page", "lookup": None, "doc_key": "d", "page": 3, "text": "PAGE-" + "y" * 600},
            ]}
    reading = ep.reading_text(pack, max_chars=500)
    assert "TYPED-VALUE 930.40" in reading            # matches a period and a term: never dropped
    assert "PAGE-" not in reading                     # page text is windowed/dropped first


def test_zero_item_lookup_is_not_found(store, monkeypatch):
    def fake_run(p3, sem, tech, route, symbol, args, as_of):  # noqa: ARG001
        return {"found": True, "rows": [{"text": "SAME ROW", "doc_key": "d", "page": 1, "known_at": AS_OF}]}

    monkeypatch.setattr(ep, "_run_lookup", fake_run)
    lookups = [{"part": "p1", "route": "cells", "args": {"terms": "a"}},
               {"part": "p2", "route": "cells", "args": {"terms": "b"}}]
    pack = ep.gather(store, SYMBOL, {"question": "x", "periods": [], "kind": "fact", "metrics": [],
                                     "topic_words": []}, AS_OF, lookups=lookups,
                     parts=[{"id": "p1", "text": "one"}, {"id": "p2", "text": "two"}])
    first, second = pack["coverage"][0], pack["coverage"][1]
    assert first["status"] == "found"
    assert second["status"] == "none"
    assert second["lookups"][0]["found"] is False       # a reply whose only item deduped away is not found
    assert "NOT FOUND" in ep.reading_text(pack)


def test_price_rows_event_doc_uses_the_1530_rule(store):
    import lookups_pilot3 as p3
    after_close = lookups_extra.price_rows(p3, SYMBOL, AS_OF, event_doc="results/q2.pdf")
    assert after_close["found"] is True
    assert after_close["day0"] == "2026-10-30"          # filed 16:13 IST -> next session
    assert "next session" in after_close["day0_rule"]
    rows = {r["date"]: r for r in after_close["rows"]}
    assert set(rows) == {"2026-10-29", "2026-10-30", "2026-11-02"}   # before, day 0, next
    assert rows["2026-10-30"]["prev_close"] == 1673.0
    same = lookups_extra.price_rows(p3, SYMBOL, AS_OF, event_doc="results/q1.pdf")
    assert same["day0"] == "2026-10-29"                 # filed 10:00 IST -> same session
    plan = {"parts": [{"id": "p1", "text": "reaction to the results"}],
            "lookups": [{"part": "p1", "route": "price_rows", "args": {"event_doc": "results/q2.pdf"}}]}
    ok, rejected = plan_model.validate(plan, _menu(store))
    assert rejected == [] and ok[0]["args"]["event_doc"].endswith("results/q2.pdf")


def test_validate_requires_a_lookup_for_every_part(store):
    plan = {"parts": [{"id": "p1", "text": "revenue"}, {"id": "p2", "text": "margin"}],
            "lookups": [{"part": "p1", "route": "fin",
                         "args": {"measure": "revenue_from_operations", "period": "Q2FY27"}}]}
    ok, rejected = plan_model.validate(plan, _menu(store))
    assert len(ok) == 1
    assert any("no lookup planned" in r["reason"] and r["part"] == "p2" for r in rejected)


def test_round9_printed_rows_keep_every_round6_number():
    """T-205 round 9 (round-8 step 2): on the real packs, every figure a typed item printed in round 6 survives the
    round-9 printed row (provenance, absolute paths and nulls aside)."""
    import json
    import re
    root = Path(__file__).resolve().parents[2]
    base, out = root / ".tmp" / "pack_r6", root / ".tmp" / "pack_r9"
    if not base.exists() or not out.exists():
        pytest.skip("round-6 and round-9 packs are not built in this checkout")
    num_re = re.compile(r"-?\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?")
    drop_keys = ("page", "known_at", "doc_key", "source", "rowid", "id", "x0", "y0", "x1", "y1",
                 "preferred_from", "preferred_to", "title", "caption")

    def _strip_provenance(text):
        out, i = [], 0
        while True:
            j = text.find('"provenance"', i)
            if j < 0:
                out.append(text[i:])
                return "".join(out)
            out.append(text[i:j])
            k = text.find("{", j)
            if k < 0:
                return "".join(out)
            depth, m = 0, k
            while m < len(text):
                if text[m] == "{":
                    depth += 1
                elif text[m] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                m += 1
            i = m + 1

    def nums(text):
        found = set()
        text = _strip_provenance(text or "")
        for key in drop_keys:
            text = re.sub(r'"' + re.escape(key) + r'"\s*:\s*("(?:[^"\\]|\\.)*"|\[[^\]]*\]|[^,}\s]+)', "", text)
        for m in num_re.finditer(text):
            try:
                value = float(m.group(0).replace(",", ""))
            except ValueError:
                continue
            if 1900 <= value <= 2100:      # a year, not a figure
                continue
            found.add(value)
        return found

    checked, bad = 0, []
    for setname in ("bluestar", "aurobindo"):
        bdir, odir = base / setname, out / setname
        if not bdir.exists() or not odir.exists():
            continue
        for path in odir.glob("pack_*.json"):
            old_path = bdir / path.name
            if not old_path.exists():
                continue
            r9 = json.loads(path.read_text(encoding="utf-8"))
            r6 = json.loads(old_path.read_text(encoding="utf-8"))
            old = {str(it.get("id")): it for it in r6.get("items") or []}
            for it in r9.get("items") or []:
                if it.get("route") not in ep._TYPED_ROUTES:
                    continue
                old_text = str((old.get(str(it.get("id"))) or {}).get("text") or "")
                missing = nums(old_text) - nums(ep._row_text(it))
                checked += 1
                if missing:
                    bad.append((path.stem, it.get("id"), sorted(missing)[:6]))
    assert checked > 0
    assert not bad, f"round-9 row lost figures: {bad[:20]}"
    from reality_engine.answer import pack_recall as pr
    assert pr.score_pack("return +545.93% (6.46x)", "545.9")[0] == "miss"
    assert pr.score_pack_rounded("return +545.93% (6.46x)", "545.9")[0] == "hit"
    assert pr.score_pack("share count 75,049,043 shares", "75049043")[0] == "hit"
    assert pr.score_pack_rounded("share count 75,049,043 shares", "75049043")[0] == "hit"


def test_price_rows_long_range_returns_endpoints_and_the_return():
    class FakeP3:
        def resolve_symbol(self, symbol):  # noqa: ARG002
            return "ACME"

        def _asof(self, as_of, col="known_at"):  # noqa: ARG002
            return " AND known_at IS NOT NULL AND substr(known_at,1,10) <= ?", ("2026-11-11",)

        def _q(self, sql, args=()):  # noqa: ARG002
            if "FROM price_delivery" in sql and "ORDER BY date" in sql:
                days = [f"2020-{m:02d}-15" for m in range(1, 13)] * 10      # 120 sessions
                return [{"date": d, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0 + i,
                         "prev_close": 10.0 + i - 1, "volume": 100, "delivery_pct": 50.0,
                         "adj_close": 10.0 + i, "known_at": d} for i, d in enumerate(days)]
            return []

    reply = lookups_extra.price_rows(FakeP3(), "ACME", "2026-11-11", start="2020-01-01", end="2020-12-31")
    assert reply["sessions_in_range"] == 120
    assert reply["endpoints_only"] is True
    assert reply["sessions_returned"] is True
    assert reply["n"] == 3                     # two endpoints plus the return row
    assert reply["return_pct"] is not None
    assert reply["rows"][0]["prev_close"] is not None
    assert "adjusted price return" in reply["rows"][-1]["text"]
