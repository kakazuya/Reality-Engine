"""
Factor loader tests (temp DBs only — the live equity_intelligence.db is never
opened; NO network calls).

What these tests exist to prevent
--------------------------------
``factor_loaders`` is the *load* half of the point-in-time factor spine. The
failure mode it is built against is not a crash — it is a load that succeeds.
A loader that stamps ``as_of_date = date.today()`` on a 1960 commodity price
produces a spine that is internally consistent, passes ``lookahead_audit`` with
zero violations (vacuously), and is a pure fiction. So the assertions below
cluster around three things a green build must NOT do:

  1. read the *wrong table* (the Pink Sheet's ``sheet1.xml`` is the "Mismatch
     Details" diagnostic sheet, not "Monthly Prices") — a test that passes
     whether or not rels resolution works proves nothing, so the fixture
     carries a decoy sheet that is itself parseable and plausible;
  2. date content it cannot date — ``as_of_date`` must come FROM the file or
     not exist, never from the clock, and the "not exist" branch must be a
     refusal rather than a guess;
  3. manufacture a number — ``'\\ufffd'`` in a numeric column is a missing
     observation (NULL), not ``0.0``; the PPAC ONGC/OIL nomination *ceiling* is
     a different number for a different population of gas and is never
     substituted for the notified APM price.

Every case that needs a document builds one locally: the XLSX fixtures are
hand-built zips (``zipfile`` + ``xml.etree`` + ``sharedStrings.xml``, exactly
as the real workbook stores text), and the PPAC fixtures are string literals
reproducing the real OCR output. There is no HTTP in this file.

Temp-DB discipline
------------------
Same convention as ``test_factor_spine.py:36-48`` and the four other suites
that already carry it: ``REALITY_ENGINE_DB_PATH`` is redirected to a temp path
BEFORE any ``reality_engine`` import, because ``db/database.py:639`` builds
``db_manager = DatabaseManager()`` at module import time and ``__init__`` ->
``init_db()`` applies PRAGMAs and ``CREATE TABLE IF NOT EXISTS`` to
``config.DB_PATH``. A ``setUpModule`` stub runs too late — the import-time
write has already happened by then. The live file is 33 GB; this suite must
leave its mtime untouched.
"""

import ast
import os
import re
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import date
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

# --------------------------------------------------------------------------
# Singleton isolation — MUST precede every reality_engine import.
# See reality_engine/db/database.py:639 and test_factor_spine.py:36-48.
# --------------------------------------------------------------------------
_TEMP_DB_DIR = tempfile.mkdtemp(prefix="reality_factor_loaders_test_db_")
os.environ.setdefault(
    "REALITY_ENGINE_DB_PATH", str(Path(_TEMP_DB_DIR) / "singleton_isolated.db")
)

from reality_engine.db import database as _database_module
from reality_engine.db.database import DatabaseManager
from reality_engine.processing import factor_loaders
from reality_engine.processing.factor_spine import (
    ensure_factor_spine_schema,
    register_series,
    resolve_as_of,
)


# --------------------------------------------------------------------------
# Module-level live-DB guard
# --------------------------------------------------------------------------
class _ForbiddenLiveDB:
    """Stands in for the global db_manager. Any use is a test bug."""

    def session(self):  # pragma: no cover - only runs if a path regresses
        raise AssertionError(
            "factor loader test touched the default db_manager — the live "
            "reality_engine/data/equity_intelligence.db must never be opened"
        )


_REAL_DB_MANAGER = None


def setUpModule():
    global _REAL_DB_MANAGER
    _REAL_DB_MANAGER = _database_module.db_manager
    _database_module.db_manager = _ForbiddenLiveDB()


def tearDownModule():
    if _REAL_DB_MANAGER is not None:
        _database_module.db_manager = _REAL_DB_MANAGER


SOURCE_PATH = Path(factor_loaders.__file__)
SOURCE_TEXT = SOURCE_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Hand-built XLSX fixture
#
# Realistic in the ways that matter: text lives in ``xl/sharedStrings.xml`` and
# cells reference it with ``t="s"``; sheet *names* are bound to zip parts only
# through ``xl/_rels/workbook.xml.rels``. That last part is the whole point —
# workbook order is not zip order, and "Monthly Prices" is NOT sheet1.
# --------------------------------------------------------------------------
_DECOY_SHEET = "Mismatch Details"
_REAL_SHEET = "Monthly Prices"


def _col_letter(index: int) -> str:
    name = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _sheet_xml(grid, shared):
    """``grid`` is ``{row_number: {col_number: value}}``; ``None`` means no cell.

    Numbers are written as bare numeric cells; everything else becomes a
    ``sharedStrings.xml`` reference, which is what forces the reader through
    the shared-string table the way the live workbook does.
    """
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           "<sheetData>"]
    for rownum in sorted(grid):
        cells = grid[rownum]
        out.append(f'<row r="{rownum}">')
        for colnum in sorted(cells):
            value = cells[colnum]
            if value is None:
                continue
            ref = f"{_col_letter(colnum)}{rownum}"
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                idx = shared.setdefault(str(value), len(shared))
                out.append(f'<c r="{ref}" t="s"><v>{idx}</v></c>')
            else:
                out.append(f'<c r="{ref}"><v>{value}</v></c>')
        out.append("</row>")
    out.append("</sheetData></worksheet>")
    return "".join(out)


