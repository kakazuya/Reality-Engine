"""T-242: the Sonnet settle worker exits on a stale reading or at its per-window cap, and its claude call is bare."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
import sys
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from reality_engine.scripts import sonnet_settle as ss

RESET = "2026-11-25T18:53:00+05:30"
OLD_RESET = "2026-11-25T13:53:00+05:30"
DDL = """create table observation (symbol text, doc_key text, page integer, status text, record_type text,
         entity_scope text, observation_id integer, measure text, printed_label text, printed_axis text,
         value_text text, value real, unit text, scale real, period text, basis text, segment text,
         series_title text, status_reason text)"""


@pytest.fixture()
def work_dir() -> Iterator[Path]:
    """A plain mkdir temp dir (pytest's tmp_path makes 0o700 dirs, unlistable under the Windows sandbox token)."""
    p = Path(tempfile.gettempdir()) / f"sonnet_settle_{uuid.uuid4().hex}"
    p.mkdir()
    yield p
    shutil.rmtree(p, ignore_errors=True)


def _usage(cfg: Path, five: int, age_s: int = 0) -> None:
    saved = (dt.datetime.now() - dt.timedelta(seconds=age_s)).isoformat("T", "seconds")
    (cfg / "usage_status.json").write_text(json.dumps({
        "_saved_at": saved,
        "rate_limits": {"five_hour": {"used_percentage": five, "resets_at": RESET},
                        "seven_day": {"used_percentage": 10}}}), encoding="utf-8")


def _obs_db(work: Path) -> Path:
    db = work / "obs.db"
    con = sqlite3.connect(db)
    con.execute(DDL)
    con.execute("insert into observation (symbol, doc_key, page, status, record_type, entity_scope, "
                "observation_id, measure, value) values ('A', 'dk1', 1, 'unverified', 'number', 'company', "
                "7, 'revenue', 1234.0)")
    con.commit()
    con.close()
    return db


def _main(work: Path, monkeypatch: pytest.MonkeyPatch, five: int = 6, age_s: int = 0,
          windows: tuple[str, ...] = ()) -> tuple[int, int]:
    """Run main() against a fake usage file, one fake page and a fake claude; (exit code, claude calls)."""
    cfg = work / "cfg"
    cfg.mkdir()
    _usage(cfg, five, age_s)
    monkeypatch.setattr(ss, "CFG", str(cfg))
    (work / "out").mkdir()
    if windows:
        (work / "out" / "runs.jsonl").write_text("".join(
            json.dumps({"ts": "x", "five_hour_resets_at": w, "cost": None}) + "\n" for w in windows),
            encoding="utf-8")
    monkeypatch.setattr(ss, "store_index", lambda root, cache: {"dk1": "store.db"})
    monkeypatch.setattr(ss.obs, "page_text_of", lambda store, key, page: "Revenue 1,234 (Rs Cr)")
    fired: list[Path] = []
    monkeypatch.setattr(ss, "run_claude", lambda prompt, log, cwd: fired.append(cwd) or ("[]", {"cost": 0.01}))
    monkeypatch.setattr(sys, "argv", ["sonnet_settle", "--db", str(_obs_db(work)),
                                      "--stores-root", str(work), "--out", str(work / "out")])
    return ss.main(), len(fired)


def test_stale_reading_exits_without_a_run(work_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rc, fired = _main(work_dir, monkeypatch, age_s=ss.STALE_S + 60)
    assert rc == 0 and fired == 0


def test_seventy_five_percent_exits_without_a_run(work_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rc, fired = _main(work_dir, monkeypatch, five=ss.LIMIT_5H)
    assert rc == 0 and fired == 0


def test_run_cap_counts_only_the_current_window(work_dir: Path) -> None:
    (work_dir / "runs.jsonl").write_text(
        "".join(json.dumps({"ts": "x", "five_hour_resets_at": RESET, "cost": None}) + "\n" for _ in range(24))
        + "".join(json.dumps({"ts": "x", "five_hour_resets_at": OLD_RESET, "cost": None}) + "\n" for _ in range(30)),
        encoding="utf-8")
    assert ss.runs_in_window(work_dir, RESET) == 24
    assert ss.runs_in_window(work_dir, OLD_RESET) == 30
    assert ss.runs_in_window(work_dir, "2026-11-26T00:00:00+05:30") == 0


def test_cap_stops_the_process(work_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rc, fired = _main(work_dir, monkeypatch, windows=(RESET,) * ss.MAX_RUNS_PER_WINDOW)
    assert rc == 0 and fired == 0


def test_previous_window_runs_do_not_block(work_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rc, fired = _main(work_dir, monkeypatch, windows=(OLD_RESET,) * 30)
    assert rc == 0 and fired == 1
    last = json.loads((work_dir / "out" / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert last["five_hour_resets_at"] == RESET and last["cost"] == 0.01
    assert (work_dir / "out" / "bare").is_dir()


def test_build_cmd_is_bare() -> None:
    cmd = ss.build_cmd()
    assert cmd[0] == "claude" and "-p" in cmd
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert "--disallowedTools" not in cmd
