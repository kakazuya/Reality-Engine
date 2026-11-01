"""SessionStart hook: put Shivam's rulings, the live state and the ticket card into every
session, also after compaction.

Claude Code caps hook output at 10,000 characters, so rulings come first and the total stays
under that.  The card sits after STATE (never displacing it) and before the decision headings;
the tracker file itself is not loaded.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = Path(r"D:\RealityEngine\plans\DECISION_LOG.md")
LIMIT = 9500

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reality_engine.scripts import task_board  # noqa: E402


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        return f"UNREADABLE {path}: {exc}"


def recent_decisions(text: str, count: int = 5) -> list[str]:
    """The last few decision headings; the entries stay in the log."""
    return re.findall(r"^## .*$", text, flags=re.M)[-count:]


def build() -> str:
    parts = [_read(ROOT / "tasks" / "RULINGS.md"), _read(ROOT / "tasks" / "STATE.md")]
    tracker = task_board.card()
    used = len("\n\n".join(parts))
    if tracker and used + len(tracker) + 2 <= LIMIT:
        parts.append(tracker)
    heads = recent_decisions(_read(LOG))
    if heads:
        parts.append("# Latest decisions, full entries in the decision log\n" + "\n".join(heads))
    text = "\n\n".join(parts)
    if len(text) > LIMIT:
        text = text[:LIMIT] + f"\n\n[Cut at {LIMIT} characters: shorten tasks/STATE.md. Read the rest from the file.]"
    return text


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(build())
