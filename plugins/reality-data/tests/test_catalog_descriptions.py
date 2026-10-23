"""Contract tests for plugins/reality-data/catalog_descriptions.yaml.

Run from the repo root:
    python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"

The databases are gitignored and live in the main checkout. Override the data
directory or snapshot path with REALITY_DATA_DIR / REALITY_SNAPSHOT when they
move.
"""
import os
import sqlite3
import unittest
from pathlib import Path

import duckdb
import yaml

PLUGIN_DIR = Path(__file__).resolve().parents[1]
CATALOG_PATH = PLUGIN_DIR / "catalog_descriptions.yaml"

DEFAULT_DATA_DIR = Path(
    r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data"
)
DATA_DIR = Path(os.environ.get("REALITY_DATA_DIR", DEFAULT_DATA_DIR))
SNAPSHOT = Path(
    os.environ.get(
        "REALITY_SNAPSHOT",
        DATA_DIR / "snapshots" / "truth_2026-10-19.duckdb",
    )
)

# db_key -> SQLite file. truth_duckdb is handled separately.
SQLITE_DBS = {
    "equity_intelligence": "equity_intelligence.db",
    "ar_facts": "ar_facts.db",
    "deck_figures": "deck_figures.db",
    "concall_facts": "concall_facts.db",
    "results_xbrl": "results_xbrl.db",
    "bse_announcements": "bse_announcements.db",
}
DB_KEYS = set(SQLITE_DBS) | {"truth_duckdb"}

# FTS5 shadow tables plus SQLite internals are not catalog entries. The FTS
# virtual tables themselves ARE catalogued.
FTS_SHADOW_SUFFIXES = ("_data", "_idx", "_docsize", "_config", "_content")


def _is_internal(name: str) -> bool:
    return name.startswith("sqlite_") or name.endswith(FTS_SHADOW_SUFFIXES)


def _columns(con, table):
    rows = con.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {row[1] for row in rows}


def sqlite_tables(path: Path):
    """Non-internal table and view names, read-only."""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        names = [
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') ORDER BY name"
            )
        ]
        return [n for n in names if not _is_internal(n)]
    finally:
        con.close()


def duckdb_tables(path: Path):
    """Non-internal tables/views in DuckDB's main schema, read-only."""
    con = duckdb.connect(str(path), read_only=True)
    try:
        rows = con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()
        return [r[0] for r in rows if not _is_internal(r[0])]
    finally:
        con.close()


class CatalogDescriptionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CATALOG_PATH.exists():
            raise AssertionError(f"missing catalog: {CATALOG_PATH}")
        cls.catalog = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))

    def test_catalog_parses_and_has_expected_shape(self):
        self.assertIsInstance(self.catalog, dict)
        self.assertEqual(set(self.catalog), DB_KEYS)
        for db_key, entry in self.catalog.items():
            with self.subTest(db=db_key):
                self.assertIsInstance(entry.get("description"), str)
                self.assertTrue(entry["description"].strip())
                self.assertIsInstance(entry.get("tables"), dict)
                for table, meta in entry["tables"].items():
                    with self.subTest(db=db_key, table=table):
                        self.assertIsInstance(meta.get("description"), str)
                        self.assertTrue(meta["description"].strip())
                        keys = meta.get("key_columns")
                        self.assertIsInstance(keys, list)
                        self.assertTrue(keys, "key_columns must be a non-empty list")
                        self.assertTrue(all(isinstance(k, str) and k for k in keys))
                        self.assertIsInstance(meta.get("notes"), str)
                        self.assertTrue(meta["notes"].strip())

    def test_every_table_and_view_is_covered(self):
        actual = {}
        for db_key, filename in SQLITE_DBS.items():
            path = DATA_DIR / filename
            self.assertTrue(path.exists(), f"database not found: {path}")
            actual[db_key] = set(sqlite_tables(path))
        self.assertTrue(SNAPSHOT.exists(), f"snapshot not found: {SNAPSHOT}")
        actual["truth_duckdb"] = set(duckdb_tables(SNAPSHOT))

        for db_key, tables in actual.items():
            documented = set(self.catalog[db_key]["tables"])
            missing = sorted(tables - documented)
            stale = sorted(documented - tables)
            with self.subTest(db=db_key):
                self.assertEqual(missing, [], f"undocumented tables in {db_key}")
                self.assertEqual(stale, [], f"stale catalog entries in {db_key}")

    def test_key_columns_exist_in_each_table(self):
        failures = []

        def check(con, db_key, table, keys, describe):
            cols = describe(table)
            for key in keys:
                if key == "rowid":
                    continue
                if key not in cols:
                    failures.append(f"{db_key}.{table}: key column {key!r} not in {sorted(cols)}")

        for db_key, filename in SQLITE_DBS.items():
            path = DATA_DIR / filename
            self.assertTrue(path.exists(), f"database not found: {path}")
            con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            try:
                for table, meta in self.catalog[db_key]["tables"].items():
                    check(con, db_key, table, meta["key_columns"], lambda t: _columns(con, t))
            finally:
                con.close()

        con = duckdb.connect(str(SNAPSHOT), read_only=True)
        try:
            def duck_columns(table):
                rows = con.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='main' AND table_name=?",
                    [table],
                ).fetchall()
                return {r[0] for r in rows}

            for table, meta in self.catalog["truth_duckdb"]["tables"].items():
                check(con, "truth_duckdb", table, meta["key_columns"], duck_columns)
        finally:
            con.close()

        self.assertEqual(failures, [], "bad key_columns:\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