def _build_xlsx(monthly_grid, decoy_grid=None, description_rows=(1,)):
    """Return the bytes of a 3-sheet workbook.

    Sheet part order is deliberately INVERTED relative to meaning:
    ``sheet1.xml`` is the Mismatch Details diagnostic table, ``sheet2.xml`` is
    Monthly Prices, ``sheet3.xml`` is the legend. A parser that assumes
    "the first part is the data" gets plausible numbers from the wrong table.
    """
    if decoy_grid is None:
        decoy_grid = {
            1: {1: "Mismatch Details"},
            2: {1: "Unmatched identifiers between the two sources"},
            3: {1: "Identifier", 2: "Crude oil, average", 3: "Crude oil, Brent",
                4: "Natural gas, US"},
            4: {1: "1960M01", 2: 99.99, 3: 98.88, 4: 97.77},
            5: {1: "1960M02", 2: 96.66, 3: 95.55, 4: 94.44},
        }
    shared = {}
    parts = {
        "xl/worksheets/sheet1.xml": _sheet_xml(decoy_grid, shared),
        "xl/worksheets/sheet2.xml": _sheet_xml(monthly_grid, shared),
        "xl/worksheets/sheet3.xml": _sheet_xml(
            {r: {1: f"Legend line {r}"} for r in description_rows}, shared
        ),
    }
    sst = "".join(
        f"<si><t>{text}</t></si>" for text, _idx in sorted(shared.items(), key=lambda kv: kv[1])
    )
    parts["xl/sharedStrings.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared)}" uniqueCount="{len(shared)}">{sst}</sst>'
    )
    parts["xl/workbook.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        f'<sheet name="{_DECOY_SHEET}" sheetId="1" r:id="rId1"/>'
        f'<sheet name="{_REAL_SHEET}" sheetId="2" r:id="rId2"/>'
        '<sheet name="Description" sheetId="3" r:id="rId3"/>'
        "</sheets></workbook>"
    )
    rel_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    parts["xl/_rels/workbook.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{rel_type}" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{rel_type}" Target="worksheets/sheet2.xml"/>'
        f'<Relationship Id="rId3" Type="{rel_type}" Target="worksheets/sheet3.xml"/>'
        "</Relationships>"
    )
    parts["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
    )

    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Written in a deliberately shuffled order: zip order != sheet order.
        for name in sorted(parts):
            zf.writestr(name, parts[name])
    return buf.getvalue()


def _monthly_grid(updated_on, rows, headers=None, units=None):
    """The Pink Sheet 'Monthly Prices' shape: title, 'Updated on', labels, units.

    ``rows`` is ``[(period_label, {column_key: raw_cell_value})]``. Column 1 is
    the period label; data columns start at 2 in header order.
    """
    headers = headers or ["Crude oil, average", "Crude oil, Brent", "Natural gas, US"]
    units = units or ["($/bbl)", "($/bbl)", "($/mmbtu)"]
    grid = {
        1: {1: "CMO Historical Prices"},
        2: {1: "Monthly Prices"},
    }
    next_row = 3
    if updated_on is not None:
        grid[next_row] = {1: f"Updated on {updated_on}"}
        next_row += 1
    grid[next_row] = {1: "Data"}
    header_row = next_row + 1
    grid[header_row] = {i + 2: headers[i] for i in range(len(headers))}
    grid[header_row + 1] = {i + 2: units[i] for i in range(len(units))}
    r = header_row + 2
    for period, values in rows:
        grid[r] = {1: period}
        for i, key in enumerate(values):
            grid[r][i + 2] = values[key]
        r += 1
    return grid, header_row, r - 1


def _pink_sheet_xlsx(updated_on="September 02, 2026",
                     rows=(("1960M01", {"avg": 1.63, "brent": 1.63, "gas": 0.24}),
                           ("1960M02", {"avg": 1.7, "brent": 1.7, "gas": 0.24}),
                           ("2026M08", {"avg": 83.4, "brent": 82.1, "gas": 3.55}))):
    grid, _hdr, _last = _monthly_grid(updated_on, rows)
    return _build_xlsx(grid)


# --------------------------------------------------------------------------
# PPAC fixtures — the real OCR output of the one-page notification
# (image-only PDF: text layer 0 chars, rasterise@200dpi + OCR recovers it).
# The two price sentences are kept as separate constants so a test can delete
# the "notified as" one and prove the ceiling is never read in its place.
# --------------------------------------------------------------------------
_PPAC_NOTIFIED = (
    "The price is notified as USS 9.00/MMBTU (GCV basis) payable by the fertiliser\n"
    "plants, and the said price"
)
_PPAC_CEILING = (
    "shall be subject to a ceiling of USS 7.00/MMBTU for the gas sold by ONGC and\n"
    "OIL to the nomination fields of the consumers."
)
_PPAC_HEAD = (
    "GOVERNMENT OF INDIA\n"
    "MINISTRY OF PETROLEUM AND NATURAL GAS\n"
    "PETROLEUM PLANNING & ANALYSIS CELL (PPAC)\n"
    "\n"
    "NOTIFICATION\n"
    "Domestic Natural Gas Price for the month of September 2026\n"
    "\n"
    "Ref No: PPAC/APM/2026-27/GS/091                       Dated: 31.08.2026\n"
    "\n"
    "The Central Government has determined the price of domestic natural gas for\n"
    "the AP(M) period 1st September 2026 to 30th September 2026. "
)
# OCR artefacts, reproduced: the U+FFFD replacement char and an elided run.
_PPAC_TAIL = (
    "\n\n...the above price is inclusive of all taxes and levies.\n"
    "Sd/-\n"
    "(Director) \ufffd PPAC\n"
)


def _ppac_text(*, with_notified=True, with_ceiling=True):
    return (_PPAC_HEAD
            + (_PPAC_NOTIFIED + " " if with_notified else "")
            + (_PPAC_CEILING if with_ceiling else "")
            + _PPAC_TAIL)


_PPAC_OCR_TEXT = _ppac_text()


