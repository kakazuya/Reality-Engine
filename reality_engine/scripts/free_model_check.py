"""Daily check that Beam is still free on OpenCode (Shivam, 10 Nov 2026).

Shivam's ruling: Beam may do plumbing code and grading only while it is free on
OpenCode Go; the day it charges, Beam work stops and DeepSeek takes it.  This
script reads the public pricing table at ``https://opencode.ai/docs/zen/`` (no
account, no user data sent) and writes ``tasks/flags/free_models.json``::

    {"beam-free": {"free": true, "checked_at": "...", "source": "...", "row": "..."}}

``run_deepseek_harness`` reads that flag: ``free: false`` refuses every
``beam-free`` start, and a flag older than ``MAX_AGE_HOURS`` makes the harness
run this check first.  A page that cannot be fetched or parsed leaves the flag
unchanged and says so; it is never taken as "free".

    python -m reality_engine.scripts.free_model_check          # check + write flag
    python -m reality_engine.scripts.free_model_check --show   # print the flag
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FLAG = REPO / "tasks" / "flags" / "free_models.json"
SOURCE = "https://opencode.ai/docs/zen/"
MAX_AGE_HOURS = 30
# model id -> the display name the pricing table prints
WATCHED = {"beam-free": "Beam Free"}


def parse_price_row(html: str, display: str) -> tuple[bool, str] | None:
    """Return (is_free, row_text) for the pricing-table row of ``display``.

    The table row reads ``<name> | input | output | cached | ...``; the model is
    free only when the three price cells are all "Free".  None = row not found.
    """
    text = re.sub(r"<[^>]+>", "|", html)
    text = re.sub(r"\s*\|[\s|]*", " | ", text)
    # lookahead: a row's cells must not swallow the next row's name
    for m in re.finditer(re.escape(display) + r"(?= \| ([^|]+) \| ([^|]+) \| ([^|]+) \|)", text):
        cells = [c.strip() for c in m.groups()]
        # the endpoint table lists the id and a URL instead of prices: skip it
        if any(c.startswith("http") or c == display.lower().replace(" ", "-") for c in cells):
            continue
        row = f"{display} | " + " | ".join(cells)
        return all(c.lower() == "free" for c in cells), row
    return None


def read_flag(path: Path = FLAG) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def is_stale(entry: dict | None, now: datetime | None = None) -> bool:
    if not entry or not entry.get("checked_at"):
        return True
    try:
        at = datetime.fromisoformat(entry["checked_at"])
    except ValueError:
        return True
    now = now or datetime.now(timezone.utc)
    return now - at > timedelta(hours=MAX_AGE_HOURS)


def check(path: Path = FLAG, fetch=None) -> dict:
    """Fetch the pricing page, update the flag for every watched model, return it."""
    flag = read_flag(path)
    try:
        if fetch is None:
            req = urllib.request.Request(SOURCE, headers={"User-Agent": "Mozilla/5.0"})
            html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
        else:
            html = fetch(SOURCE)
    except Exception as exc:  # network down: keep the old flag, never assume free
        print(f"free_model_check: could not fetch {SOURCE}: {exc}; flag unchanged", file=sys.stderr)
        return flag
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for model, display in WATCHED.items():
        got = parse_price_row(html, display)
        if got is None:
            print(f"free_model_check: no pricing row for {display!r}; flag unchanged", file=sys.stderr)
            continue
        free, row = got
        flag[model] = {"free": free, "checked_at": now, "source": SOURCE, "row": row}
        if not free:
            print(f"ALERT: {model} is no longer free on OpenCode ({row}); Beam work stops, use DeepSeek")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(flag, indent=2) + "\n", encoding="utf-8")
    return flag


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--show", action="store_true", help="print the stored flag only")
    a = ap.parse_args()
    flag = read_flag() if a.show else check()
    for model in WATCHED:
        e = flag.get(model)
        print(f"{model}: " + ("unknown" if not e else
              f"{'FREE' if e['free'] else 'PAID'} (checked {e['checked_at']}: {e['row']})"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
