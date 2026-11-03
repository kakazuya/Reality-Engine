"""Audit loop and worker transcripts for reads of the hidden split (GOAL section 6).

A hidden question is only ever the wrapper's.  Any session that reads ``hidden.jsonl`` or a
``D:\\RealityEngine\\pilot3\\answer_run*`` file rejects the loop, so this scans the raw stream-json for those
names -- tool arguments, shell commands and tool output alike.  It prints the file and line and the tool that
did it, never the text around the match: that text can be a hidden question.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

FORBIDDEN = re.compile(r"hidden\.jsonl|answer_run|night_eval[\\/]hidden", re.I)


def _tool_uses(node: Any) -> Iterator[tuple[str, str]]:
    """Every (tool name, serialised input) in a stream-json event."""
    if isinstance(node, dict):
        if node.get("type") == "tool_use":
            yield str(node.get("name") or "?"), json.dumps(node.get("input") or {}, ensure_ascii=False)
        for value in node.values():
            yield from _tool_uses(value)
    elif isinstance(node, list):
        for value in node:
            yield from _tool_uses(value)


def scan(path: Path) -> list[dict[str, Any]]:
    """One hit per transcript line that names the hidden split; no question text is kept."""
    hits: list[dict[str, Any]] = []
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), 1):
        match = FORBIDDEN.search(line)
        if not match:
            continue
        tool, kind = "?", "line"
        try:
            event = json.loads(line)
        except ValueError:
            event = None
        if isinstance(event, dict):
            for name, payload in _tool_uses(event):
                if FORBIDDEN.search(payload):
                    tool, kind = name, "tool_use"
                    break
            else:
                kind = f"event:{event.get('type')}"
        hits.append({"file": str(path), "line": number, "match": match.group(0).lower(), "tool": tool,
                     "kind": kind})
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audit", description="find hidden-split reads in transcripts")
    parser.add_argument("transcripts", nargs="+", help="stream-json transcript(s)")
    parser.add_argument("--out", default="", help="write the hits json here")
    args = parser.parse_args(argv)
    hits: list[dict[str, Any]] = []
    for name in args.transcripts:
        hits.extend(scan(Path(name)))
    print(f"transcripts {len(args.transcripts)}  hidden-split reads {len(hits)}")
    for hit in hits:
        print(f"  HIT {hit['file']}:{hit['line']} {hit['kind']} {hit['tool']}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"hits": hits}, indent=2), encoding="utf-8")
    return 0 if not hits else 1


if __name__ == "__main__":
    sys.exit(main())