# --------------------------------------------------------------------------
# Case 1 — rels-based sheet resolution (with a decoy sheet1)
# --------------------------------------------------------------------------
class TestSheetResolution(unittest.TestCase):
    def _parse(self, payload):
        return factor_loaders.parse_world_bank_pink_sheet(payload, _REAL_SHEET)

    def test_picks_named_sheet_not_sheet1(self):
        parsed = self._parse(_pink_sheet_xlsx())
        self.assertEqual(parsed["status"], "ok", parsed.get("reason"))
        self.assertEqual(parsed["sheet_part"], "xl/worksheets/sheet2.xml")
        self.assertEqual(parsed["sheet_name"], _REAL_SHEET)
        # Workbook order really is decoy-first; the parser must not be reading
        # the first zip part it finds.
        self.assertEqual(
            [n for n, _p in _sheet_parts_of(_pink_sheet_xlsx())][0], _DECOY_SHEET
        )

    def test_decoy_sheet_would_produce_different_answers(self):
        """NON-VACUITY: the fixture must DISCRIMINATE, else case 1 is a no-op.

        Bypassing rels resolution (the naive "sheet1.xml is the data" bug) is
        run explicitly here. If this yielded the same numbers, the
        sheet_part/as_of_date/value assertions above would pass either way and
        the test would be worthless.
        """
        payload = _pink_sheet_xlsx()
        naive = lambda _zf, _name: "xl/worksheets/sheet1.xml"  # noqa: E731
        with mock.patch.object(factor_loaders, "resolve_sheet_part", naive):
            bypassed = self._parse(payload)
        correct = self._parse(payload)

        self.assertEqual(bypassed["sheet_part"], "xl/worksheets/sheet1.xml")
        self.assertNotEqual(bypassed["sheet_part"], correct["sheet_part"])
        # The decoy is *parseable and plausible* — a real row count, real
        # column matches — so only the values/date separate them.
        self.assertEqual(bypassed["status"], "ok", bypassed.get("reason"))
        self.assertTrue(bypassed["rows"])
        self.assertEqual(
            sorted(bypassed["column_map"]), sorted(correct["column_map"])
        )
        self.assertNotEqual(
            bypassed["rows"][0]["values"]["WB.CRUDE_OIL_AVG"],
            correct["rows"][0]["values"]["WB.CRUDE_OIL_AVG"],
        )
        # ...and the decoy carries no knowledge date at all, which is the
        # tell-tale of a silent wrong-table read.
        self.assertIsNone(bypassed["as_of_date"])
        self.assertEqual(correct["as_of_date"], "2026-09-02")

    def test_resolve_sheet_part_raises_on_unknown_name(self):
        with self.assertRaises(KeyError):
            with zipfile.ZipFile(__import__("io").BytesIO(_pink_sheet_xlsx())) as zf:
                factor_loaders.resolve_sheet_part(zf, "No Such Sheet")

    def test_column_map_and_units_come_from_the_named_sheet(self):
        parsed = self._parse(_pink_sheet_xlsx())
        self.assertEqual(
            sorted(parsed["column_map"]),
            ["WB.CRUDE_OIL_AVG", "WB.CRUDE_OIL_BRENT", "WB.NATURAL_GAS_US"],
        )
        # Units are read off the row BELOW the winning header (row 6 in the
        # live workbook), not from a stale empty map.
        self.assertEqual(parsed["units"], {
            "WB.CRUDE_OIL_AVG": "($/bbl)",
            "WB.CRUDE_OIL_BRENT": "($/bbl)",
            "WB.NATURAL_GAS_US": "($/mmbtu)",
        })


def _sheet_parts_of(payload):
    import io

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return factor_loaders.list_sheet_parts(zf)


# --------------------------------------------------------------------------
# Case 2 — as_of_date comes FROM THE FILE
# --------------------------------------------------------------------------
class TestAsOfDateFromFile(unittest.TestCase):
    def test_exact_date_is_read_from_the_updated_on_cell(self):
        parsed = factor_loaders.parse_world_bank_pink_sheet(
            _pink_sheet_xlsx(updated_on="September 02, 2026")
        )
        self.assertEqual(parsed["as_of_date"], "2026-09-02")

    def test_as_of_date_is_not_the_clock(self):
        parsed = factor_loaders.parse_world_bank_pink_sheet(
            _pink_sheet_xlsx(updated_on="September 02, 2026")
        )
        today = date.today().isoformat()
        self.assertNotEqual(parsed["as_of_date"], today)
        # A 1960-month observation is what makes the mistake lethal: stamping
        # today on it would be a ~66-year look-ahead.
        first = parsed["rows"][0]
        self.assertEqual(first["period"], "1960M01")
        self.assertEqual(first["period_start"], "1960-01-01")
        self.assertEqual(first["period_end"], "1960-01-31")
        self.assertNotEqual(first["period_start"], parsed["as_of_date"])

    def test_every_row_carries_the_single_publication_date(self):
        parsed = factor_loaders.parse_world_bank_pink_sheet(_pink_sheet_xlsx())
        obs = factor_loaders._world_bank_observations(parsed, None)
        by_key = dict(obs)
        self.assertEqual(sorted(by_key), ["WB.CRUDE_OIL_AVG", "WB.CRUDE_OIL_BRENT",
                                          "WB.NATURAL_GAS_US"])
        for key, rows in by_key.items():
            self.assertEqual({r["as_of_date"] for r in rows}, {"2026-09-02"}, key)

    def test_updated_on_variants_all_parse(self):
        for text, expected in (
            ("Updated on September 02, 2026", "2026-09-02"),
            ("Last Updated On 02 September 2026", "2026-09-02"),
            ("Data updated on 02.09.2026", "2026-09-02"),
            ("Updated: September 2nd, 2026", "2026-09-02"),
        ):
            with self.subTest(text=text):
                self.assertEqual(factor_loaders.parse_updated_on(text), expected)

    def test_publisher_omits_the_date_yields_none(self):
        self.assertIsNone(factor_loaders.parse_updated_on("Updated on soon"))
        self.assertIsNone(factor_loaders.parse_updated_on(None))


