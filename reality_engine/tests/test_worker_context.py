"""The generated worker context pack must stay small enough to read once."""
from __future__ import annotations

import unittest
from pathlib import Path

from reality_engine.scripts import build_worker_context

REPO = Path(__file__).resolve().parents[2]
LIMIT = 20_000


class WorkerContextPackSizeTests(unittest.TestCase):
    def test_built_pack_is_at_most_20000_bytes(self) -> None:
        out = REPO / ".tmp" / "worker-context-size-test"
        out.mkdir(parents=True, exist_ok=True)
        stats = build_worker_context.build(repo_root=REPO, out_dir=out)
        size = Path(stats["path"]).stat().st_size
        text = Path(stats["path"]).read_text(encoding="utf-8")
        self.assertLessEqual(size, LIMIT, f"worker context pack is {size} bytes; limit {LIMIT}")
        self.assertEqual(size, stats["bytes"])
        self.assertFalse(stats["over_budget"])
        self.assertIn("Do not survey the repo", text)
        self.assertIn("tasks/STATE.md", text)


if __name__ == "__main__":
    unittest.main()
