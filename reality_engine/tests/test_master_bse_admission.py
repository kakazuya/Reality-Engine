"""Exchange-aware delisting sweep + BSE-only admission provenance.

Regression cover for the swept-ETF bug: the liveness set used to be built from
NSE EQUITY_L alone, so every scrip NSE's equity list does not carry — ETFs,
index funds, non-EQ series — was flagged delisted on every sync. Liveness is now
the union of NSE EQUITY_L, the whole BSE active scrip master (all groups and
segments) and the currently-active exempt-synthetic set; a scrip is deactivated
only when absent from all of them.

Also covers the BSE-only admission path: rows admitted with
``listing_source='BSE_ONLY'`` / ``is_screenable=0`` and the guards that keep
duplicate ISINs, non-equity segments, group 'Z' shells and ticker collisions out
of the universe.

Runs against a temp-file SQLite DB with injected exchange fakes — no network,
no production writes.
"""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.ingestion.master_sync import MasterSyncManager

# ISINs are synthetic-but-real-shaped (never INE_AUTO*, which the legacy
# liveness carve-out already protects and which cannot save a real-ISIN ETF).
_ETF_DUAL_ISIN = "INE0ITI12345"      # ETF in NSE-bhavcopy + BSE master
_ETF_BSEABSENT_ISIN = "INE0BEE12345"  # ETF the BSE scrip master does not carry
_GHOST_ISIN = "INE0GHOST001"          # operating scrip, absent from every source

_ALPHA_ISIN = "INE001A01001"   # NSE + BSE
_BETA_ISIN = "INE002A01002"    # NSE only
_EPSILON_ISIN = "INE005A01005"  # already in master, BSE-corroborated
_AIRFLOA_ISIN = "INE010A01010"  # BSE-only, admitted
_MICRO_ISIN = "INE011A01011"    # BSE-only, admitted, no market cap
_ZED_ISIN = "INE012A01012"      # BSE-only, group 'Z'
_PREF_ISIN = "INE013A01013"     # BSE-only, non-equity segment
_NOISIN_BSE_CODE = "500014"     # BSE-only, no ISIN at all
_CLONE_ISIN = "INE015A01015"    # BSE-only, ticker collides with NSE 'AAA'

_NSE_COLUMNS = ["SYMBOL", "NAME OF COMPANY", "SERIES", "ISIN NUMBER"]


def _nse_rows():
    return [
        ["AAA", "Alpha Ltd", "EQ", _ALPHA_ISIN],
        ["BBB", "Beta Ltd", "EQ", _BETA_ISIN],
    ]


def _bse_row(bse_code, symbol, name, isin, group="B", segment="Equity",
             status="Active", mktcap="4000.0", industry=None):
    return {
        "bse_code": bse_code,
        "bse_name": name,
        "Status": status,
        "bse_group": group,
        "isin": isin,
        "INDUSTRY": industry,
        "bse_symbol": symbol,
        "Segment": segment,
        "bse_mktcap_cr": mktcap,
    }


def _bse_rows():
    return [
        _bse_row("500001", "AAA", "Alpha Ltd", _ALPHA_ISIN, group="A", mktcap="153319.95"),
        _bse_row("500005", "EEE", "Epsilon Ltd", _EPSILON_ISIN, mktcap="500"),
        _bse_row("500010", "AIRFLOA", "Airfloa Rail Technology Ltd", _AIRFLOA_ISIN,
                 group="M", mktcap="4000"),
        _bse_row("500011", "MICROCO", "Micro Co Ltd", _MICRO_ISIN, group="X", mktcap="nan"),
        _bse_row("500012", "ZEDCO", "Zed Co Ltd", _ZED_ISIN, group="Z", mktcap="900"),
        _bse_row("500013", "PREFCO", "Pref Co Ltd", _PREF_ISIN, segment="PreferenceShares"),
        _bse_row("500014", "NOISIN", "No Isin Ltd", None, mktcap="900"),
        _bse_row("500015", "AAA", "Cloned Alpha Ltd", _CLONE_ISIN),
    ]


class _FakeNSE:
    """Minimal NSEClient stand-in (equity master + index constituents)."""

    def __init__(self, rows=None, constituents=None):
        self._rows = _nse_rows() if rows is None else rows
        self._constituents = constituents or {}

    def fetch_equity_master(self) -> pd.DataFrame:
        return pd.DataFrame(self._rows, columns=_NSE_COLUMNS)

    def fetch_nifty_index_constituents(self, index_name: str = "NIFTY200") -> pd.DataFrame:
        return self._constituents.get(index_name.upper(), pd.DataFrame())