# --------------------------------------------------------------------------
# Case 4 — honest NULL: no recoverable date is a refusal, not a guess
# --------------------------------------------------------------------------
class TestHonestNullDate(unittest.TestCase):
    def test_workbook_without_updated_on_refuses_to_load(self):
        payload = _pink_sheet_xlsx(updated_on=None)
        parsed = factor_loaders.parse_world_bank_pink_sheet(payload)
        self.assertEqual(parsed["status"], "ok")   # values parsed fine...
        self.assertIsNone(parsed["as_of_date"])     # ...but the date is unknown
        # The contract is "no observations", spelled as an empty list (the
        # function's declared return type, and every other early return).
        self.assertEqual(factor_loaders._world_bank_observations(parsed, None), [])

        mgr, path = _mk_mgr()
        try:
            report = factor_loaders.load_series(
                mgr,
                series_keys=["WB.CRUDE_OIL_AVG"],
                sources=("world_bank",),
                dry_run=False,
                fetcher=lambda: parsed,
            )
        finally:
            pass
        try:
            self.assertEqual(report["n_written"], 0)
            self.assertEqual(report["series"], {})
            # A clean no-op must not report itself as a successful load. The
            # workbook parsed, nothing raised, and nothing was written — the
            # one combination the old final `else` stamped "ok" on. Asserted
            # here because this test already walks that exact path.
            self.assertEqual(report["status"], "no_usable_observations")
            self.assertEqual(report["errors"], [],
                             "this is the no-error flavour of 'loaded nothing'")
            self.assertEqual(report["n_registered"], 0)
            with _connect(path) as conn:
                n_obs = conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                    "AND name='factor_observation'"
                ).fetchone()[0]
            self.assertEqual(n_obs, 0, "a table was created for a dateless load")
        finally:
            _drop(mgr, path)

    def test_unparseable_dated_line_is_not_today(self):
        # The shared PPAC fixture DOES carry 'Dated: 31.08.2026', so it must be
        # stripped here: the point of this test is that a document with NO
        # recoverable date yields NO as_of_date. Fed the whole fixture it
        # asserted a contradiction — demanding None from a document that stated
        # a date — and the parser was right to return 2026-08-31.
        text = re.sub(r"[^\n]*Dated:[^\n]*", "", _ppac_text())
        self.assertNotIn("Dated:", text, "fixture repair did not apply")
        out = factor_loaders.parse_ppac_gas_notification(
            text, filename=""   # no 'Dated:' recovery, no epoch prefix
        )
        self.assertIsNone(out["as_of_date"])
        self.assertIsNone(out["as_of_date_source"])
        self.assertNotEqual(out["as_of_date"], date.today().isoformat())
        self.assertIn("no publication date recoverable", out["reason"])
        # The price still parses — a missing knowledge date does not destroy
        # the observation, it makes the write refuse.
        self.assertEqual(out["value"], 9.0)

    def test_blank_document_reports_a_status(self):
        out = factor_loaders.parse_ppac_gas_notification("", filename="")
        self.assertEqual(out["extraction_status"], factor_loaders.EXTRACTION_NONE)
        self.assertIsNone(out["value"])
        self.assertIsNone(out["as_of_date"])
        self.assertEqual(out["reason"], "no text recovered from the document")


# --------------------------------------------------------------------------
# Case 5 — junk in a numeric column is NULL, never 0.0
# --------------------------------------------------------------------------
class TestJunkCellsBecomeNull(unittest.TestCase):
    def test_sentinels_and_junk_become_none(self):
        junk = ["\ufffd", "...", "--", "-", "", "n/a", "NA", "null", "not-a-number"]
        rows = tuple((f"196{i}M01", {"avg": v, "brent": 1.0, "gas": 2.0})
                     for i, v in enumerate(junk))
        parsed = factor_loaders.parse_world_bank_pink_sheet(_pink_sheet_xlsx(rows=rows))
        self.assertEqual(parsed["status"], "ok", parsed.get("reason"))
        self.assertEqual(len(parsed["rows"]), len(junk))
        for row in parsed["rows"]:
            self.assertIsNone(row["values"]["WB.CRUDE_OIL_AVG"],
                              f"{row['period']}: junk became a value")
            self.assertEqual(row["n_null"], 1)
        # Zero is a *number*. A junk cell must never masquerade as one.
        self.assertNotIn(0.0, [r["values"]["WB.CRUDE_OIL_AVG"] for r in parsed["rows"]])

    def test_junk_does_not_raise_and_does_not_poison_neighbours(self):
        rows = (("1960M01", {"avg": "\ufffd", "brent": 1.63, "gas": 0.24}),)
        parsed = factor_loaders.parse_world_bank_pink_sheet(_pink_sheet_xlsx(rows=rows))
        self.assertEqual(parsed["rows"][0]["values"], {
            "WB.CRUDE_OIL_AVG": None,
            "WB.CRUDE_OIL_BRENT": 1.63,
            "WB.NATURAL_GAS_US": 0.24,
        })

    def test_to_float_contract(self):
        for junk in ("\ufffd", "...", "", None, "  "):
            self.assertIsNone(factor_loaders._to_float(junk))
        self.assertEqual(factor_loaders._to_float("1.63"), 1.63)
        self.assertEqual(factor_loaders._to_float(" 2 "), 2.0)


# --------------------------------------------------------------------------
# Case 3 — vintage chaining
# --------------------------------------------------------------------------
def _rows_for(as_of, value):
    """One-period Pink Sheet payload, published on ``as_of``, priced ``value``."""
    payload = _pink_sheet_xlsx(
        updated_on=as_of.strftime("%B %d, %Y"),
        rows=(("2020M01", {"avg": value, "brent": value, "gas": value}),),
    )
    parsed = factor_loaders.parse_world_bank_pink_sheet(payload)
    parsed["source_url"] = "https://example.invalid/pink.xlsx"
    return parsed


