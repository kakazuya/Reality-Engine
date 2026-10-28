"""Acceptance checks for the pilot-60 artifacts (golden-rule step 4).

    python -m unittest reality_engine.tests.test_pilot60

Skips when the generated artifacts are not present (they are built by the job).
"""
from __future__ import annotations

import csv
import json
import unittest
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "tasks" / "pilot60"
BANK = REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl"


class Pilot60Test(unittest.TestCase):
    def test_universe(self):
        path = OUT / "UNIVERSE.csv"
        if not path.is_file():
            self.skipTest("UNIVERSE.csv not built")
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        self.assertEqual(len(rows), 60)
        self.assertEqual(len({r["isin"] for r in rows}), 60)
        buckets = Counter(r["bucket"] for r in rows)
        self.assertEqual(buckets, {"LARGE": 10, "MID-SMALL": 20, "MICRO": 30})
        self.assertGreaterEqual(len({r["sector"] for r in rows}), 15)

    def test_instances_cover_the_bank(self):
        path = OUT / "INSTANCES.jsonl"
        if not path.is_file():
            self.skipTest("INSTANCES.jsonl not built")
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        bank = {json.loads(x)["mid"] for x in BANK.read_text(encoding="utf-8").splitlines()
                if x.strip()}
        covered = {r["parent_mid"] for r in rows}
        self.assertGreaterEqual(len(covered & bank) / len(bank), 0.90)
        stack = Counter((r["kind"], r.get("bucket")) for r in rows)
        self.assertEqual(stack[("stock", "LARGE")], stack[("stock", "MID-SMALL")])
        self.assertEqual(stack[("stock", "LARGE")], stack[("stock", "MICRO")])
        for row in rows:
            for key in ("mid", "parent_mid", "kind", "entities", "shift"):
                self.assertIn(key, row)

    def test_report_breakdowns(self):
        path = OUT / "REPORT.md"
        if not path.is_file():
            self.skipTest("REPORT.md not built")
        text = path.read_text(encoding="utf-8")
        for heading in ("By sector", "By family", "By entity level", "Bucket x family",
                        "PIT", "Latency", "Hand check"):
            self.assertIn(heading, text)


if __name__ == "__main__":
    unittest.main()