class _FakeBSE:
    """Minimal BSEClient stand-in, mirroring fetch_scrip_master's str() coercion.

    The real client stringifies every object column, so missing cells arrive as
    the literal string 'nan' — the fake must reproduce that to exercise the
    NaN-safe cleaning in master_sync.
    """

    def __init__(self, rows=None):
        self._rows = _bse_rows() if rows is None else rows

    def fetch_scrip_master(self) -> pd.DataFrame:
        df = pd.DataFrame(self._rows)
        for col in df.columns:
            df[col] = df[col].map(lambda v: str(v).strip())
        return df


def _mk_sync(td, nse_rows=None, bse_rows=None):
    """Temp-DB manager + repository + sync wired to injected exchange fakes."""
    mgr = DatabaseManager(db_path=Path(td) / "t.db")
    repo = Repository(manager=mgr)
    sync = MasterSyncManager()
    sync.repo = repo
    sync.nse = _FakeNSE(nse_rows)
    sync.bse = _FakeBSE(bse_rows)
    return sync, repo, mgr


def _seed(repo, records):
    return repo.upsert_master_companies(records)


def _seed_epsilon(repo):
    """A pre-existing master row whose ISIN the BSE master corroborates."""
    return _seed(repo, [{
        "isin": _EPSILON_ISIN, "nse_symbol": "EEE", "company_name": "Epsilon Ltd",
        "market_cap_tier": "MICRO", "is_active": 1,
    }])


def _rows_by_isin(repo, active_only=False):
    return {c["isin"]: c for c in repo.get_all_companies(active_only=active_only)}


class TestExchangeAwareDelistingSweep(unittest.TestCase):
    """(a) ETF-class scrips survive the sweep; only truly-absent ISINs die."""

    def test_etf_class_scrips_survive_two_syncs(self):
        with tempfile.TemporaryDirectory() as td:
            sync, repo, mgr = _mk_sync(td)
            _seed(repo, [{
                "isin": _ETF_DUAL_ISIN, "nse_symbol": "ITIETF",
                "company_name": "ITI ETF", "market_cap_tier": "MICRO", "is_active": 1,
            }, {
                "isin": _ETF_BSEABSENT_ISIN, "nse_symbol": "SNXT30BEES",
                "company_name": "Nippon India ETF Nifty 30 Bees",
                "market_cap_tier": "MICRO", "is_active": 1,
            }, {
                "isin": _GHOST_ISIN, "nse_symbol": "GHOST",
                "company_name": "Ghost Ltd", "market_cap_tier": "MICRO", "is_active": 1,
            }])

            res = sync.sync_all()

            # The ghost is absent from NSE EQ, BSE and is not a synthetic
            # instrument -> the sweep still flags it.
            self.assertEqual(res["delisted_flagged"], 1)
            rows = _rows_by_isin(repo)
            self.assertEqual(rows[_ETF_DUAL_ISIN]["is_active"], 1,
                             "ETF present in the BSE active master must stay active")
            self.assertEqual(rows[_ETF_BSEABSENT_ISIN]["is_active"], 1,
                             "real-ISIN ETF absent from BSE must stay active (exempt synthetic)")
            self.assertEqual(rows[_GHOST_ISIN]["is_active"], 0)

            # Second sync: nothing new to add, nothing re-flagged, ETFs still alive.
            res2 = sync.sync_all()
            self.assertEqual(res2["delisted_flagged"], 0)
            self.assertEqual(res2["bse_only_added"], 0)
            rows2 = _rows_by_isin(repo)
            self.assertEqual(rows2[_ETF_DUAL_ISIN]["is_active"], 1)
            self.assertEqual(rows2[_ETF_BSEABSENT_ISIN]["is_active"], 1)

            # And the sweep never resurrects a delisted ghost on re-sync.
            self.assertEqual(rows2[_GHOST_ISIN]["is_active"], 0)

    def test_delisted_bse_scrip_is_deactivated_when_it_leaves_the_bse_master(self):
        """A BSE-only row dropped from the BSE active feed is genuinely gone."""
        with tempfile.TemporaryDirectory() as td:
            sync, repo, mgr = _mk_sync(td)
            sync.sync_all()
            self.assertEqual(_rows_by_isin(repo)[_AIRFLOA_ISIN]["is_active"], 1)

            # BSE feed no longer carries AIRFLOA; NSE never carried it either.
            sync.bse = _FakeBSE([r for r in _bse_rows() if r["isin"] != _AIRFLOA_ISIN])
            res = sync.sync_all()
            self.assertEqual(res["delisted_flagged"], 1)
            self.assertEqual(_rows_by_isin(repo)[_AIRFLOA_ISIN]["is_active"], 0)

    def test_bse_outage_never_flags_delistings(self):
        """An unread BSE feed is not evidence of absence: sweep nothing, add nothing."""
        with tempfile.TemporaryDirectory() as td:
            sync, repo, mgr = _mk_sync(td)
            _seed(repo, [{
                "isin": _GHOST_ISIN, "nse_symbol": "GHOST", "company_name": "Ghost Ltd",
                "market_cap_tier": "MICRO", "is_active": 1,
            }])

            sync.bse = _FakeBSE([])  # fetch fails -> master_sync continues with no BSE rows
            res = sync.sync_all()

            self.assertEqual(res["delisted_flagged"], 0)
            self.assertEqual(res["bse_only_added"], 0)
            self.assertEqual(_rows_by_isin(repo)[_GHOST_ISIN]["is_active"], 1)

            # Recovery: with the BSE master readable again the genuinely-absent
            # scrip is flagged on the next successful sync.
            sync.bse = _FakeBSE()
            res2 = sync.sync_all()
            self.assertEqual(res2["delisted_flagged"], 1)
            self.assertEqual(_rows_by_isin(repo)[_GHOST_ISIN]["is_active"], 0)


