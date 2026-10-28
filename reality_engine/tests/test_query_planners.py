"""Fixture tests for the query layer: every planner, PIT and answer assembly.

The fixture is a tiny data root written to a temp dir: the same table names and
columns the planners read, one company, two peers, one policy event, one deck
published after the as_of day.  No live database is touched.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import shutil
from pathlib import Path

from reality_engine.query import answer, load_planners, pit_audit, route
from reality_engine.query.ctx import Ctx

AS_OF = "2026-06-30"
ISIN = "INE000A01001"
PEER = "INE000A01002"


def _make(path: Path, ddl: list[str], rows: list[tuple[str, tuple]]) -> None:
    con = sqlite3.connect(path)
    for statement in ddl:
        con.execute(statement)
    for statement, params in rows:
        con.execute(statement, params)
    con.commit()
    con.close()


def build_root(root: Path) -> None:
    eq = root / "equity_intelligence.db"
    _make(eq, [
        "CREATE TABLE master_companies(isin TEXT, nse_symbol TEXT, bse_code TEXT, "
        "company_name TEXT, industry TEXT, sector TEXT, market_cap_tier TEXT, "
        "is_active INTEGER, is_nifty500 INTEGER)",
        "CREATE TABLE security_master(isin TEXT, nse_symbol TEXT, bse_code TEXT, name TEXT, "
        "bse_status TEXT, first_trade TEXT, last_trade TEXT)",
        "CREATE TABLE symbol_isin_history(exchange TEXT, symbol TEXT, isin TEXT, "
        "first_date TEXT, last_date TEXT, n_days INTEGER)",
        "CREATE TABLE daily_price_delivery(date TEXT, symbol TEXT, isin TEXT, open REAL, "
        "high REAL, low REAL, close REAL, prev_close REAL, change_pct REAL, "
        "total_volume INTEGER, turnover_lacs REAL, num_trades INTEGER, "
        "deliverable_volume INTEGER, delivery_pct REAL, rsi_14 REAL)",
        "CREATE TABLE mkt_nse_index_daily(date TEXT, index_name TEXT, open REAL, high REAL, "
        "low REAL, close REAL, pct_change REAL)",
        "CREATE TABLE mkt_commodity_daily(date TEXT, commodity TEXT, ticker TEXT, "
        "close REAL, adj_close REAL)",
        "CREATE TABLE policy_events(id INTEGER, title TEXT, policy_name TEXT, sectors TEXT, "
        "companies TEXT, direction_for_industry TEXT, effective_date TEXT, "
        "published_at TEXT, quote TEXT)",
        "CREATE TABLE index_membership(index_name TEXT, symbol TEXT, isin TEXT)",
    ], [
        ("INSERT INTO master_companies VALUES (?,?,?,?,?,?,?,?,?)",
         (ISIN, "AAA", "500001", "Alpha Ltd", "Capital Goods", "Industrials", "LARGE", 1, 1)),
        ("INSERT INTO master_companies VALUES (?,?,?,?,?,?,?,?,?)",
         (PEER, "BBB", "500002", "Beta Ltd", "Capital Goods", "Industrials", "MID", 1, 1)),
        ("INSERT INTO security_master VALUES (?,?,?,?,?,?,?)",
         (ISIN, "AAA", "500001", "Alpha Ltd", "Active", "2019-01-01", "2026-06-26")),
        ("INSERT INTO symbol_isin_history VALUES (?,?,?,?,?,?)",
         ("NSE", "AAA", ISIN, "2019-01-01", "2026-06-26", 10)),
        ("INSERT INTO symbol_isin_history VALUES (?,?,?,?,?,?)",
         ("NSE", "BBB", PEER, "2019-01-01", "2026-06-26", 10)),
        ("INSERT INTO index_membership VALUES (?,?,?)", ("Nifty 50", "AAA", ISIN)),
        ("INSERT INTO policy_events VALUES (?,?,?,?,?,?,?,?,?)",
         (1, "Copper duty cut", "copper duty", "Capital Goods", "", "positive",
          "2026-05-01", "2026-04-25T10:00:00", "duty cut on copper")),
    ])
    con = sqlite3.connect(eq)
    for i, day in enumerate(("2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04",
                             "2026-06-05", "2026-06-30")):
        for isin, symbol, close in ((ISIN, "AAA", 100 + i), (PEER, "BBB", 200 + i)):
            con.execute("INSERT INTO daily_price_delivery(date,symbol,isin,open,high,low,close,"
                        "prev_close,change_pct,total_volume,delivery_pct,rsi_14) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (day, symbol, isin, close, close + 1, close - 1, close,
                         close - 1, 1.0, 1000, 40.0 + i, 25.0 if i == 2 else 55.0))
    con.execute("INSERT INTO mkt_nse_index_daily VALUES (?,?,?,?,?,?,?)",
                ("2026-06-04", "Nifty IT", 1, 2, 1, 100.0, -0.6))
    con.execute("INSERT INTO mkt_nse_index_daily VALUES (?,?,?,?,?,?,?)",
                ("2026-06-04", "Nifty Energy", 1, 2, 1, 100.0, -12.47))
    con.execute("INSERT INTO mkt_commodity_daily VALUES (?,?,?,?,?)",
                ("2026-06-04", "copper", "copper", 100.0, 100.0))
    con.commit()
    con.close()

    rx = root / "results_xbrl.db"
    _make(rx, [
        "CREATE TABLE filings(file TEXT, isin TEXT, period_end TEXT, dissem_ts TEXT, "
        "broadcast_ts TEXT, filing_ts TEXT, xbrl_url TEXT)",
        "CREATE TABLE filings_isin(file TEXT, isin TEXT)",
        "CREATE TABLE facts(file TEXT, concept TEXT, context TEXT, period_start TEXT, "
        "period_end TEXT, value REAL, unit TEXT)",
    ], [
        ("INSERT INTO filings VALUES (?,?,?,?,?,?,?)",
         ("f1", ISIN, "2026-06-30", "2026-07-10T12:00:00", None, None, "u1")),
        ("INSERT INTO filings VALUES (?,?,?,?,?,?,?)",
         ("f2", ISIN, "2025-06-30", "2025-07-10T12:00:00", None, None, "u2")),
        ("INSERT INTO filings VALUES (?,?,?,?,?,?,?)",
         ("f3", PEER, "2026-06-30", "2026-07-11T12:00:00", None, None, "u3")),
        ("INSERT INTO filings_isin VALUES (?,?)", ("f1", ISIN)),
        ("INSERT INTO filings_isin VALUES (?,?)", ("f2", ISIN)),
        ("INSERT INTO filings_isin VALUES (?,?)", ("f3", PEER)),
        ("INSERT INTO facts VALUES (?,?,?,?,?,?,?)",
         ("f1", "RevenueFromOperations", "OneD", "2026-04-01", "2026-06-30", 1100.0, "INR")),
        ("INSERT INTO facts VALUES (?,?,?,?,?,?,?)",
         ("f2", "RevenueFromOperations", "FourD", "2025-04-01", "2025-06-30", 1000.0, "INR")),
        ("INSERT INTO facts VALUES (?,?,?,?,?,?,?)",
         ("f3", "RevenueFromOperations", "OneD", "2026-04-01", "2026-06-30", 900.0, "INR")),
    ])

    ar = root / "ar_facts.db"
    _make(ar, [
        "CREATE TABLE ar_facts(doc_id INTEGER, piece INTEGER, isin TEXT, symbol TEXT, "
        "fiscal_year TEXT, filed_at TEXT, page INTEGER, category TEXT, item TEXT, "
        "value REAL, unit TEXT, period TEXT, basis TEXT, quote TEXT)",
        "CREATE TABLE ar_docs(doc_id INTEGER, isin TEXT, symbol TEXT, filed_at TEXT)",
    ], [
        ("INSERT INTO ar_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         (11, 1, ISIN, "AAA", "FY26", "2026-06-20", 5, "financials", "Trade receivables",
          200.0, "INR crore", "FY26", "consolidated", "trade receivables")),
        ("INSERT INTO ar_docs VALUES (?,?,?,?)", (11, ISIN, "AAA", "2026-06-20")),
    ])

    deck = root / "deck_figures.db"
    _make(deck, [
        "CREATE TABLE pages(sha256 TEXT, page_no INTEGER, isin TEXT, symbol TEXT, "
        "doc_type TEXT, known_at TEXT)",
        "CREATE TABLE facts(sha256 TEXT, page_no INTEGER, metric TEXT, period TEXT, "
        "value REAL, unit TEXT)",
    ], [
        ("INSERT INTO pages VALUES (?,?,?,?,?,?)",
         ("s1", 1, ISIN, "AAA", "deck", "2026-06-01T09:00:00")),
        ("INSERT INTO pages VALUES (?,?,?,?,?,?)",
         ("s2", 1, ISIN, "AAA", "deck", "2026-10-24T09:00:00")),
        ("INSERT INTO facts VALUES (?,?,?,?,?,?)", ("s1", 1, "capacity", "FY26", 10.0, "MW")),
        ("INSERT INTO facts VALUES (?,?,?,?,?,?)", ("s2", 1, "capacity", "FY27", 99.0, "MW")),
    ])

    cc = root / "concall_facts.db"
    _make(cc, [
        "CREATE TABLE cc_docs(doc_id INTEGER, isin TEXT, symbol TEXT, filed_at TEXT, "
        "period_discussed TEXT)",
        "CREATE TABLE cc_items(doc_id INTEGER, list_name TEXT, idx INTEGER, isin TEXT, "
        "metric TEXT, value TEXT, unit TEXT, period TEXT, quote TEXT, statement TEXT)",
    ], [
        ("INSERT INTO cc_docs VALUES (?,?,?,?,?)", (21, ISIN, "AAA", "2026-05-01", "Q4FY26")),
        ("INSERT INTO cc_items VALUES (?,?,?,?,?,?,?,?,?,?)",
         (21, "guidance", 1, ISIN, "margin guidance", "18-20%", "%", "FY27",
          "we guide margins of 18-20%", "management guided")),
    ])

    try:
        import duckdb
        snap = root / "snapshots"
        snap.mkdir()
        dc = duckdb.connect(str(snap / "truth_2026-06-30.duckdb"))
        dc.execute("CREATE TABLE events(isin TEXT, known_at_utc TEXT, kind TEXT, "
                   "source_ref TEXT, summary TEXT)")
        dc.execute("CREATE TABLE px_daily(exch TEXT, entity_id TEXT, date DATE, isin TEXT, "
                   "symbol TEXT, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, "
                   "adj_close DOUBLE, volume BIGINT, delivery_pct DOUBLE)")
        dc.execute("INSERT INTO events VALUES (?,?,?,?,?)",
                   [ISIN, "2026-06-03T18:00:00", "results", "xbrl:f1", "Q4 results filed"])
        for i, day in enumerate(("2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04")):
            dc.execute("INSERT INTO px_daily VALUES ('NSE','E1',? ,?, 'AAA', ?,?,?,?,?,1000,40.0)",
                       [day, ISIN, 100 + i, 101 + i, 99 + i, 100 + i, 100 + i])
        dc.close()
    except Exception:  # noqa: BLE001 - duckdb is optional; SERIES falls back to SQLite
        pass


def case(**over):
    base = {
        "mid": "T0001", "source_bank": "test", "family": [2], "entity_level": "stock",
        "answer_kind": "number", "archetype": None,
        "question": "AAA revenue Q1FY27", "entities": [{"symbol": "AAA"}],
        "period": "Q1FY27", "as_of": AS_OF, "template": None,
        "rubric": {"required_evidence": ["results_xbrl.filings", "px_nse_adj"]},
        "case_status": "answerable_now",
    }
    base.update(over)
    return base


class PlannerFixtureTest:
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="query_fixture_"))
        build_root(cls.tmp)
        cls.ctx = Ctx(root=cls.tmp)
        cls.planners = load_planners()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_plan(self, name, slots, as_of=AS_OF):
        return self.planners[name](slots, as_of, self.ctx)

    def slots(self, **over):
        return route(case(**over))["slots"]


class TestResolve(PlannerFixtureTest):
    def test_resolve_at_as_of(self):
        hop = self.run_plan("resolve", self.slots())
        assert hop["ok"] is True and hop["rows"][0]["isin"] == ISIN
        assert "symbol_isin_history" in hop["pit"]

    def test_resolve_unknown_entity_is_g1(self):
        hop = self.run_plan("resolve", {"symbol": "NOPE", "symbols": ["NOPE"]})
        assert hop["ok"] is False and hop["why"] == "no_doc"
        assert "gate G1" in (hop["nid_reason"] or "")


class TestFacts(PlannerFixtureTest):
    def test_revenue_fact_is_pit_capped(self):
        hop = self.run_plan("FACTS", self.slots(question="AAA revenue Q1FY27"))
        assert hop["ok"] is True
        assert any("Revenue from operations" in (row["item"] or "") for row in hop["rows"])

    def test_fact_after_as_of_never_returned(self):
        # The deck row known 2026-10-24 is after as_of 2026-06-30 and must not
        # appear even when the deck is the only store holding that metric.
        hop = self.run_plan("FACTS", self.slots(question="AAA capacity FY27",
                                                rubric={"required_evidence": ["deck_facts"]}))
        assert all("99" not in str(row["value"]) for row in hop["rows"])
        assert hop["ok"] is False


class TestSeries(PlannerFixtureTest):
    def test_cagr_and_window(self):
        hop = self.run_plan("SERIES", self.slots(question="AAA 3-yr price CAGR",
                                                period="Oct 2023-Oct 2026",
                                                rubric={"required_evidence": ["px_nse_adj"]}))
        assert hop["ok"] is True
        assert "CAGR" in hop["detail"]

    def test_single_day_close(self):
        hop = self.run_plan("SERIES", self.slots(question="AAA close on 4 June 2026",
                                                period="4 June 2026"))
        assert hop["ok"] is True and "close" in hop["detail"]


class TestScreen(PlannerFixtureTest):
    def test_delivery_ranking(self):
        hop = self.run_plan("SCREEN", self.slots(question="Which large caps saw delivery fall "
                                                "most in the week after 3 June 2026",
                                                period="3 June 2026",
                                                rubric={"required_evidence": ["px_nse_adj"]}))
        assert hop["ok"] is True
        assert "delivery % change" in hop["detail"]

    def test_missing_table_is_blocked_schema(self):
        hop = self.run_plan("SCREEN", self.slots(
            question="Which large caps rank highest on the screen",
            case_status="needs_new_table:company_state_daily"))
        assert hop["ok"] is False and hop["why"] == "schema"
        assert hop["gap"] == "company_state_daily"


class TestEvent(PlannerFixtureTest):
    def test_event_and_reaction(self):
        hop = self.run_plan("EVENT", self.slots(question="AAA rose on 4 June 2026 after results",
                                                family=[9], period="4 June 2026"))
        assert hop["ok"] is True and "results" in hop["detail"]


class TestEvidence(PlannerFixtureTest):
    def test_passage_and_pit(self):
        calls = []

        def fake_doc_find(symbol, terms, doc_type=None, date=None, as_of=None):
            calls.append({"terms": terms, "as_of": as_of})
            return {"found": True, "checked": ["fake"], "passages": [
                {"store": "document_chunks", "doc_type": "ar", "date": "2026-06-20",
                 "doc_id": 1, "page": 3, "quote": "our products serve steel plants"},
                {"store": "document_chunks", "doc_type": "ar", "date": "2026-10-24",
                 "doc_id": 2, "page": 4, "quote": "a later products paragraph"}]}

        self.ctx.overrides["doc_find"] = fake_doc_find
        try:
            hop = self.run_plan("EVIDENCE", self.slots(question="What products does AAA make?",
                                                       answer_kind="text+quote"))
        finally:
            self.ctx.overrides.pop("doc_find", None)
        assert hop["ok"] is True
        assert calls and calls[0]["as_of"] == AS_OF
        assert all(item["known_at"] == "2026-06-20" for item in hop["rows"])
        assert "2026-10-24" not in json.dumps(hop)

    def test_no_passage_is_honest(self):
        self.ctx.overrides["doc_find"] = lambda *a, **k: {
            "found": False, "checked": ["fake"], "reason": "no passage matching 'xyz'"}
        try:
            hop = self.run_plan("EVIDENCE", self.slots(question="What did AAA say about margins?",
                                                       answer_kind="text+quote"))
        finally:
            self.ctx.overrides.pop("doc_find", None)
        assert hop["ok"] is False and hop["why"] == "no_doc"


class TestCompare(PlannerFixtureTest):
    def test_peer_rank(self):
        hop = self.run_plan("COMPARE", self.slots(question="AAA versus BBB: which has better "
                                                  "return over the window",
                                                  entities=[{"symbol": "AAA"}, {"symbol": "BBB"}],
                                                  family=[8]))
        assert hop["ok"] is True
        assert len(hop["rows"]) >= 2


class TestRipple(PlannerFixtureTest):
    def test_policy_trigger_and_market(self):
        hop = self.run_plan("RIPPLE", self.slots(question="copper duty cut beneficiaries",
                                                 family=[18],
                                                 period="2026-05-01"))
        assert hop["ok"] is True
        assert "trigger" in hop["detail"]


class TestExpectations(PlannerFixtureTest):
    def test_opinion_template_is_gated(self):
        hop = self.run_plan("EXPECTATIONS", self.slots(
            question="Is this a good level to start a position?",
            template="entry_timing"))
        assert hop["ok"] is False and hop["why"] == "schema"
        assert hop["gap"] == "consensus_estimates"

    def test_factual_ask_is_not_gated(self):
        hop = self.run_plan("EXPECTATIONS", self.slots(question="AAA revenue Q1FY27",
                                                       template="Q12"))
        assert hop["na"] is True


class TestAnswer(PlannerFixtureTest):
    def test_full_answer_and_zero_pit_violations(self):
        out = answer(case(question="AAA revenue Q1FY27"), self.ctx, close=False)
        assert out["answer"] and not out["nid"]
        assert out["pit_violations"] == []
        assert out["plan"]["chain"][0] == "resolve"

    def test_nid_wording(self):
        out = answer(case(question="AAA will the stock double next year",
                          answer_kind="NOT IN DATA",
                          rubric={"required_evidence": []}, entities=[],
                          family=[20]), self.ctx, close=False)
        assert out["nid"] is True
        assert "NOT IN DATA" in out["answer"] and "Checked:" in out["answer"]