class TestVintageChaining(unittest.TestCase):
    def setUp(self):
        self.mgr, self.path = _mk_mgr()
        ensure_factor_spine_schema(self.mgr)
        key = "WB.CRUDE_OIL_AVG"
        register_series(self.mgr, [dict(factor_loaders._REGISTRY_BY_KEY[key])])
        self.key = key

    def tearDown(self):
        _drop(self.mgr, self.path)

    def _obs(self):
        with _connect(self.path) as conn:
            return conn.execute(
                "SELECT o.observation_id, o.vintage, o.value, o.as_of_date, "
                "o.is_latest, o.revision_of "
                "FROM factor_observation o JOIN factor_series s USING(series_id) "
                "WHERE s.factor_key = ? AND o.period_start = '2020-01-01' "
                "ORDER BY o.vintage",
                (self.key,),
            ).fetchall()

    def _load(self, as_of, value):
        parsed = _rows_for(as_of, value)
        return factor_loaders.load_series(
            self.mgr, series_keys=[self.key], sources=("world_bank",),
            dry_run=False, fetcher=lambda: parsed,
        )

    def test_restatement_chains_v2_and_flips_is_latest(self):
        self._load(datetime(2020, 2, 15), 1.63)
        first = self._obs()
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0][1], 1)
        self.assertEqual(first[0][4], 1, "v1 must be latest until a v2 exists")

        self._load(datetime(2020, 3, 15), 1.70)
        rows = self._obs()
        self.assertEqual(len(rows), 2, "a restatement must add a vintage, not overwrite")
        v1, v2 = rows
        self.assertEqual((v1[1], v1[2], v1[4]), (1, 1.63, 0))   # (vintage, value, is_latest)
        self.assertEqual((v2[1], v2[2], v2[4]), (2, 1.70, 1))
        self.assertEqual(v2[5], v1[0], "v2.revision_of must point at the v1 row")
        self.assertIsNone(v1[5])

    def test_identical_reload_is_not_a_new_vintage(self):
        self._load(datetime(2020, 2, 15), 1.63)
        before = self._obs()
        # Byte-identical payload: same as_of_date, same value.
        self._load(datetime(2020, 2, 15), 1.63)
        after = self._obs()
        self.assertEqual(len(after), 1, "an identical re-load must not create a vintage")
        self.assertEqual([r[:5] for r in before], [r[:5] for r in after])

        self._load(datetime(2020, 3, 15), 1.70)
        mid = self._obs()
        self.assertEqual(len(mid), 2)
        self._load(datetime(2020, 3, 15), 1.70)   # re-running is idempotent
        self.assertEqual(self._obs(), mid, "re-loading the current release changed state")

    def test_restated_value_is_invisible_before_it_was_published(self):
        """The point of the chain: as-of T never sees a later restatement."""
        self._load(datetime(2020, 2, 15), 1.63)
        self._load(datetime(2020, 3, 15), 1.70)
        early = resolve_as_of(self.mgr, self.key, "2020-02-20")
        self.assertEqual(early["status"], "ok")
        self.assertEqual(early["value_usable"], 1.63)
        self.assertEqual(early["vintage"], 1)
        late = resolve_as_of(self.mgr, self.key, "2020-03-20")
        self.assertEqual(late["value_usable"], 1.70)
        self.assertEqual(late["vintage"], 2)

    def test_dry_run_preview_reports_without_writing(self):
        parsed = _rows_for(datetime(2020, 2, 15), 1.63)
        report = factor_loaders.load_series(
            self.mgr, series_keys=[self.key], sources=("world_bank",),
            dry_run=True, fetcher=lambda: parsed,
        )
        self.assertEqual(report["status"], "dry_run")
        self.assertEqual(report["n_written"], 0)
        self.assertEqual(report["series"][self.key]["n_observations"], 1)
        self.assertEqual(self._obs(), [], "a dry run wrote rows anyway")


# --------------------------------------------------------------------------
# Case 6 — dry run touches no database
# --------------------------------------------------------------------------
class TestDryRunTouchesNothing(unittest.TestCase):
    def test_dry_run_creates_no_tables_and_calls_no_schema_writer(self):
        tmp = Path(tempfile.mkdtemp(prefix="fl_dryrun_")) / "never_touched.db"
        conn = sqlite3.connect(str(tmp))
        try:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0], 0
            )
            parsed = factor_loaders.parse_world_bank_pink_sheet(_pink_sheet_xlsx())
            self.assertEqual(parsed["status"], "ok")

            def _explode(*_a, **_k):  # pragma: no cover - must never run
                raise AssertionError("dry run touched the database")

            with mock.patch.object(factor_loaders, "ensure_factor_spine_schema", _explode), \
                 mock.patch.object(factor_loaders, "register_series", _explode), \
                 mock.patch.object(factor_loaders, "upsert_observations", _explode):
                report = factor_loaders.load_series(
                    conn,
                    sources=("world_bank",),
                    dry_run=True,
                    fetcher=lambda: parsed,
                )
            self.assertEqual(report["status"], "dry_run")
            self.assertEqual(report["n_written"], 0)
            self.assertEqual(report["n_registered"], 0)
            self.assertTrue(report["series"], "a dry run must still preview the plan")
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0], 0,
                "dry run created database objects",
            )
        finally:
            conn.close()
        self.assertEqual(tmp.stat().st_size, 0, "dry run wrote bytes to the DB file")

    def test_dry_run_is_the_default(self):
        import inspect

        sig = inspect.signature(factor_loaders.load_series)
        self.assertIs(sig.parameters["dry_run"].default, True)


# --------------------------------------------------------------------------
# Case 7 — AST guard: as_of_date is never assigned from the clock
# --------------------------------------------------------------------------
_CLOCK_CALLS = {
    "date.today", "datetime.now", "datetime.utcnow",
    "datetime.today", "datetime.fromtimestamp",
    "time.time", "time.strftime", "time.localtime",
    "time.gmtime", "time.monotonic",
}
# DOTTED STRINGS, not (obj, attr) tuples. _dotted() returns a string such as
# "date.today", so the previous tuple form compared a tuple against a string,
# was never equal, and every dotted clock call slipped past the guard: the
# headline test below passed because the scan could not fire, not because the
# module was clean.
_CLOCK_HELPERS = {"_today_iso", "_now_iso"}


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _is_asof_target(node):
    if isinstance(node, ast.Name):
        return node.id == "as_of_date"
    if isinstance(node, ast.Attribute):
        return node.attr == "as_of_date"
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value == "as_of_date"
    return False