class TestBseOnlyAdmission(unittest.TestCase):
    """(b) BSE-only actives are admitted as unscreenable, fully-keyed rows."""

    def _sync_with_capture(self, td):
        sync, repo, mgr = _mk_sync(td)
        _seed_epsilon(repo)
        captured = []
        original = repo.upsert_master_companies

        def spy(records):
            captured.extend(records)
            return original(records)

        repo.upsert_master_companies = spy
        try:
            res = sync.sync_all()
        finally:
            repo.upsert_master_companies = original
        return res, repo, mgr, captured

    def test_bse_only_row_is_admitted_unscreenable_with_full_record(self):
        with tempfile.TemporaryDirectory() as td:
            res, repo, mgr, captured = self._sync_with_capture(td)

            self.assertEqual(res["bse_only_added"], 2)
            self.assertIn("provenance_updated", res)
            self.assertIn("bse_only_skipped", res)

            admitted = {r["isin"]: r for r in captured if r["isin"] == _AIRFLOA_ISIN}
            self.assertEqual(len(admitted), 1)
            record = admitted[_AIRFLOA_ISIN]

            # Every emitted record must carry the whole key set (upsert reads
            # r["is_nifty200"] etc. unconditionally).
            required = {
                "isin", "nse_symbol", "bse_code", "company_name", "industry", "sector",
                "market_cap_tier", "is_fno_eligible", "is_nifty50", "is_nifty100",
                "is_nifty200", "is_nifty500", "is_active", "listing_source", "is_screenable",
            }
            self.assertTrue(required.issubset(record.keys()),
                            f"missing keys: {required - set(record)}")

            self.assertEqual(record["nse_symbol"], "AIRFLOA")
            self.assertEqual(record["bse_code"], "500010")
            self.assertEqual(record["company_name"], "Airfloa Rail Technology Ltd")
            self.assertEqual(record["market_cap_tier"], "SMALL")  # 4000 cr
            self.assertEqual(record["industry"], None)  # BSE INDUSTRY is NaN
            self.assertEqual(record["sector"], None)
            self.assertEqual(record["is_active"], 1)
            self.assertEqual(record["listing_source"], "BSE_ONLY")
            self.assertEqual(record["is_screenable"], 0)
            for flag in ("is_fno_eligible", "is_nifty50", "is_nifty100", "is_nifty200", "is_nifty500"):
                self.assertEqual(record[flag], 0)

            stored = _rows_by_isin(repo)[_AIRFLOA_ISIN]
            self.assertEqual(stored["is_active"], 1)
            self.assertEqual(stored["listing_source"], "BSE_ONLY")
            self.assertEqual(stored["is_screenable"], 0)
            self.assertEqual(stored["market_cap_tier"], "SMALL")
            self.assertIsNone(stored["industry"])

            # No market cap on the BSE row -> MICRO, still admitted.
            micro = _rows_by_isin(repo)[_MICRO_ISIN]
            self.assertEqual(micro["market_cap_tier"], "MICRO")
            self.assertEqual(micro["is_screenable"], 0)

    def test_nse_provenance_dual_vs_nse(self):
        with tempfile.TemporaryDirectory() as td:
            res, repo, mgr, _captured = self._sync_with_capture(td)
            rows = _rows_by_isin(repo)
            self.assertEqual(rows[_ALPHA_ISIN]["listing_source"], "DUAL")
            self.assertEqual(rows[_BETA_ISIN]["listing_source"], "NSE")
            self.assertEqual(rows[_ALPHA_ISIN]["is_screenable"], 1)
            self.assertEqual(rows[_BETA_ISIN]["is_screenable"], 1)
            self.assertGreaterEqual(res["provenance_updated"], 2)

            counts = repo.count_universe_by_provenance()
            self.assertEqual(counts, {"NSE": 2, "DUAL": 1, "BSE_ONLY": 2, "screenable": 3})

    def test_screenable_filter_is_opt_in(self):
        with tempfile.TemporaryDirectory() as td:
            _res, repo, mgr, _captured = self._sync_with_capture(td)

            default = repo.get_all_companies(active_only=True)
            explicit_default = repo.get_all_companies(active_only=True, screenable_only=False)
            filtered = repo.get_all_companies(active_only=True, screenable_only=True)

            self.assertEqual(default, explicit_default)
            self.assertEqual({c["isin"] for c in default} - {c["isin"] for c in filtered},
                             {_AIRFLOA_ISIN, _MICRO_ISIN})
            self.assertTrue(all(c["is_screenable"] == 1 for c in filtered))
            # Legacy rows (no provenance written) remain screenable.
            self.assertIn(_EPSILON_ISIN, {c["isin"] for c in filtered})

            self.assertEqual(repo.set_screenable(_AIRFLOA_ISIN, 1), 1)
            self.assertIn(_AIRFLOA_ISIN,
                          {c["isin"] for c in repo.get_all_companies(screenable_only=True)})
            self.assertEqual(repo.set_screenable(_AIRFLOA_ISIN, 0), 1)
            self.assertNotIn(_AIRFLOA_ISIN,
                             {c["isin"] for c in repo.get_all_companies(screenable_only=True)})


