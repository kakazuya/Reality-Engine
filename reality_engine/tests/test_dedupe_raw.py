"""Tests for raw dedupe (sha256 groups + hard links) and ``raw_store.store_bytes``.

Everything runs on workspace temp dirs: no live raw root, no live database, no network.
Each test owns one root under ``.tmp/dedupe-tests`` and creates its own sha index.
"""
from __future__ import annotations

import errno
import os
import unittest
import uuid
from pathlib import Path
from unittest import mock

from reality_engine import raw_store
from reality_engine.scripts import dedupe_raw

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / ".tmp" / "dedupe-tests"


def _root(name: str) -> Path:
    """Workspace temp dir (the OS temp dir is not writable under the DSH sandbox)."""
    path = BASE / f"{name}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _blob(tag: str, size: int = 4096) -> bytes:
    """Deterministic content that looks like a PDF and is well over the 1 KB floor."""
    body = (tag.encode() + b"-payload-") * (size // max(len(tag), 8) + 1)
    return b"%PDF-1.7\n" + body[:size]


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class DedupePlanTest(unittest.TestCase):
    def test_identical_files_are_grouped(self):
        root = _root("plan")
        first = _write(root / "bse" / "01_results.pdf", _blob("standalone"))
        second = _write(root / "bse" / "02_results.pdf", _blob("standalone"))
        _write(root / "bse" / "unique.pdf", _blob("unique"))

        planned = dedupe_raw.plan([root])

        self.assertEqual(len(planned["groups"]), 1)
        group = planned["groups"][0]
        self.assertEqual(sorted([group["canonical"]] + group["duplicates"]),
                         sorted([str(first), str(second)]))
        self.assertEqual(group["size"], first.stat().st_size)

    def test_small_files_are_skipped(self):
        root = _root("small")
        _write(root / "a.txt", b"tiny")
        _write(root / "b.txt", b"tiny")

        planned = dedupe_raw.plan([root])

        self.assertEqual(planned["groups"], [])
        self.assertEqual(planned["folders"][str(root)]["small_skipped"], 2)


class DedupeApplyTest(unittest.TestCase):
    def test_apply_links_and_both_paths_read_the_same_bytes(self):
        root = _root("apply")
        canonical = _write(root / "a" / "results.pdf", _blob("revision"))
        duplicate = _write(root / "b" / "results.pdf", _blob("revision"))
        os.utime(canonical, (1_000_000, 1_000_000))     # unambiguous oldest copy

        planned = dedupe_raw.plan([root])
        self.assertEqual(planned["groups"][0]["canonical"], str(canonical))
        dedupe_raw.apply_plan(planned)
        report = dedupe_raw.summarise(planned, applied=True)

        self.assertTrue(canonical.exists() and duplicate.exists(), "every path still opens")
        self.assertEqual(duplicate.read_bytes(), canonical.read_bytes())
        self.assertEqual(os.stat(duplicate).st_nlink, 2, "one file, two names")
        self.assertEqual(report["totals"]["links_made"], 1)
        self.assertEqual(report["totals"]["bytes_saved"], canonical.stat().st_size)
        self.assertEqual(report["folders"][str(root)]["bytes_saved"], canonical.stat().st_size)

    def test_single_copy_is_never_removed(self):
        root = _root("single")
        unique = _write(root / "unique.pdf", _blob("only-copy"))
        duplicate = _write(root / "dup.pdf", _blob("only-copy"))

        planned = dedupe_raw.plan([root])
        dedupe_raw.apply_plan(planned)

        self.assertEqual(unique.read_bytes(), _blob("only-copy"))
        self.assertEqual(duplicate.read_bytes(), _blob("only-copy"))
        self.assertEqual(os.stat(unique).st_nlink, 2)

    def test_changed_file_between_plan_and_apply_is_not_linked(self):
        root = _root("changed")
        canonical = _write(root / "a.pdf", _blob("quarterly"))
        duplicate = _write(root / "b.pdf", _blob("quarterly"))
        os.utime(canonical, (1_000_000, 1_000_000))
        planned = dedupe_raw.plan([root])

        replacement = _blob("revised-after-the-scan")
        duplicate.write_bytes(replacement)             # a file changed between plan and apply
        dedupe_raw.apply_plan(planned)

        self.assertEqual(duplicate.read_bytes(), replacement, "the changed file keeps its bytes")
        self.assertEqual(os.stat(duplicate).st_nlink, 1)
        self.assertIn({"path": str(duplicate), "reason": "changed_since_scan"}, planned["skipped"])

    def test_cross_volume_pair_is_skipped(self):
        root = _root("external")
        canonical = _write(root / "a.pdf", _blob("deck"))
        duplicate = _write(root / "b.pdf", _blob("deck"))
        os.utime(canonical, (1_000_000, 1_000_000))
        planned = dedupe_raw.plan([root])

        error = OSError(errno.EXDEV, "Invalid cross-device link")
        with mock.patch.object(os, "link", side_effect=error):
            dedupe_raw.apply_plan(planned)

        self.assertEqual(duplicate.read_bytes(), _blob("deck"))
        self.assertEqual(os.stat(duplicate).st_nlink, 1)
        self.assertIn({"path": str(duplicate), "reason": "cross_volume"}, planned["skipped"])
        self.assertEqual(dedupe_raw.summarise(planned, applied=True)["totals"]["links_made"], 0)


class StoreBytesTest(unittest.TestCase):
    def test_store_bytes_reuses_an_existing_sha(self):
        root = _root("store")
        index = root / "_dedupe" / "sha_index.db"
        data = _blob("deck-copy")

        first = raw_store.store_bytes(root / "nse" / "deck.pdf", data, index_path=index)
        second = raw_store.store_bytes(root / "bse" / "deck.pdf", data, index_path=index)

        self.assertEqual(second.read_bytes(), data)
        self.assertTrue(raw_store.same_file(first, second), "the second write is a hard link")
        self.assertEqual(os.stat(second).st_nlink, 2)

    def test_store_bytes_writes_distinct_content_and_indexes_it(self):
        root = _root("store-distinct")
        index = root / "_dedupe" / "sha_index.db"

        first = raw_store.store_bytes(root / "one.pdf", _blob("first"), index_path=index)
        second = raw_store.store_bytes(root / "two.pdf", _blob("second"), index_path=index)

        self.assertFalse(raw_store.same_file(first, second))
        self.assertEqual(first.read_bytes(), _blob("first"))
        self.assertEqual(second.read_bytes(), _blob("second"))
        self.assertEqual(list(root.rglob("*.part")), [], "the .part file never survives")


if __name__ == "__main__":
    unittest.main()
