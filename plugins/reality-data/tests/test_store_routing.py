"""T-203 fixture tests for pilot3 store routing (``REALITY_PILOT3_STORES``).

Two tiny stores with different companies are built under ``.tmp/store_routing/`` and a registry JSON points at
them: every ``pilot3_*`` call resolves its symbol to the store that holds it, the first registered store wins when
both hold it (and the reply says ``also_held_in``), a pinned ``REALITY_PILOT3_DB`` switches routing off, and a
``pilot3_sql`` call that names neither a symbol nor a store lists the registry instead of guessing.

Run one file per process:
    python -m pytest plugins/reality-data/tests/test_store_routing.py -q --basetemp=.tmp/pt1
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
TMP = ROOT / ".tmp" / "store_routing"
ALPHA = TMP / "alpha" / "alpha.db"
BETA = TMP / "beta" / "beta.db"
REGISTRY = TMP / "stores.json"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVER_DIR))

import core  # noqa: E402
import lookups_pilot3 as p3  # noqa: E402

COMPANIES = {
    ALPHA: [("FIXA", "INE111A01011", "511111", "Alpha Industries Limited"),
            ("FIXB", "INE111A01012", "511112", "Alpha Shared Limited")],
    BETA: [("FIXB", "INE222B01012", "522112", "Beta Shared Limited"),
           ("FIXC", "INE222B01013", "522113", "Gamma Works Limited")],
}


def build(path: Path, companies: list[tuple[str, str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE company (symbol TEXT, isin TEXT, bse_code TEXT, name TEXT)")
    con.executemany("INSERT INTO company VALUES (?,?,?,?)", companies)
    con.execute("CREATE TABLE marker (store TEXT)")
    con.execute("INSERT INTO marker VALUES (?)", (path.parent.name,))
    con.commit()
    con.close()


class StoreRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TMP.mkdir(parents=True, exist_ok=True)
        for path, companies in COMPANIES.items():
            build(path, companies)
        REGISTRY.write_text(json.dumps({"generated_at": "2026-11-12T22:00:00", "stores": [
            {"name": "alpha", "path": str(ALPHA), "built": "2026-11-01",
             "symbols": [row[0] for row in COMPANIES[ALPHA]]},
            {"name": "beta", "path": str(BETA), "built": "2026-11-02",
             "symbols": [row[0] for row in COMPANIES[BETA]]},
        ]}), encoding="utf-8")

    def setUp(self) -> None:
        self._env = {key: os.environ.get(key) for key in ("REALITY_PILOT3_DB", "REALITY_PILOT3_STORES")}
        os.environ.pop("REALITY_PILOT3_DB", None)
        os.environ["REALITY_PILOT3_STORES"] = str(REGISTRY)
        p3.close()
        p3._STORE.set(None)
        p3._SYMBOL.set(None)

    def tearDown(self) -> None:
        p3.close()
        p3._STORE.set(None)
        p3._SYMBOL.set(None)
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_a_symbol_is_answered_from_the_store_that_holds_it(self) -> None:
        self.assertTrue(p3.routing_enabled())
        self.assertEqual(p3.resolve_symbol("fixa"), "FIXA")
        self.assertEqual(p3.db_path(), ALPHA)
        self.assertEqual(p3.sql("SELECT store FROM marker", symbol="FIXA")["rows"], [["alpha"]])
        out = p3.sql("SELECT store FROM marker", symbol="FIXC")
        self.assertEqual(out["rows"], [["beta"]])
        self.assertEqual(out["provenance"]["path"], str(BETA))
        self.assertEqual(out["provenance"]["store"], "beta")
        # ISIN, BSE code and name resolve through the same registry (as a single store did before)
        self.assertEqual(p3.resolve_symbol("INE111A01011"), "FIXA")
        self.assertEqual(p3.resolve_symbol("522113"), "FIXC")
        self.assertEqual(p3.resolve_symbol("gamma works"), "FIXC")
        p3.reset_store()   # a later non-symbol call is not left on the previous call's store
        self.assertNotEqual(p3.db_path(), ALPHA)

    def test_a_pinned_store_wins_and_the_registry_is_not_searched(self) -> None:
        os.environ["REALITY_PILOT3_DB"] = str(ALPHA)
        self.assertFalse(p3.routing_enabled())
        self.assertEqual(p3.resolve_symbol("FIXA"), "FIXA")
        self.assertEqual(p3.db_path(), ALPHA)
        with self.assertRaises(core.DataError) as caught:
            p3.resolve_symbol("FIXC")   # only in beta, which the pin switches off
        self.assertEqual(caught.exception.code, "not_pilot3")

    def test_the_first_registered_store_wins_and_the_reply_says_also_held_in(self) -> None:
        self.assertEqual(p3.resolve_symbol("FIXB"), "FIXB")
        self.assertEqual(p3.db_path(), ALPHA)
        out = p3.sql("SELECT store FROM marker", symbol="FIXB")
        self.assertEqual(out["rows"], [["alpha"]])
        self.assertEqual(out["provenance"]["also_held_in"], [str(BETA)])

    def test_not_found_lists_the_stores_searched(self) -> None:
        with self.assertRaises(core.DataError) as caught:
            p3.resolve_symbol("NOSUCHCO")
        self.assertEqual(caught.exception.code, "not_pilot3")
        self.assertIn("alpha", caught.exception.message)
        self.assertIn("beta", caught.exception.message)
        self.assertIn(str(ALPHA), caught.exception.message)
        self.assertIn(str(BETA), caught.exception.message)

    def test_sql_without_a_symbol_or_store_lists_the_registered_stores(self) -> None:
        out = p3.sql("SELECT 1")
        self.assertEqual([row["name"] for row in out["stores"]], ["alpha", "beta"])
        self.assertNotIn("rows", out)
        self.assertIn("symbol=", out["hint"])

    def test_sql_store_by_name_or_path_queries_that_store(self) -> None:
        self.assertEqual(p3.sql("SELECT store FROM marker", store="beta")["rows"], [["beta"]])
        self.assertEqual(p3.sql("SELECT store FROM marker", store=str(ALPHA))["rows"], [["alpha"]])
        with self.assertRaises(core.DataError) as caught:
            p3.select_store("nosuchstore")
        self.assertEqual(caught.exception.code, "bad_store")

    def test_pinned_sql_still_works_without_a_symbol(self) -> None:
        os.environ["REALITY_PILOT3_DB"] = str(BETA)
        self.assertEqual(p3.sql("SELECT store FROM marker")["rows"], [["beta"]])


if __name__ == "__main__":
    unittest.main()
