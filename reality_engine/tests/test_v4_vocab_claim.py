"""v4 WP2b — vocabulary, claims, own estimates and the edge DDL on small fixtures.

No live database is opened: every test builds its own sqlite fixture under
``tmp_path``.  The checks are the ones the brief names: 100% of surfaces mapped to
a label or ``other:<raw>``; claims carry a label id and the facets; the estimate's
walk-forward band is measured, never constant; and an estimate at ``as_of=t``
reads nothing with ``known_at > t`` (including a tampered input, which must fail).
"""
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from reality_engine.query.v4 import (build_claim, build_edge_schema, build_own_estimate,
                                     build_vocab, map_vocab_beam)

ISIN = "INE001A01036"     # a real row of tasks/pilot60/UNIVERSE.csv
ISIN2 = "INE001B01026"


@pytest.fixture()
def tmp_path(request):
    """A workspace temp dir: the sandbox's own pytest tmp base is not writable here."""
    base = Path(".tmp") / "v4_wp2b_tests" / request.node.name.replace("::", "_")
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    return base


# --- fixtures ---------------------------------------------------------------
def _con(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _source_dbs(root: Path) -> None:
    """The three extraction stores the vocabulary reads, with a handful of phrases."""
    root.mkdir(parents=True, exist_ok=True)
    cc = _con(root / "concall_facts.db")
    cc.executescript("""
        CREATE TABLE cc_items(doc_id INTEGER, list_name TEXT, idx INTEGER, isin TEXT,
            filed_at TEXT, metric TEXT, value TEXT, unit TEXT, period TEXT, basis TEXT,
            direction TEXT, firmness TEXT, signal TEXT, statement TEXT, quote TEXT,
            item_json TEXT);
        CREATE TABLE cc_docs(doc_id INTEGER PRIMARY KEY, isin TEXT, filed_at TEXT);
    """)
    cc.executemany(
        "INSERT INTO cc_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, "guidance", 0, ISIN, "2026-08-01T10:00:00", "EBITDA margin", "22% and 25%",
             "%", "Q3FY27", "standalone", "maintained", "firm", None, "we are guiding",
             "we are guiding for an EBITDA margin of 22 to 25 percent in Q3FY27", None),
            (1, "key_numbers", 1, ISIN, "2026-08-01T10:00:00", "profit after tax", "450",
             "INR_CRORE", "Q2FY26", "standalone", None, None, None, "PAT was 450",
             "profit after tax came in at 450 crore", None),
            (1, "key_numbers", 2, ISIN, "2026-08-01T10:00:00", "leases", "120", "INR_CRORE",
             None, "standalone", None, None, None, "lease expense",
             "leases of 120 crore were charged", None),
            (1, "key_numbers", 3, ISIN, "2026-08-01T10:00:00", "joint_venture", "5",
             "INR_CRORE", None, None, None, None, None, "JV share",
             "share of the joint venture was 5 crore", None),
            (1, "key_numbers", 4, ISIN, "2026-08-01T10:00:00", None, None, None, None, None,
             None, None, None, "no metric here",
             "a sentence the extractor could not name", None),
            (2, "guidance", 0, ISIN2, None, "revenue", "100-120", "INR_CRORE", "FY27",
             "consolidated", "raised", "indicative", None, "guided revenue",
             "we raise our revenue guidance to 100 to 120 crore for FY27", None),
        ])
    cc.execute("INSERT INTO cc_docs VALUES (2, ?, '2026-07-01T09:00:00')", (ISIN2,))
    cc.commit()
    cc.close()

    ar = _con(root / "ar_facts.db")
    ar.executescript("""
        CREATE TABLE ar_facts(doc_id INTEGER, isin TEXT, filed_at TEXT, category TEXT);
    """)
    ar.executemany("INSERT INTO ar_facts VALUES (?,?,?,?)", [
        (10, ISIN, "2026-06-01T00:00:00", "subsidiary"),
        (10, ISIN, "2026-06-01T00:00:00", "signal"),
        (10, ISIN, "2026-06-01T00:00:00", "employee_benefits"),
        (10, ISIN, "2026-06-01T00:00:00", "joint venture"),
        (11, ISIN2, "2026-05-01T00:00:00", "leases"),
    ])
    ar.commit()
    ar.close()

    df = _con(root / "deck_figures.db")
    df.executescript("""
        CREATE TABLE pages(sha256 TEXT, isin TEXT, known_at TEXT);
        CREATE TABLE facts(sha256 TEXT, page_no INTEGER, metric TEXT);
    """)
    df.execute("INSERT INTO pages VALUES ('h1', ?, '2026-04-01T00:00:00')", (ISIN,))
    df.executemany("INSERT INTO facts VALUES (?,?,?)", [
        ("h1", 1, "Apollo Structural Heavy Sales Mix Q3FY24"),
        ("h1", 2, "profit after tax"),
    ])
    df.commit()
    df.close()


