"""Summarise a HeadlessProbe JSONL log: the acceptance numbers for one run.

    python -m reality_engine.tools.textrec.probe.summarise <probe.jsonl> [--json]

Counts, for the interval the probe covered:
  * samples and their spacing (the brief asks for at least every 200 ms);
  * visible top-level windows owned by textrec/conhost/cmd/powershell/pwsh/python;
  * focus changes to those processes (the foreground window's owner);
  * every session process seen, and any conhost/cmd/powershell/pwsh/python whose
    parent is textrec;
  * the console-handle hosts (conhost.exe) that existed at any point.
Pass means ``watched_windows``, ``focus_changes`` and ``watched_children`` are 0.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

WATCHED = {"textrec", "textrec20", "conhost", "cmd", "powershell", "pwsh", "python"}


def summarise(path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    samples = [row for row in rows if row.get("kind") == "sample"]
    tables = [row for row in rows if row.get("kind") in ("start", "processes", "end")]

    times = [row.get("at_ms") for row in samples if row.get("at_ms") is not None]
    gaps = []
    for earlier, later in zip(times, times[1:]):
        gaps.append((later - earlier) / 1000.0)
    start = next((row for row in rows if row.get("kind") == "start"), {})

    foreground: dict[str, int] = {}
    watched_windows = 0
    focus_changes = 0
    for row in samples:
        window = row.get("foreground") or {}
        name = (window.get("process") or "(none)").lower()
        foreground[name] = foreground.get(name, 0) + 1
        watched_windows += len(row.get("watched") or [])
        if row.get("focus_change"):
            focus_changes += 1

    processes: dict[int, dict] = {}
    for table in tables:
        for entry in table.get("processes") or []:
            processes.setdefault(entry["pid"], entry)
    textrec_pids = {entry["pid"] for entry in processes.values()
                    if entry["process"].lower().startswith("textrec")}
    watched_children = [
        entry for entry in processes.values()
        if entry["ppid"] in textrec_pids and entry["process"].lower() in WATCHED]
    conhosts = sorted(entry["pid"] for entry in processes.values()
                      if entry["process"].lower() == "conhost")
    watched_present = sorted({entry["process"].lower() for entry in processes.values()
                              if entry["process"].lower() in WATCHED})

    return {
        "log": str(path),
        "records": len(rows),
        "samples": len(samples),
        "sample_gap_max_s": round(max(gaps), 3) if gaps else None,
        "sample_gap_min_s": round(min(gaps), 3) if gaps else None,
        "probe_reported_max_gap_ms": start.get("max_gap_ms")
        or next((row.get("max_gap_ms") for row in rows if row.get("kind") == "end"), None),
        "watched_windows": watched_windows,
        "focus_changes": focus_changes,
        "foreground_counts": foreground,
        "session": start.get("session"),
        "probe_pid": start.get("pid"),
        "max_gap_over_200ms": bool(gaps and max(gaps) > 0.2),
        "textrec_pids": sorted(textrec_pids),
        "watched_children_of_textrec": watched_children,
        "conhost_pids_seen": conhosts,
        "watched_processes_present": watched_present,
        "pass": watched_windows == 0 and focus_changes == 0 and not watched_children,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    summary = summarise(args.log)
    print(json.dumps(summary, indent=2))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
