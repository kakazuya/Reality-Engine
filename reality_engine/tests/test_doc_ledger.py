"""Shivam 26 Nov 2026: capped start files keep a full, never-trimmed ledger."""
from __future__ import annotations

import subprocess

from reality_engine.scripts import doc_ledger as dl


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_staged_change_goes_to_the_ledger_and_full_rulings_keep_removed_wording(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "T")
    rules = tmp_path / "tasks" / "RULINGS.md"
    rules.parent.mkdir()
    rules.write_text("# R\n## A\n- Old long wording of a rule with every detail.\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "first")
    rules.write_text("# R\n## A\n- Short rule.\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    written = dl.staged(tmp_path)
    ledger = dl.ledger_path("tasks/RULINGS.md", tmp_path).read_text(encoding="utf-8")
    assert written and "-- Old long wording of a rule with every detail." in ledger and "+- Short rule." in ledger
    _git(tmp_path, "commit", "-qm", "second")
    full = dl.full_rulings(tmp_path).read_text(encoding="utf-8")
    assert "- Short rule." in full and "Old long wording of a rule with every detail." in full
