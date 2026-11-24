"""T-242: deterministic corroboration of call numbers and guidance against filings (no model)."""
from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from reality_engine.v2 import corroborate as cor

CALL_KNOWN = "2026-10-30T18:00:00"
_TMP_ROOT = Path(__file__).resolve().parents[2] / ".tmp"


@pytest.fixture()
def workdir() -> Iterator[Path]:
    """A throwaway dir under the repo ``.tmp``.

    ``tmp_path`` creates its base dir with mode 0700, which the DSH workspace-write sandbox creates but cannot
    read back, so pytest fails at fixture setup before any test runs.  A default-mode dir under ``.tmp`` works
    everywhere, and teardown removes it."""
    d = _TMP_ROOT / "corroborate_tests" / f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _obs_db(root: Path, rows: list[dict[str, object]]) -> Path:
    path = root / "obs.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE observation (observation_id INTEGER PRIMARY KEY, symbol TEXT, doc_key TEXT, page INTEGER, "
        "known_at TEXT, measure TEXT, value REAL, value_high REAL, value_text TEXT, unit TEXT, scale REAL, "
        "period TEXT, basis TEXT, record_type TEXT, status TEXT, status_reason TEXT)")
    for i, r in enumerate(rows, 1):
        con.execute(
            "INSERT INTO observation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (i, r.get("symbol", "ACME"), "C:/raw/ACME/concall_transcript/call.pdf", 3,
             r.get("known_at", CALL_KNOWN), r["measure"], r["value"], r.get("value_high"),
             r.get("value_text", ""), r.get("unit", "crores"), r.get("scale", 1e7),
             r.get("period", "Q2 FY27"), r.get("basis", ""), r.get("record_type", "number"),
             r.get("status", "unverified"), r.get("status_reason", "transcript_number: pending")))
    con.commit()
    con.close()
    return path


