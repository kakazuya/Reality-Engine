"""T-242: the loader re-applies the live filing_events gate, so an older events db never serves a failed kind as verified."""
from __future__ import annotations

import pytest

from reality_engine.research import filing_events as fe
from reality_engine.scripts import load_observations as lo

COLS = ["symbol", "kind", "status"]
ROWS = [("A", "order_win", "verified"), ("A", "fund_raise", "verified"), ("A", "order_win", "unverified")]


def test_no_kind_gated_means_nothing_loads_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fe, "VERIFIED_KINDS", frozenset())
    rows, moved = lo._gate_event_rows(COLS, ROWS)
    assert moved == 2 and all(r[2] == "unverified" for r in rows)


def test_a_gated_kind_keeps_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fe, "VERIFIED_KINDS", frozenset({"order_win"}))
    rows, moved = lo._gate_event_rows(COLS, ROWS)
    assert moved == 1 and rows[0][2] == "verified" and rows[1][2] == "unverified"


def test_rows_without_status_or_kind_pass_through() -> None:
    rows, moved = lo._gate_event_rows(["symbol"], [("A",)])
    assert moved == 0 and rows == [("A",)]