def find_clock_asof_assignments(source):
    """Every assignment to an ``as_of_date`` target fed by a clock read.

    Deliberately syntactic and deliberately narrow: it inspects the *source*,
    not the runtime, so a new code path cannot smuggle ``date.today()`` into
    an ``as_of_date`` without this firing. It reports a hit when the assigned
    *value expression* contains a clock call (``_CLOCK_CALLS``) or one of the
    ``_CLOCK_HELPERS`` names.

    Known limit, stated rather than papered over: the scan sees only the
    assignment site, so a clock read *hidden inside a helper* is invisible to
    it. ``out["as_of_date"] = _epoch_date(int(ep.group(1)))``
    (``factor_loaders.py:1286``) is therefore NOT reported — ``_epoch_date``
    is a module function whose body calls ``datetime.fromtimestamp``, and that
    call is not part of the assigned value. The epoch integer is read from the
    *filename*, not the clock, and the row is labelled
    ``as_of_date_source = "filename_epoch_inferred"`` so a consumer can tell
    an inferred date from a publisher-stated one. Anything that wraps a clock
    in a helper must keep that labelling, or the guard will not catch it.
    """
    findings = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if value is None or not any(_is_asof_target(t) for t in targets):
            continue
        for sub in ast.walk(value):
            hit = None
            if isinstance(sub, ast.Call) and _dotted(sub.func) in _CLOCK_CALLS:
                hit = _dotted(sub.func)
            elif isinstance(sub, ast.Name) and sub.id in _CLOCK_HELPERS:
                hit = sub.id
            if hit:
                findings.append(f"line {node.lineno}: as_of_date assigned from {hit}()")
    return findings


class TestNoClockInAsOfDate(unittest.TestCase):
    def test_no_loader_path_assigns_as_of_date_from_the_clock(self):
        findings = find_clock_asof_assignments(SOURCE_TEXT)
        self.assertEqual(
            findings, [],
            "as_of_date is a property of the world, not of us:\n  "
            + "\n  ".join(findings),
        )

    def test_retrieved_at_is_the_only_clock_column(self):
        # The module may read the clock, but only for retrieved_at / refusal
        # guards. Assert the read happens at all, so the guard above is not
        # passing because the module was rewritten to be clock-free.
        self.assertRegex(SOURCE_TEXT, r"retrieved_at\s*=\s*_now_iso\(\)")

    def test_guard_is_not_vacuous_date_today(self):
        anchor = "    as_of_date = _find_as_of_date(rows)"
        self.assertIn(anchor, SOURCE_TEXT, "mutation anchor moved; guard proof is stale")
        mutant = SOURCE_TEXT.replace(
            anchor, "    as_of_date = date.today().isoformat()"
        )
        self.assertNotEqual(mutant, SOURCE_TEXT)
        findings = find_clock_asof_assignments(mutant)
        self.assertTrue(findings, "guard failed to catch an injected date.today()")
        self.assertIn("as_of_date", findings[0])

    def test_guard_is_not_vacuous_module_helper(self):
        anchor = "    as_of_date = _find_as_of_date(rows)"
        self.assertIn(anchor, SOURCE_TEXT, "mutation anchor moved; guard proof is stale")
        mutant = SOURCE_TEXT.replace(anchor, "    as_of_date = _today_iso()")
        findings = find_clock_asof_assignments(mutant)
        self.assertTrue(findings, "guard failed to catch an injected _today_iso()")
        self.assertIn("_today_iso", findings[0])

    def test_guard_detects_a_subscript_assignment(self):
        mutant = SOURCE_TEXT.replace(
            '    report: Dict[str, Any] = {\n        "status": "failed",',
            '    report["as_of_date"] = _today_iso()\n'
            '    report: Dict[str, Any] = {\n        "status": "failed",',
        )
        self.assertNotEqual(mutant, SOURCE_TEXT)
        self.assertTrue(find_clock_asof_assignments(mutant))

    def test_guard_limit_is_real_and_documented(self):
        """The guard is syntactic: it fires on a clock read that is part of the
        *assigned value*. That has a limit, and this pins both halves of it so
        the docstring cannot drift into promising coverage it lacks —
        inlined is caught, wrapped-in-a-helper is not.
        """
        anchor = 'out["as_of_date"] = _epoch_date(int(ep.group(1)))'
        self.assertIn(anchor, SOURCE_TEXT, "the documented example moved")

        # (a) The real source: the helper-wrapped call is NOT reported.
        self.assertEqual(find_clock_asof_assignments(SOURCE_TEXT), [])

        # (b) Same line with the clock inlined: reported.
        inlined = SOURCE_TEXT.replace(
            anchor,
            'out["as_of_date"] = datetime.fromtimestamp(0).date().isoformat()',
        )
        self.assertNotEqual(inlined, SOURCE_TEXT)
        self.assertTrue(find_clock_asof_assignments(inlined),
                        "an inlined clock read must still be caught")

        # (c) Same line still wrapped in a helper: not reported. This is the
        # documented blind spot, asserted so it stays documented.
        wrapped = SOURCE_TEXT.replace(anchor, 'out["as_of_date"] = _helper_clock()')
        self.assertNotEqual(wrapped, SOURCE_TEXT)
        self.assertEqual(find_clock_asof_assignments(wrapped), [])