def _store(root: Path, *, xbrl: Sequence[tuple] = (), rp: Sequence[tuple] = (), kpi: Sequence[tuple] = (),
           guidance: Sequence[tuple] = (), symbol: str = "ACME") -> Path:
    path = root / "stores" / "c01" / "c01.db"
    path.parent.mkdir(parents=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE company (symbol TEXT, isin TEXT, bse_code TEXT, name TEXT)")
    con.execute("INSERT INTO company VALUES (?,?,?,?)", (symbol, "INE000A01001", "500001", "Acme Ltd"))
    con.execute("CREATE TABLE doc (doc_key TEXT, symbol TEXT, doc_type TEXT, filing_date TEXT, known_at TEXT)")
    con.execute("INSERT INTO doc VALUES (?,?,?,?,?)",
                ("C:/raw/ACME/concall_transcript/call.pdf", symbol, "transcript", "2026-10-30", CALL_KNOWN))
    con.execute("CREATE TABLE fin_quarter_xbrl (symbol TEXT, fiscal_period TEXT, basis TEXT, line_item TEXT, "
                "value REAL, unit TEXT, scale REAL, known_at TEXT)")
    con.execute("CREATE TABLE ratio_panel (symbol TEXT, fiscal_period TEXT, basis TEXT, metric TEXT, value REAL, "
                "unit TEXT, scale REAL, known_at TEXT)")
    con.execute("CREATE TABLE kpi_series (symbol TEXT, fiscal_period TEXT, basis TEXT, metric TEXT, value REAL, "
                "unit TEXT, scale REAL, known_at TEXT)")
    con.execute("CREATE TABLE guidance (symbol TEXT, metric TEXT, target_period TEXT, low REAL, high REAL, "
                "unit TEXT, said_on TEXT, known_at TEXT)")
    con.executemany("INSERT INTO fin_quarter_xbrl VALUES (?,?,?,?,?,?,?,?)", [(symbol, *r) for r in xbrl])
    con.executemany("INSERT INTO ratio_panel VALUES (?,?,?,?,?,?,?,?)", [(symbol, *r) for r in rp])
    con.executemany("INSERT INTO kpi_series VALUES (?,?,?,?,?,?,?,?)", [(symbol, *r) for r in kpi])
    con.executemany("INSERT INTO guidance VALUES (?,?,?,?,?,?,?,?)", [(symbol, *r) for r in guidance])
    con.commit()
    con.close()
    return path


def _run(root: Path, call_rows: list[dict[str, object]], *, xbrl: Sequence[tuple] = (),
         rp: Sequence[tuple] = (), kpi: Sequence[tuple] = (), guidance: Sequence[tuple] = ()) -> tuple[
        dict, dict[int, tuple[str, str]], Path, Path]:
    obs = _obs_db(root, call_rows)
    store = _store(root, xbrl=xbrl, rp=rp, kpi=kpi, guidance=guidance)
    out = root / "out.db"
    stats = cor.run(obs, store.parents[1], out)
    con = sqlite3.connect(out)
    try:
        rows = {int(r[0]): (str(r[1]), str(r[2])) for r in
                con.execute("SELECT observation_id, status, status_reason FROM observation")}
    finally:
        con.close()
    return stats, rows, obs, out


def test_crore_number_matches_xbrl_rupees(workdir: Path) -> None:
    stats, rows, _obs, _out = _run(
        workdir,
        [{"measure": "revenue_from_operations", "value": 2250.0, "value_text": "Rs. 2,250"}],
        xbrl=[("Q2FY27", "consolidated", "revenue_from_operations", 22500000000.0, "inr", 1.0,
               "2026-10-29T10:00:00")])
    status, reason = rows[1]
    assert status == "verified"
    assert reason == "corroborated: fin_quarter_xbrl.revenue_from_operations Q2FY27 consolidated " \
                     "= 22500000000 inr (pre_call)"
    assert stats["rows_matched"] == 1 and stats["pre_call"] == 1 and stats["post_call"] == 0


def test_margin_matches_ratio_panel(workdir: Path) -> None:
    stats, rows, _obs, _out = _run(
        workdir,
        [{"measure": "ebitda_margin", "value": 23.4, "unit": "%", "scale": 1.0, "value_text": "23.4%"}],
        rp=[("Q2FY27", "consolidated", "ebitda_margin_pct", 23.4, "pct", 1.0, "2026-10-29T10:00:00")])
    assert rows[1][0] == "verified"
    assert rows[1][1] == "corroborated: ratio_panel.ebitda_margin_pct Q2FY27 consolidated = 23.4 pct (pre_call)"
    assert stats["matched_by_measure"] == {"ebitda_margin": 1}


def test_range_matches_any_value_inside(workdir: Path) -> None:
    _stats, rows, _obs, _out = _run(
        workdir,
        [{"measure": "pat", "value": 100.0, "value_high": 120.0, "value_text": "Rs.100-120"}],
        rp=[("Q2FY27", "consolidated", "pat", 1150000000.0, "inr", 1.0, "2026-10-29T10:00:00")])
    assert rows[1][0] == "verified"
    assert "ratio_panel.pat Q2FY27 consolidated = 1150000000 inr (pre_call)" in rows[1][1]


def test_period_mismatch_does_not_match(workdir: Path) -> None:
    stats, rows, _obs, _out = _run(
        workdir,
        [{"measure": "revenue_from_operations", "value": 2250.0}],
        xbrl=[("Q3FY27", "consolidated", "revenue_from_operations", 22500000000.0, "inr", 1.0,
               "2027-01-29T10:00:00")])
    assert rows[1] == ("unverified", "transcript_number: pending")
    assert stats["rows_matched"] == 0 and stats["unmatched_with_counterpart"] == 1


def test_two_percent_difference_does_not_match(workdir: Path) -> None:
    stats, rows, _obs, _out = _run(
        workdir,
        [{"measure": "pat", "value": 100.0}],
        rp=[("Q2FY27", "consolidated", "pat", 1020000000.0, "inr", 1.0, "2026-10-29T10:00:00")])
    assert rows[1][0] == "unverified"
    assert stats["rows_matched"] == 0


def test_guidance_matches_store_row(workdir: Path) -> None:
    stats, rows, _obs, _out = _run(
        workdir,
        [{"measure": "revenue_growth_yoy", "value": 5.0, "value_high": 6.0, "unit": "%", "scale": 1.0,
          "period": "FY27", "record_type": "guidance", "known_at": "2026-08-21T18:32:00",
          "value_text": "5-6%"}],
        guidance=[("revenue_growth", "FY27", 5.0, 6.0, "pct", "2026-08-21", "2026-08-21T18:00:00")])
    assert rows[1] == ("verified", "corroborated: guidance.revenue_growth FY27 = 5-6 pct (pre_call)")
    assert stats["guidance"]["matched"] == 1 and stats["guidance"]["pre_call"] == 1


def test_no_counterpart_stays_unverified(workdir: Path) -> None:
    stats, rows, _obs, _out = _run(
        workdir,
        [{"measure": "revenue.mix", "value": 40.0, "unit": "%", "scale": 1.0, "value_text": "40%"}])
    assert rows[1] == ("unverified", "transcript_number: pending")
    assert stats["rows_matched"] == 0
    assert stats["no_counterpart"] == {"revenue.mix": 1}
    assert stats["unmatched_with_counterpart"] == 0


def test_post_call_filing_is_reported(workdir: Path) -> None:
    stats, rows, _obs, _out = _run(
        workdir,
        [{"measure": "revenue_from_operations", "value": 2250.0}],
        xbrl=[("Q2FY27", "consolidated", "revenue_from_operations", 22500000000.0, "inr", 1.0,
               "2027-02-10T10:00:00")])
    assert rows[1][0] == "verified"
    assert rows[1][1].endswith("(post_call)")
    assert stats["post_call"] == 1 and stats["pre_call"] == 0


def test_input_db_is_never_written(workdir: Path) -> None:
    obs = _obs_db(workdir, [{"measure": "revenue_from_operations", "value": 2250.0}])
    store = _store(workdir, xbrl=[("Q2FY27", "consolidated", "revenue_from_operations", 22500000000.0,
                                    "inr", 1.0, "2026-10-29T10:00:00")])
    before = (obs.read_bytes(), obs.stat().st_mtime_ns)
    out = workdir / "out.db"
    cor.run(obs, store.parents[1], out)
    assert obs.read_bytes() == before[0]
    assert obs.stat().st_mtime_ns == before[1]
    con = sqlite3.connect(obs)
    try:
        assert con.execute("SELECT status FROM observation").fetchone()[0] == "unverified"
    finally:
        con.close()
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT status FROM observation").fetchone()[0] == "verified"
    finally:
        con.close()