class TestBseOnlyGuards(unittest.TestCase):
    """(c/d) Duplicate ISINs, collisions, group 'Z' and junk rows are skipped."""

    def test_skip_counters_and_no_admission_for_guarded_rows(self):
        with tempfile.TemporaryDirectory() as td:
            sync, repo, mgr = _mk_sync(td)
            _seed_epsilon(repo)
            res = sync.sync_all()

            # AAA and EEE are already known; the cloned BSE row collides with NSE
            # 'AAA'; ZEDCO is group 'Z'; PREFCO is a preference share; 500014
            # carries no ISIN at all.
            self.assertEqual(res["bse_only_skipped"],
                             {"known": 2, "collision": 1, "group": 2, "no_isin": 1})

            rows = _rows_by_isin(repo)
            for isin in (_ZED_ISIN, _PREF_ISIN, _CLONE_ISIN):
                self.assertNotIn(isin, rows, f"{isin} must never enter the universe")

            # The colliding BSE row did not steal the NSE ticker.
            alpha = rows[_ALPHA_ISIN]
            self.assertEqual(alpha["nse_symbol"], "AAA")
            self.assertEqual(alpha["bse_code"], "500001")
            self.assertEqual(alpha["listing_source"], "DUAL")

    def test_group_z_row_already_tracked_is_live_but_never_admitted(self):
        """Liveness stays permissive even where admission is strict.

        A group-'Z' scrip the BSE master still carries counts as alive (so it is
        never swept as delisted), yet it must never be admitted with provenance.
        """
        with tempfile.TemporaryDirectory() as td:
            sync, repo, mgr = _mk_sync(td)
            _seed(repo, [{
                "isin": _ZED_ISIN, "nse_symbol": "ZEDCO", "company_name": "Zed Co Ltd",
                "market_cap_tier": "MICRO", "is_active": 1,
            }])
            res = sync.sync_all()

            rows = _rows_by_isin(repo)
            self.assertEqual(res["delisted_flagged"], 0)
            self.assertEqual(rows[_ZED_ISIN]["is_active"], 1)
            # 'known' (not 'group'): both ZEDCO and the BSE row for AAA are
            # already tracked, so the guard order keeps them out of admission.
            self.assertEqual(res["bse_only_skipped"]["known"], 2)
            self.assertIsNone(rows[_ZED_ISIN]["listing_source"])


class TestIdempotentSync(unittest.TestCase):
    """(f) A repeat sync adds nothing and reports nothing delisted."""

    def test_second_sync_adds_zero_and_delists_zero(self):
        with tempfile.TemporaryDirectory() as td:
            sync, repo, mgr = _mk_sync(td)
            _seed_epsilon(repo)
            first = sync.sync_all()
            self.assertEqual(first["bse_only_added"], 2)

            with mgr.session() as conn:
                before = conn.execute("SELECT COUNT(*) FROM master_companies").fetchone()[0]

            second = sync.sync_all()

            self.assertEqual(second["bse_only_added"], 0)
            self.assertEqual(second["delisted_flagged"], 0)
            self.assertEqual(second["provenance_updated"], 0)
            with mgr.session() as conn:
                after = conn.execute("SELECT COUNT(*) FROM master_companies").fetchone()[0]
            self.assertEqual(before, after)

            counts = repo.count_universe_by_provenance()
            self.assertEqual(counts["BSE_ONLY"], 2)
            self.assertEqual(counts["screenable"], 3)


if __name__ == "__main__":
    unittest.main()