# --------------------------------------------------------------------------
# Case 8 — PPAC ladder: notified price vs nomination-field ceiling
# --------------------------------------------------------------------------
class TestPpacLadder(unittest.TestCase):
    def test_price_anchors_on_notified_as(self):
        out = factor_loaders.parse_ppac_gas_notification(_PPAC_OCR_TEXT)
        self.assertEqual(out["value"], 9.00)
        self.assertEqual(out["unit"], "usd_per_mmbtu")

    def test_ceiling_is_parsed_separately_and_labelled(self):
        out = factor_loaders.parse_ppac_gas_notification(_PPAC_OCR_TEXT)
        self.assertEqual(out["ceiling_value"], 7.00)
        self.assertNotEqual(out["value"], out["ceiling_value"])

    def test_ceiling_is_never_substituted_for_the_notified_price(self):
        """Delete the 'notified as' sentence: the value must go NULL, not 7.00."""
        without_price = factor_loaders.parse_ppac_gas_notification(
            _ppac_text(with_notified=False)
        )
        self.assertIsNone(
            without_price["value"],
            "the ONGC/OIL nomination ceiling was read as the APM price",
        )
        self.assertEqual(without_price["ceiling_value"], 7.00)
        self.assertIn("ceiling", (without_price["reason"] or "").lower())

        # ...and the converse: a document with only the notified price must not
        # invent a ceiling.
        without_ceiling = factor_loaders.parse_ppac_gas_notification(
            _ppac_text(with_ceiling=False)
        )
        self.assertEqual(without_ceiling["value"], 9.00)
        self.assertIsNone(without_ceiling["ceiling_value"])

    def test_period_and_dated_line(self):
        out = factor_loaders.parse_ppac_gas_notification(
            _PPAC_OCR_TEXT, filename="1790573931_domestic_natural_gas_price_sep_2026.pdf"
        )
        self.assertEqual(out["period_start"], "2026-09-01")
        self.assertEqual(out["period_end"], "2026-09-30")
        self.assertEqual(out["as_of_date"], "2026-08-31")
        self.assertEqual(out["as_of_date_source"], "document_dated_line")
        self.assertNotEqual(out["as_of_date"], date.today().isoformat())

    def test_filename_epoch_is_labelled_as_inferred(self):
        out = factor_loaders.parse_ppac_gas_notification(
            "The price is notified as USS 9.00/MMBTU for the AP(M) period "
            "1st September 2026 to 30th September 2026.",
            filename="1790573931_domestic_natural_gas_price_sep_2026.pdf",
        )
        self.assertEqual(out["value"], 9.00)
        self.assertEqual(out["as_of_date_source"], "filename_epoch_inferred")
        self.assertEqual(
            out["as_of_date"],
            datetime.fromtimestamp(1790573931, tz=timezone.utc).date().isoformat(),
        )
        # Registered as a series-wide property, not per-row (design 1.4).
        entry = factor_loaders._REGISTRY_BY_KEY["IN.PPAC.GAS_APM"]
        self.assertEqual(entry["is_point_in_time"], 0)
        self.assertEqual(entry["availability_contract"], "pita_estimated")

    def test_extraction_ladder_reports_the_tier_that_worked(self):
        def _never(*_a, **_k):  # pragma: no cover - must not run
            raise AssertionError("OCR must not run when the text layer is usable")

        tier1 = factor_loaders.extract_pdf_text(
            b"%PDF-1.4 stub",
            text_fn=lambda _p: "x" * 200,
            ocr_fn=_never,
        )
        self.assertEqual(tier1["extraction_status"], factor_loaders.EXTRACTION_TEXT_LAYER)
        self.assertIsNone(tier1["reason"])

        def _boom(_p):
            raise RuntimeError("no text layer in this scan")

        tier2 = factor_loaders.extract_pdf_text(
            b"%PDF-1.4 stub",
            text_fn=_boom,
            ocr_fn=lambda _p: (_PPAC_OCR_TEXT, factor_loaders.EXTRACTION_OCR),
        )
        self.assertEqual(tier2["extraction_status"], factor_loaders.EXTRACTION_OCR)
        # _boom RAISES, so the audit trail must say the tier failed, not that
        # it ran. "tried and returned nothing" and "tried and blew up" are
        # different facts and are recorded differently.
        self.assertEqual(tier2["tiers_attempted"],
                         [factor_loaders.EXTRACTION_TEXT_LAYER + "(error)",
                          factor_loaders.EXTRACTION_OCR])
        self.assertIn("tier 1 unusable", tier2["reason"])
        self.assertIn("Dated: 31.08.2026", tier2["text"])

        # ...and the *other* tier-1 failure mode — a layer that came back
        # empty rather than raising — is recorded distinctly.
        tier2_empty = factor_loaders.extract_pdf_text(
            b"%PDF-1.4 stub",
            text_fn=lambda _p: "",
            ocr_fn=lambda _p: (_PPAC_OCR_TEXT, factor_loaders.EXTRACTION_OCR),
        )
        self.assertEqual(tier2_empty["extraction_status"],
                         factor_loaders.EXTRACTION_OCR)
        self.assertEqual(tier2_empty["tiers_attempted"],
                         [factor_loaders.EXTRACTION_TEXT_LAYER,
                          factor_loaders.EXTRACTION_OCR])
        self.assertIn("tier 1 unusable", tier2_empty["reason"])

    def test_extraction_ladder_gives_up_honestly(self):
        def _boom(_p):
            raise RuntimeError("nothing here")

        out = factor_loaders.extract_pdf_text(b"%PDF-1.4 stub", text_fn=_boom, ocr_fn=_boom)
        self.assertEqual(out["extraction_status"], factor_loaders.EXTRACTION_NONE)
        self.assertEqual(out["text"], "")
        self.assertIn("tier 2 failed", out["reason"])


# --------------------------------------------------------------------------
# Cases 9 + 10 — PPAC link de-duplication
# --------------------------------------------------------------------------
def _ppac_html(*urls):
    links = "".join(f'<li><a href="{u}">doc</a></li>' for u in urls)
    return f"<html><body><ul>{links}</ul></body></html>"


_BASE = "https://ppac.gov.in/page/prices"
_SEP_FILE = "/sites/default/files/1790573931_domestic_natural_gas_price_sep_2026.pdf"
_SEP_FILE2 = "/sites/default/files/1790574117_domestic_natural_gas_price_sep_2026.pdf"
_OCT_FILE = "/sites/default/files/1790574200_domestic_natural_gas_price_oct_2026.pdf"


