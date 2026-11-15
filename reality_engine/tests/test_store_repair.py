"""T-218: part stamps, the stale list, and the repair gate (a result that loses a row is put back).

Fixture stores only: tiny sqlite files under ``.tmp`` and a fake step runner that edits the store, so no build,
no network and no child process runs here.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from reality_engine.pilot3 import part_stamp
from reality_engine.scripts import store_repair


@pytest.fixture()
def tmp_path():
    path = Path(".tmp") / "pytest" / uuid.uuid4().hex[:8]
    path.mkdir(parents=True, exist_ok=False)
    return path


def _store(root: Path, name: str = "c01", guidance_rows: int = 2) -> dict:
    base = root / name
    base.mkdir(parents=True)
    profile = base / f"{name}_profile.json"
    profile.write_text(json.dumps({"name": name, "companies": [{"symbol": "AAA"}]}), encoding="utf-8")
    conn = sqlite3.connect(base / f"{name}.db")
    conn.execute("CREATE TABLE guidance (id INTEGER PRIMARY KEY, symbol TEXT, metric TEXT, target_period TEXT, "
                 "low REAL, high REAL, unit TEXT, doc_key TEXT, page INTEGER, quote TEXT, entity TEXT)")
    conn.executemany("INSERT INTO guidance (symbol, metric, target_period, low, high, doc_key, page, quote) "
                     "VALUES ('AAA', 'revenue_growth', 'FY27', ?, ?, 'd1', 1, 'q')",
                     [(10 + i, 12 + i) for i in range(guidance_rows)])
    conn.commit()
    conn.close()
    return store_repair.find_stores(root)[0]


def _runner(sql: str | None, rc: int = 0):
    def run(part, cmd, log, ram_gb, timeout_s):
        db = Path(cmd[cmd.index("--out") + 1])
        if sql:
            conn = sqlite3.connect(db)
            conn.execute(sql)
            part_stamp.write(conn, part, 0.1, head="test")
            conn.close()
        return {"part": part, "seconds": 0.1, "rc": rc, "peak_rss_mb": 1.0, "ram_stop": False, "timed_out": False,
                "tail5": "boom" if rc else ""}
    return run


def _count(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM guidance").fetchone()[0]
    finally:
        conn.close()


def test_every_part_lists_files_that_exist_and_hash_is_stable():
    assert set(part_stamp.PART_FILES) == set(part_stamp.ORDER) == set(part_stamp.UPSTREAM) == set(part_stamp.PART_TABLES)
    for part in part_stamp.ORDER:
        assert part_stamp.part_files(part)
        assert part_stamp.code_hash(part) == part_stamp.code_hash(part)
        assert all(part_stamp.ORDER.index(up) < part_stamp.ORDER.index(part) for up in part_stamp.UPSTREAM[part])


def test_a_shared_file_is_hashed_by_the_functions_the_part_uses():
    module = b"A = 1\n\ndef used():\n    return 1\n\ndef other():\n    return 2\n"
    same = part_stamp._names_source(module, ["used", "A"])
    assert same == part_stamp._names_source(module.replace(b"return 2", b"return 3"), ["used", "A"])
    assert same != part_stamp._names_source(module.replace(b"return 1", b"return 9"), ["used", "A"])
    assert b"<missing>" in part_stamp._names_source(module, ["gone"])


def test_table_hash_ignores_row_order_and_dropped_columns(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.execute("CREATE TABLE t (a, b, preferred_from)")
    conn.executemany("INSERT INTO t VALUES (?,?,?)", [(1, 2, None), (3, 4, None)])
    first = part_stamp.table_hash(conn, "t"), part_stamp.table_hash(conn, "t-preferred*")
    conn.execute("DELETE FROM t")
    conn.executemany("INSERT INTO t VALUES (?,?,?)", [(3, 4, "x"), (1, 2, None)])
    assert part_stamp.table_hash(conn, "t") != first[0] and part_stamp.table_hash(conn, "t-preferred*") == first[1]
    assert part_stamp.table_hash(conn, "nothing") == "absent"
    conn.close()


def test_stale_reasons_and_a_same_rows_rerun_leaves_readers_fresh(tmp_path):
    conn = sqlite3.connect(tmp_path / "s.db")
    conn.execute("CREATE TABLE kpi_series (symbol, metric, value)")
    assert set(part_stamp.stale(conn)) == set(part_stamp.RECIPE)          # a store built before stamps
    for part in part_stamp.RECIPE:
        part_stamp.write(conn, part, 1.0, head="test")
    assert part_stamp.stale(conn) == {}
    hashes = {p: part_stamp.code_hash(p) for p in part_stamp.ORDER}
    hashes["kpi"] = "different"
    stale = part_stamp.stale(conn, hashes)
    assert stale["kpi"] == "code changed" and stale["segments"] == "after kpi" and stale["guidance"] == "after segments"
    assert "stores" not in stale and "transcripts" not in stale
    part_stamp.write(conn, "segments", 1.0, head="test")                 # re-run, same rows: nothing downstream
    assert part_stamp.stale(conn) == {}
    conn.execute("INSERT INTO kpi_series VALUES ('AAA', 'order_book', 5)")
    part_stamp.write(conn, "segments", 1.0, head="test")                 # re-run, new rows: its readers are behind
    stale = part_stamp.stale(conn)
    assert stale["guidance"] == "segments output changed" and stale["checks"].startswith("after ")
    assert "ratios" not in stale
    conn.close()


def test_baseline_stamps_only_missing_parts_with_the_commits_code(tmp_path):
    conn = sqlite3.connect(tmp_path / "s.db")
    part_stamp.write(conn, "kpi", 1.0, head="test")
    done = part_stamp.baseline(conn, "HEAD", 1_700_000_000, {"profile": "p", "docs_collect": "d"})
    stamps = part_stamp.read(conn)
    assert "kpi" not in done and set(done) == set(part_stamp.RECIPE) - {"kpi"}
    assert stamps["stores"]["git_head"] == "baseline:HEAD" and stamps["profile"]["out_hash"] == "p"
    assert stamps["registry"]["inputs"] == {"profile": "p", "docs_collect": "d"}
    conn.close()


def test_a_part_whose_table_an_earlier_part_rewrote_runs_again():
    assert part_stamp.rewrites("stores", "preferred") and part_stamp.rewrites("kpi", "segments")
    assert part_stamp.rewrites("comparatives", "preferred")
    assert not part_stamp.rewrites("preferred", "stores") and not part_stamp.rewrites("stores", "ratios")


def test_dependants_follow_build_order():
    assert part_stamp.dependants(["kpi"]) == ["kpi", "segments", "guidance", "checks"]
    assert part_stamp.dependants(["guidance"]) == ["guidance", "checks"]
    assert part_stamp.dependants(["stores"])[:4] == ["stores", "comparatives", "preferred", "ratios"]


def test_an_unforced_part_with_unchanged_inputs_is_skipped(tmp_path):
    store = _store(tmp_path)
    conn = sqlite3.connect(store["db"])
    for part in part_stamp.RECIPE:
        part_stamp.write(conn, part, 1.0, head="test")
    conn.close()
    ran = []

    def runner(part, cmd, log, ram_gb, timeout_s):
        ran.append(part)
        conn = sqlite3.connect(store["db"])
        part_stamp.write(conn, part, 0.1, head="test")
        conn.close()
        return {"part": part, "seconds": 0.1, "rc": 0, "ram_stop": False, "timed_out": False}

    record = store_repair.repair_store(store, ["guidance", "checks"], "r1", runner=runner, forced={"guidance"})
    assert ran == ["guidance"] and record["outcome"] == "repaired"
    assert record["steps"][1] == {"part": "checks", "skipped": "inputs unchanged"}


def test_repair_keeps_a_result_that_only_adds_rows(tmp_path):
    store = _store(tmp_path)
    add = ("INSERT INTO guidance (symbol, metric, target_period, low, high, doc_key, page, quote) "
           "VALUES ('AAA', 'ebitda_margin', 'FY27', 20, 22, 'd2', 3, 'q')")
    record = store_repair.repair_store(store, ["guidance"], "r1", runner=_runner(add))
    assert record["outcome"] == "repaired" and record["diff"]["guidance"]["added"] == 1
    assert _count(store["db"]) == 3
    assert not (store["dir"] / "repair.lock").exists()


def test_repair_refuses_a_lost_row_restores_the_store_and_accept_puts_it_in(tmp_path):
    store = _store(tmp_path)
    record = store_repair.repair_store(store, ["guidance"], "r1", runner=_runner("DELETE FROM guidance WHERE low=10"))
    assert record["outcome"] == "refused" and record["losses"][0]["table"] == "guidance"
    assert _count(store["db"]) == 2                                        # the store is as it was
    assert (store["dir"] / "repair" / "r1" / "after.db").is_file()
    accepted = store_repair.accept(store, "r1")
    assert accepted["outcome"] == "repaired" and _count(store["db"]) == 1


def test_approve_loss_keeps_the_result_and_a_failed_part_restores(tmp_path):
    store = _store(tmp_path)
    kept = store_repair.repair_store(store, ["guidance"], "r1", approve_loss=True,
                                     runner=_runner("DELETE FROM guidance WHERE low=10"))
    assert kept["outcome"] == "repaired" and _count(store["db"]) == 1
    failed = store_repair.repair_store(store, ["guidance"], "r2", runner=_runner("DELETE FROM guidance", rc=1))
    assert failed["outcome"] == "failed" and _count(store["db"]) == 1


def test_a_locked_store_is_not_touched(tmp_path):
    store = _store(tmp_path)
    (store["dir"] / "repair.lock").write_text("", encoding="utf-8")
    assert store_repair.repair_store(store, ["guidance"], "r1", runner=_runner(None))["outcome"] == "locked"


def test_notes_roundtrip_and_index(tmp_path):
    note = store_repair.note_add({"part": "stores", "symptom": "no shareholding rows", "store": "c07",
                                  "question": "What is the promoter holding?"}, tmp_path)
    assert note["id"] == "R-001" and note["status"] == "open"
    store_repair.note_set("R-001", {"status": "fixed", "fix": "symbol fallback"}, ["c07"], "r1", tmp_path)
    saved = store_repair.read_notes(tmp_path)[0]
    assert saved["status"] == "fixed" and saved["repaired"] == ["c07"] and saved["runs"] == ["r1"]
    index = (tmp_path / "INDEX.md").read_text(encoding="utf-8")
    assert "R-001" in index and "symbol fallback" in index and "promoter holding" in index