def _estimate_dbs(root: Path) -> None:
    """Two companies' quarterly series (one tagged large, one micro) plus buckets."""
    pilot = root / "pilot" / "pilot60"
    pilot.mkdir(parents=True, exist_ok=True)
    con = _con(pilot / "facts_pilot.db")
    con.executescript("""
        CREATE TABLE company_metric_series(isin TEXT, metric_key TEXT, period_end TEXT,
            period_kind TEXT, basis TEXT, value REAL, unit TEXT, source TEXT, doc_id TEXT,
            known_at TEXT, pit_conf REAL);
    """)
    ends = []
    for y in range(2019, 2027):
        for md in ("-03-31", "-06-30", "-09-30", "-12-31"):
            ends.append(f"{y}{md}")
    ends = [e for e in ends if e <= "2026-06-30"]
    rows = []
    for i, end in enumerate(ends):
        for key, base in (("revenue", 100.0), ("pat", 10.0), ("eps", 2.0)):
            rows.append((ISIN, key, end, "quarter", "consolidated",
                         round(base * (1.05 ** (i // 4)), 6),
                         "INR" if key == "eps" else "INR_CRORE", "xbrl",
                         f"doc{i}", f"{end}T00:00:00", 1.0))
    for i, end in enumerate(ends[:9]):     # ISIN2: too few quarters for a full band
        rows.append((ISIN2, "revenue", end, "quarter", "consolidated",
                     round(50.0 * (1.02 ** (i // 4)), 6), "INR_CRORE", "xbrl",
                     f"doc{i}", f"{end}T00:00:00", 1.0))
    con.executemany("INSERT INTO company_metric_series VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()

    ms = _con(pilot / "market_state_pilot.db")
    ms.executescript("""
        CREATE TABLE company_state_daily(isin TEXT, date TEXT, mcap_bucket TEXT);
    """)
    ms.executemany("INSERT INTO company_state_daily VALUES (?,?,?)", [
        (ISIN, "2026-09-30", "large"),
        (ISIN2, "2026-09-30", "micro"),
    ])
    ms.commit()
    ms.close()


@pytest.fixture()
def sources(tmp_path):
    _source_dbs(tmp_path)
    return tmp_path


@pytest.fixture()
def vocab_db(sources, tmp_path):
    out = tmp_path / "v4_vocab.db"
    report = build_vocab.build(out, sources, strict=False, isins=[ISIN, ISIN2])
    assert report["ok"] is True
    return out


# --- vocabulary -------------------------------------------------------------
def test_every_surface_is_mapped_to_a_label_or_other(sources, vocab_db):
    con = _con(vocab_db)
    surfaces = con.execute("SELECT count(*) FROM surface").fetchone()[0]
    mapped = con.execute("SELECT count(*) FROM map").fetchone()[0]
    labels = {r[0] for r in con.execute("SELECT label_id FROM label")}
    values = [r[0] for r in con.execute("SELECT map_value FROM map")]
    con.close()
    assert surfaces == mapped
    assert all(v in labels or v.startswith("other:") for v in values)


def test_declared_label_layer_maps_the_known_cases(sources, vocab_db):
    con = _con(vocab_db)
    got = {r[0]: r[1] for r in con.execute(
        "SELECT surface_verbatim, map_value FROM surface s JOIN map m USING(surface_id)")}
    con.close()
    assert got["profit after tax"] == "pat"
    assert got["leases"] == "lease"                       # VOCAB_PASS1 §3 error #18
    assert got["joint venture"] == "jv"                   # §3 error #20
    assert got["employee_benefits"] == "employee_benefits"  # §3 row 8, now its own L2
    assert got["signal"] == "other:signal"                # correctly other
    assert got["Apollo Structural Heavy Sales Mix Q3FY24"] == "revenue"
    assert got["EBITDA margin"] == "ebitda_margin"
    # 100% mapped is not 100% labelled: the split is reported, never rounded up
    assert any(v.startswith("other:") for v in got.values())


def test_promotion_queue_uses_the_declared_thresholds(sources, vocab_db):
    con = _con(vocab_db)
    rows = con.execute("SELECT status, n_occurrences, n_isins, n_doctypes "
                       "FROM other_cluster").fetchall()
    con.close()
    for status, n, nin, ndt in rows:
        queued = n >= build_vocab.PROMOTE_MIN_N and nin >= build_vocab.PROMOTE_MIN_COMPANIES \
            and ndt >= build_vocab.PROMOTE_MIN_DOCTYPES
        assert (status == "queued") == queued


def test_label_for_is_deterministic_and_specific():
    words = build_vocab.words_of("employee benefits expense")
    assert build_vocab.label_for(words) == ("employee_benefits", "phrase")
    # a phrase the declared layer cannot name stays `other`, never guessed
    assert build_vocab.label_for(build_vocab.words_of("signal ratio")) == ("other", "other")


def test_short_ratio_surfaces_label_after_the_mapper_fix():
    """ROE/ROCE/ROCE % normalise to one token; the old declared layer missed them."""
    assert build_vocab.map_surface("ROE") == "roe"
    assert build_vocab.map_surface("ROCE") == "roce"
    assert build_vocab.map_surface("ROCE %") == "roce"
    assert build_vocab.map_surface("ROA") == "roa"
    assert build_vocab.map_surface("RONW") == "ronw"
    # a statement name must not steal a specific line from its own topic
    assert build_vocab.map_surface("Consolidated P&L – Depreciation") == "depreciation"
    assert build_vocab.map_surface("Consolidated P&L – EBITDA") == "ebitda"


def test_spelling_variants_merge_before_labelling():
    """`p&l`/`p_and_l`/`pnl` and `balance sheet`/`balance_sheet` are one phrase."""
    base = build_vocab.words_of("profit and loss")
    for variant in ("p&l", "P&L", "p_and_l", "pnl", "p/l"):
        assert build_vocab.words_of(variant) == base
    assert base <= build_vocab.words_of("consolidated_p_and_l")
    assert build_vocab.map_surface("p&l") == "financials"
    assert (build_vocab.map_surface("balance sheet")
            == build_vocab.map_surface("balance_sheet") == "financials")


def test_source_drift_fails_the_build_instead_of_rescaling(sources, tmp_path):
    report = build_vocab.build(None, sources, strict=True, isins=[ISIN, ISIN2])
    assert report["ok"] is False
    assert "source drift" in report["error"]


# --- claims -----------------------------------------------------------------
def test_claim_rows_carry_label_ids_and_facets(sources, vocab_db, tmp_path):
    db = tmp_path / "v4.db"
    report = build_claim.build(db, sources, vocab_db=vocab_db)
    assert report["inserted"] == 6
    con = _con(db)
    rows = {r["surface_raw"]: dict(r) for r in con.execute("SELECT * FROM claim")}
    con.close()

    guide = rows["EBITDA margin"]
    assert guide["topic"] == "ebitda_margin"
    assert guide["magnitude"] == pytest.approx(23.5)      # midpoint of 22 and 25
    assert guide["unit"] == "%"
    assert guide["horizon"] == "Q3FY27"
    assert guide["certainty"] == "stated"
    assert guide["guidance_vs_fact"] == "guidance"
    assert guide["known_at"] == "2026-08-01T10:00:00"     # filing time, never a crawl date

    pat = rows["profit after tax"]
    assert pat["topic"] == "pat"
    assert pat["magnitude"] == pytest.approx(450.0)
    assert pat["direction"] == "neutral"
    assert pat["certainty"] is None
    assert pat["guidance_vs_fact"] == "fact"
    assert pat["surface_id"] is not None                   # the verbatim surface is linked

    raised = rows["revenue"]
    assert raised["direction"] == "up" and raised["direction_raw"] == "raised"
    assert raised["certainty"] == "expected"
    assert raised["magnitude"] == pytest.approx(110.0)
    assert raised["horizon"] == "FY27"
    assert raised["known_at"] == "2026-07-01T09:00:00"     # COALESCEd from cc_docs

    unnamed = [r for r in rows.values() if r["topic"] == "other"]
    assert unnamed and unnamed[0]["surface_raw"] is None


def test_claim_spotcheck_is_mechanical_and_reports_the_sample(sources, vocab_db, tmp_path):
    db = tmp_path / "v4.db"
    build_claim.build(db, sources, vocab_db=vocab_db)
    check = build_claim.spot_check(db, n=4, seed=7)
    assert check["n"] == 4 and len(check["sample"]) == 4
    assert "mechanical" in check["note"]
    for row in check["sample"]:
        assert row["quote"]


def test_horizon_and_magnitude_parsers():
    assert build_claim.horizon_of("Q3FY27") == "Q3FY27"
    assert build_claim.horizon_of("FY '28") == "FY28"
    assert build_claim.horizon_of("Q2 FY2026") == "Q2FY26"
    assert build_claim.horizon_of("current financial year") == "current financial year"
    assert build_claim.parse_magnitude("80% plus", "%") == 80.0
    assert build_claim.parse_magnitude("40-50%", "%") == 45.0
    assert build_claim.parse_magnitude("FY24 to FY27", "INR_CRORE") is None
    assert build_claim.parse_magnitude("22% and 25%", None) is None


# --- own estimate -----------------------------------------------------------
def test_trend_estimate_rule_is_the_declared_one():
    series = []
    for year, value in (("2021", 100.0), ("2022", 110.0), ("2023", 121.0)):
        for md in ("-03-31", "-06-30", "-09-30", "-12-31"):
            series.append({"period_end": f"{year}{md}", "value": value,
                           "known_at": f"{year}{md}T00:00:00", "doc_id": "d"})
    value, detail = build_own_estimate.trend_estimate(series, "2024-03-31")
    # base 121 * (1 + 0.75 * median(10%, 10%, 10%, 10%)) == 121 * 1.075
    assert value == pytest.approx(121.0 * 1.075)
    assert detail["base_quarter"] == "2023-03-31"
    assert detail["median_yoy"] == pytest.approx(0.10)
    assert all(r[2] <= "2023-12-31T00:00:00" for r in detail["rows"])


def test_trend_estimate_falls_back_to_seasonal_naive_without_growth_history():
    series = [{"period_end": "2023-03-31", "value": 50.0,
               "known_at": "2023-03-31T00:00:00", "doc_id": "d"}]
    value, detail = build_own_estimate.trend_estimate(series, "2024-03-31")
    assert value == pytest.approx(50.0)
    assert detail["median_yoy"] is None
    assert "fell_back" in detail


def test_own_estimate_builds_bands_and_replays_point_in_time(tmp_path):
    root = tmp_path / "data"
    _estimate_dbs(root)
    db = tmp_path / "v4.db"
    report = build_own_estimate.build(db, root, isins=[ISIN, ISIN2])

    assert report["estimates"] > 0
    assert set(report["per_atom"]) == {"fin.revenue", "fin.pat", "fin.eps"}
    assert report["replay"]["ok"] is True and report["replay"]["violations"] == 0

    con = _con(db)
    bands = {tuple(r)[:2]: dict(r) for r in con.execute("SELECT * FROM own_estimate_band")}
    est = dict(con.execute(
        "SELECT * FROM own_estimate WHERE isin=? AND est_atom='fin.revenue' "
        "ORDER BY period_end LIMIT 1", (ISIN,)).fetchone())
    micro = dict(con.execute(
        "SELECT * FROM own_estimate WHERE isin=? AND est_atom='fin.revenue' LIMIT 1",
        (ISIN2,)).fetchone())
    con.close()

    assert est["method"] == "trend"
    assert est["known_at"] == est["as_of"]
    assert est["inputs_json"] and est["n_obs"] >= 8
    assert json.loads(est["inputs_json"])["rows"]
    # the band is measured, not a constant: a real p75 with its floor
    large = bands[("fin.revenue", "large")]
    assert large["n_obs"] >= 8 and large["fallback"] is None
    assert large["band_pct"] == pytest.approx(max(large["p75_abs_pct"], 0.5))
    assert large["measured_from"].startswith("walk-forward")
    # a thin bucket takes the pooled band for the same atom and says so
    assert micro["band_pct"] == pytest.approx(large["band_pct"])
    assert bands[("fin.revenue", "micro")]["fallback"] in ("pooled_atom", "pooled_all")


def test_estimate_at_reads_only_past_inputs_and_a_tampered_input_fails(tmp_path):
    root = tmp_path / "data"
    _estimate_dbs(root)
    db = tmp_path / "v4.db"
    build_own_estimate.build(db, root, isins=[ISIN, ISIN2])

    con = _con(db)
    row = dict(con.execute(
        "SELECT isin, est_atom, period_end, as_of FROM own_estimate "
        "WHERE isin=? AND est_atom='fin.revenue' ORDER BY period_end DESC LIMIT 1",
        (ISIN,)).fetchone())
    con.close()

    at_cut = build_own_estimate.estimate_at(db, row["isin"], row["est_atom"],
                                           row["period_end"], row["as_of"])
    assert at_cut is not None and at_cut["reads_future"] is False
    assert build_own_estimate.estimate_at(db, row["isin"], row["est_atom"],
                                          row["period_end"], "2000-01-01") is None

    # tamper: put an input from the future into one row; the replay check must catch it
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    row = dict(con.execute("SELECT isin, est_atom, period_end, as_of, inputs_json "
                           "FROM own_estimate WHERE isin=? ORDER BY period_end LIMIT 1",
                           (ISIN,)).fetchone())
    detail = json.loads(row["inputs_json"])
    detail["rows"].append(["2099-03-31", 1.0, "2099-03-31T00:00:00", "future"])
    con.execute("UPDATE own_estimate SET inputs_json=? WHERE isin=? AND est_atom=? "
                "AND period_end=? AND as_of=?",
                (json.dumps(detail), row["isin"], row["est_atom"], row["period_end"],
                 row["as_of"]))
    con.commit()
    con.close()
    bad = build_own_estimate.replay_check(db)
    assert bad["ok"] is False and bad["violations"] == 1


# --- edge schema ------------------------------------------------------------
def test_edge_ddl_runs_clean_and_is_idempotent(tmp_path):
    db = tmp_path / "v4.db"
    first = build_edge_schema.build(db)
    assert first["ok"] and first["missing"] == []
    assert set(build_edge_schema.TABLES) <= set(first["tables"])
    second = build_edge_schema.build(db)          # re-run is a no-op
    assert second["ok"] and second["rows"] == {t: 0 for t in build_edge_schema.TABLES}

    con = sqlite3.connect(db)
    con.execute("INSERT INTO edge (driver, target, origin, label, known_at) "
                "VALUES ('crude','paint','measured','verified','2026-01-01')")
    con.commit()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO edge (driver, target, origin, label, known_at) "
                    "VALUES ('crude','tyre','measured','invented','2026-01-01')")
    con.close()


# --- beam mapping (WP8) -----------------------------------------------------
def _beam_store(sources, vocab_db, tmp_path):
    """A pass2 copy of the vocab store plus the declared-unmapped workload file."""
    root = tmp_path / "pilot" / "v4"
    root.mkdir(parents=True, exist_ok=True)
    (root / "unmapped_head.json").write_text(json.dumps([
        {"surface": "signal", "occurrences": 3, "words": "signal"}]))
    con = map_vocab_beam.open_pass2(tmp_path / "v4_vocab_pass2.db", vocab_db)
    return con, root / "unmapped_head.json"


def _fake_poster(answers):
    """Stand-in for the model call: answers[i] gives the i-th reply's JSON body."""
    calls = []

    def poster(system, user, key):
        calls.append(user)
        body = answers[min(len(calls) - 1, len(answers) - 1)]
        n = sum(1 for line in user.splitlines() if line[:1].isdigit() and ". " in line)
        return {"content": json.dumps({str(i): body for i in range(n)}),
                "finish": "stop", "in_tok": 12, "out_tok": 6}
    poster.calls = calls
    return poster


def test_beam_parser_accepts_only_declared_ids():
    allowed = {"pat", "revenue", "other"}
    accepted, rejected = map_vocab_beam.parse_answers(
        '{"0": "pat", "1": "profitability?", "2": "Revenue", "3": "other"',
        {0: None, 1: None, 2: None, 3: None}, allowed)
    assert accepted == {0: "pat", 2: "revenue", 3: "other"}
    assert set(rejected) == {1}          # undeclared -> rejected, never mapped
    # truncated body still yields complete pairs; a missing index is unanswered
    got, bad = map_vocab_beam.parse_answers('{"0":"pat"', {0: None, 1: None}, allowed)
    assert got == {0: "pat"} and set(bad) == {1}


def test_beam_run_resumes_without_redoing_finished_batches(sources, vocab_db, tmp_path):
    con, unmapped = _beam_store(sources, vocab_db, tmp_path)
    rows = map_vocab_beam.workload(con, unmapped)
    assert [r["surface"] for r in rows] == ["signal"]
    labels = map_vocab_beam.labels_of(con)
    assert "pat" in labels and "other" in labels
    plan = map_vocab_beam.plan(rows)
    poster = _fake_poster(["pat"])

    first = map_vocab_beam.run(con, labels, plan, {}, "k", poster=poster, start=1, ceiling=1)
    assert first["batches"] == 1 and first["surfaces"] == 1
    again = map_vocab_beam.run(con, labels, plan, {}, "k", poster=poster, start=1, ceiling=1)
    assert again["batches"] == 0 and again["skipped"] == 1
    assert len(poster.calls) == 1        # the finished batch was not sent again

    assert map_vocab_beam.apply(con) == {"updated": 1}
    value, source, method = con.execute(
        "SELECT m.map_value, m.source, m.method FROM surface s JOIN map m USING(surface_id) "
        "WHERE s.surface_verbatim='signal'").fetchone()
    con.close()
    assert (value, source, method) == ("pat", "beam", "beam")


def test_beam_rejected_answer_is_retried_once_then_other(sources, vocab_db, tmp_path):
    con, unmapped = _beam_store(sources, vocab_db, tmp_path)
    rows = map_vocab_beam.workload(con, unmapped)
    labels = map_vocab_beam.labels_of(con)
    plan = map_vocab_beam.plan(rows)

    poster = _fake_poster(["not_a_label", "pat"])     # first ask rejected, retry answers
    map_vocab_beam.run(con, labels, plan, {}, "k", poster=poster, start=1, ceiling=1)
    assert len(poster.calls) == 2                      # one retry, not a second batch
    answers = [dict(r) for r in con.execute("SELECT * FROM beam_answer")]
    assert answers[0]["label_id"] == "pat" and answers[0]["first_pass"] == 0

    con.execute("DELETE FROM beam_answer")
    con.execute("DELETE FROM beam_batch")
    poster = _fake_poster(["not_a_label", "still_not_a_label"])
    map_vocab_beam.run(con, labels, plan, {}, "k", poster=poster, start=1, ceiling=1)
    map_vocab_beam.apply(con)
    value, label_id = con.execute(
        "SELECT m.map_value, m.label_id FROM surface s JOIN map m USING(surface_id) "
        "WHERE s.surface_verbatim='signal'").fetchone()
    con.close()
    assert label_id is None and value == "other:signal"   # wrong is worse than none