class TestPpacLinkDedup(unittest.TestCase):
    def test_file_vs_fileDownload_collapse_to_one_document(self):
        docs = factor_loaders.discover_ppac_gas_documents(
            _ppac_html(
                f"{_BASE}?file={_SEP_FILE}",
                f"{_BASE}?fileDownload={_SEP_FILE}",
                f"{_BASE}?filedownload={_SEP_FILE}",
            )
        )
        self.assertEqual(len(docs), 1, f"expected one document, got {docs}")
        self.assertEqual(docs[0]["filename"],
                         "1790573931_domestic_natural_gas_price_sep_2026.pdf")
        self.assertEqual(docs[0]["epoch"], 1790573931)

    def test_earliest_epoch_wins_over_a_re_upload(self):
        """A re-upload must not date the content later than it became knowable."""
        docs = factor_loaders.discover_ppac_gas_documents(
            _ppac_html(
                f"{_BASE}?file={_SEP_FILE2}",   # re-upload, listed FIRST
                f"{_BASE}?fileDownload={_SEP_FILE}",   # original, listed second
            )
        )
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["epoch"], 1790573931)
        # The surviving URL must be the ORIGINAL upload's, not the re-upload's
        # that was listed first. _SEP_FILE2 shares no substring with _SEP_FILE,
        # so this fails if the later epoch ever wins.
        self.assertIn(_SEP_FILE, docs[0]["url"])
        self.assertLess(1790573931, 1790574117)

    def test_distinct_documents_are_not_over_collapsed(self):
        docs = factor_loaders.discover_ppac_gas_documents(
            _ppac_html(
                f"{_BASE}?file={_SEP_FILE}",
                f"{_BASE}?fileDownload={_SEP_FILE2}",
                f"{_BASE}?file={_OCT_FILE}",
            )
        )
        self.assertEqual(len(docs), 2)
        self.assertEqual(
            sorted(d["doc_key"] for d in docs),
            ["domestic_natural_gas_price_oct_2026.pdf",
             "domestic_natural_gas_price_sep_2026.pdf"],
        )
        self.assertTrue(all(d["epoch"] is not None for d in docs))
        self.assertTrue(all(d["epoch_date"] for d in docs))

    def test_entity_escaped_query_still_found(self):
        docs = factor_loaders.discover_ppac_gas_documents(
            _ppac_html(f"{_BASE}?file={_SEP_FILE}&amp;inline=1")
        )
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["epoch"], 1790573931)

    def test_soft_404_shell_and_noise_are_ignored(self):
        docs = factor_loaders.discover_ppac_gas_documents(
            _ppac_html(
                "https://ppac.gov.in/page/prices/domestic-natural-gas-price",
                f"{_BASE}?file=/sites/default/files/annual_report_2025.pdf",
                f"{_BASE}?file={_OCT_FILE}",
            )
        )
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["epoch"], 1790574200)

    def test_empty_page_is_not_an_exception(self):
        self.assertEqual(factor_loaders.discover_ppac_gas_documents(""), [])
        self.assertEqual(factor_loaders.discover_ppac_gas_documents("<html/>"), [])


# --------------------------------------------------------------------------
# Registry contract (defect d) + failure-record contract (module rule 3)
# --------------------------------------------------------------------------
class TestRegistryAndFailureContract(unittest.TestCase):
    def test_registry_validates_against_the_spine_contract(self):
        self.assertEqual(
            factor_loaders.validate_loader_registry(),
            len(factor_loaders.LOADER_SERIES_REGISTRY),
        )
        self.assertEqual(
            factor_loaders.LOADER_REGISTRY_VALIDATED,
            len(factor_loaders.LOADER_SERIES_REGISTRY),
        )

    def test_validator_rejects_a_broken_entry(self):
        broken = [dict(factor_loaders.LOADER_SERIES_REGISTRY[0], frequency="fortnightly")]
        with self.assertRaises(ValueError):
            factor_loaders.validate_loader_registry(broken)

    def test_every_matcher_names_a_registered_series(self):
        registered = set(factor_loaders.LOADER_SERIES_KEYS)
        for key, normalised in factor_loaders.WB_COLUMN_MATCHERS:
            self.assertIn(key, registered, normalised)
        self.assertEqual(set(factor_loaders.WB_SERIES_KEYS),
                         {k for k, _n in factor_loaders.WB_COLUMN_MATCHERS})

    def test_non_zip_payload_is_a_failure_record_not_an_exception(self):
        parsed = factor_loaders.parse_world_bank_pink_sheet(b"not a zip at all")
        self.assertEqual(parsed["status"], "failed")
        self.assertIsNone(parsed["as_of_date"])
        self.assertIn("not a readable xlsx", parsed["reason"])

    def test_layout_change_is_loud_not_silently_wrong(self):
        """A workbook with no matching column must fail, not pick something."""
        payload = _build_xlsx(
            {1: {1: "CMO Historical Prices"}, 2: {1: "Something Else Entirely"},
             3: {1: "1960M01", 2: 1.63, 3: 2.0}}
        )
        parsed = factor_loaders.parse_world_bank_pink_sheet(payload, _REAL_SHEET)
        self.assertEqual(parsed["status"], "failed")
        self.assertEqual(parsed["column_map"], {})
        self.assertIn("no series column matched", parsed["reason"])

    def test_public_api_is_deduplicated(self):
        self.assertEqual(
            len(factor_loaders.__all__), len(set(factor_loaders.__all__)),
            "duplicate entry in __all__",
        )
        for name in factor_loaders.__all__:
            self.assertTrue(hasattr(factor_loaders, name), name)
        self.assertNotIn("WB_COLUMN_MATCHERS_KEYS", dir(factor_loaders))


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _mk_mgr():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return DatabaseManager(Path(tmp.name)), tmp.name


def _drop(mgr, path):
    try:
        mgr.db_path.unlink(missing_ok=True)
    except Exception:  # pragma: no cover - best-effort cleanup
        pass


class _Conn:
    """Open a raw sqlite3 connection to ``path`` (temp files only)."""

    def __init__(self, path):
        self.conn = sqlite3.connect(path)

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        self.conn.close()
        return False


def _connect(path):
    return _Conn(path)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
