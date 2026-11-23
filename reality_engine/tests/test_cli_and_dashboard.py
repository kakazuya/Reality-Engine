"""
Tests for Reality Engine CLI Interface and Streamlit Dashboard Module.
"""

from __future__ import annotations

import unittest
import sys
import io
import argparse
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reality_engine.cli import (
    cmd_seed_ontologies,
    cmd_screen,
    cmd_inspect_stock,
    cmd_run_daily_alpha,
    cmd_trace_causal_chain,
    cmd_simulate_macro_shock,
    cmd_panic_monitor,
    cmd_process_inbox,
    cmd_search_concall,
)
from reality_engine.ui import dashboard


class TestCLIAndDashboard(unittest.TestCase):
    """Verifies all CLI subcommands and dashboard helper functions execute without error."""

    def test_01_dashboard_module_load(self):
        """Verifies dashboard module and cached queries load cleanly."""
        self.assertIsNotNone(dashboard)
        dates = dashboard.get_available_dates()
        self.assertIsInstance(dates, list)
        self.assertGreater(len(dates), 0)

        symbols = dashboard.get_all_stock_symbols()
        self.assertIsInstance(symbols, list)
        self.assertGreater(len(symbols), 0)

    def test_02_cli_seed_ontologies(self):
        """Verifies seed-ontologies CLI command executes cleanly."""
        args = argparse.Namespace()
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            cmd_seed_ontologies(args)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("SEEDING ONTOLOGIES", output)
        self.assertIn("definitions seeded", output)

    def test_03_cli_screen(self):
        """Verifies screen CLI command in both standard and crisis mode."""
        args = argparse.Namespace(universe="nifty200", top=5, crisis=False, date="2026-08-14")
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            cmd_screen(args)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("Running Quantitative Multi-Factor Screener", output)
        # Structural contract: a ranked table carrying the documented columns was printed.
        # Deliberately NOT asserting that a particular symbol appears -- the ranks, the
        # solvency gate and the universe all move as the live database is refreshed, so
        # "HAL in output" pinned fixture data rather than behaviour (it broke on 2026-09-20
        # when HAL fell out of the top 5 for 2026-08-14).
        for column in ("composite_rank", "symbol", "composite_score", "delivery_spike_ratio"):
            self.assertIn(column, output, f"screener table missing column {column}")
        ranked_rows = [
            line for line in output.splitlines()
            if line.strip() and line.strip()[0].isdigit() and line.strip().split()[0].isdigit()
        ]
        self.assertGreater(len(ranked_rows), 0, "screener printed no ranked rows")

        # Crisis mode
        args_crisis = argparse.Namespace(universe="nifty200", top=5, crisis=True, date="2026-08-14")
        buf_c = io.StringIO()
        try:
            sys.stdout = buf_c
            cmd_screen(args_crisis)
        finally:
            sys.stdout = old_stdout

        output_c = buf_c.getvalue()
        self.assertIn("PANIC MONITOR STATUS", output_c)

    def test_04_cli_inspect_stock(self):
        """Verifies inspect-stock CLI command displays complete dossier."""
        args = argparse.Namespace(symbol="HAL")
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            cmd_inspect_stock(args)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("STOCK INTELLIGENCE DOSSIER: HAL", output)
        self.assertIn("ISIN:", output)
        self.assertIn("LATEST TECHNICAL & DELIVERY PROFILE", output)
        self.assertIn("DISTILLED COMPANY PARAMETERS", output)

    def test_05_cli_run_daily_alpha(self):
        """Verifies run-daily-alpha CLI orchestrates theses and report export."""
        args = argparse.Namespace(universe="nifty200", top=5, top_theses=2, date="2026-08-14")
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            cmd_run_daily_alpha(args)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("SYNTHESIZING DAILY ALPHA REPORT", output)
        self.assertIn("HIGH-CONVICTION ALPHA THESES", output)
        self.assertIn("REPORTS EXPORTED SUCCESSFULLY", output)

    def test_06_cli_trace_causal_chain(self):
        """Verifies trace-causal-chain walks multi-hop transmission graph."""
        args = argparse.Namespace(node="UNION_BUDGET_2026_RAIL_CAPEX", max_hops=3, impact="ALL")
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            cmd_trace_causal_chain(args)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("CAUSAL TRANSMISSION TRACE", output)
        self.assertIn("TITAGARH", output)

    def test_07_cli_simulate_macro_shock(self):
        """Verifies simulate-macro-shock outputs beneficiaries and victims."""
        args = argparse.Namespace(shock="UNION_BUDGET_2026_RAIL_CAPEX", sector="ALL")
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            cmd_simulate_macro_shock(args)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("MACRO SHOCK PROPAGATION SIMULATION", output)
        self.assertIn("BENEFICIARIES", output)

    def test_08_cli_panic_monitor(self):
        """Verifies monitor-panic evaluates drawdown triggers."""
        args = argparse.Namespace(date="2026-08-14")
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            cmd_panic_monitor(args)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("PANIC MONITOR STATUS", output)

    def test_09_cli_process_inbox(self):
        """Verifies process-inbox scans drop-in folder."""
        args = argparse.Namespace(inbox_dir=None)
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            cmd_process_inbox(args)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("PROCESSING LOCAL INBOX", output)

    def test_10_cli_search_concall(self):
        """Verifies search-concall executes hybrid search over transcripts."""
        args = argparse.Namespace(query="order book capex", symbol="HAL", top_k=2)
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            cmd_search_concall(args)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("HYBRID CONCALL SEARCH", output)
        self.assertIn("HAL", output)


if __name__ == "__main__":
    unittest.main()
