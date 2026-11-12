"""T-204: ``fetch_pilot60_history --fetch --out <csv>`` writes the run's own universe manifest.

The shared ``manifest.csv`` is always written; ``--out`` additionally gets the rows whose ISIN is in the run's
universe, with exactly the same columns, so a one-company run ends with a manifest ``docs_collect`` can read.
No network and no live manifest: a fixture ``Manifest`` and a patched ``Manifest`` for the wiring test.
"""
from __future__ import annotations

import csv
import os
import shutil
from pathlib import Path

from reality_engine.scripts import fetch_pilot60_history as fph

ROOT = Path(__file__).resolve().parents[2]


def _workdir(name: str) -> Path:
    # a plain mkdir, not tempfile.mkdtemp: the sandbox cannot read a directory made with mode 0o700
    root = ROOT / ".tmp" / f"t204_{name}_{os.getpid()}"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    return root


def _fixture(root: Path):
    manifest = fph.Manifest(root / "manifest.db")
    for newsid, isin, symbol in (("n1", "INE000A01001", "AAA"),
                                 ("n2", "INE000B01002", "BBB"),
                                 ("n3", "INE000A01001", "AAA")):
        manifest.put({"isin": isin, "symbol_at_time": symbol, "newsid": newsid, "status": "ok"})
    return manifest


def test_out_carries_only_the_universe_isins_and_the_shared_columns():
    root = _workdir("columns")
    manifest = _fixture(root)
    shared, own = root / "shared.csv", root / "own.csv"
    try:
        assert manifest.write_csv(shared) == 3
        assert manifest.write_csv(own, isins={"INE000A01001"}) == 2
    finally:
        manifest.con.close()
    with shared.open(newline="", encoding="utf-8") as f:
        shared_rows = list(csv.DictReader(f))
    with own.open(newline="", encoding="utf-8") as f:
        own_rows = list(csv.DictReader(f))
    shutil.rmtree(root, ignore_errors=True)
    assert len(shared_rows) == 3
    assert list(own_rows[0]) == list(shared_rows[0]) == fph.CSV_FIELDS
    assert {row["newsid"] for row in own_rows} == {"n1", "n3"}


def _run_fetch(monkeypatch, tmp_dir: Path, extra):
    calls = []

    class FakeManifest:
        def write_csv(self, path=None, isins=None):
            calls.append((path, isins))
            return 0

    universe = [{"isin": "INE000A01001", "symbol": "AAA"}, {"isin": "INE000B01002", "symbol": "BBB"}]
    monkeypatch.setattr(fph, "Manifest", FakeManifest)
    monkeypatch.setattr(fph, "load_universe", lambda path: universe)
    monkeypatch.setattr(fph, "resolve", lambda rows: ({}, None))
    monkeypatch.setattr(fph, "symbol_windows", lambda conn, symbols: {})
    monkeypatch.setattr(fph, "metadata", lambda *args, **kwargs: {})
    monkeypatch.setattr(fph, "plan", lambda *args, **kwargs: [])
    monkeypatch.setattr(fph, "fetch_rows", lambda *args, **kwargs: {})
    monkeypatch.setattr(fph, "scan_pass", lambda manifest: {})
    monkeypatch.setattr(fph, "setup_logging", lambda *args: None)
    argv = ["--fetch", "--universe", str(tmp_dir / "universe.csv"), "--limit", "1", *extra]
    assert fph.main(argv) == 0
    return calls


def test_fetch_with_out_writes_the_shared_and_the_per_company_manifest(monkeypatch):
    out = ROOT / ".tmp" / "t204_universe" / "manifest.csv"
    calls = _run_fetch(monkeypatch, out.parent, ["--out", str(out)])
    assert calls[0] == (None, None)                        # the shared manifest is always written
    assert calls[1] == (out, {"INE000A01001", "INE000B01002"})


def test_fetch_without_out_leaves_the_shared_manifest_alone(monkeypatch):
    assert _run_fetch(monkeypatch, ROOT / ".tmp" / "t204_plain", []) == [(None, None)]
