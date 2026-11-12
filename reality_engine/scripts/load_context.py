"""SessionStart hook: put Shivam's rulings, the live state and the ticket card into every
session, also after compaction.

Claude Code caps hook output at 10,000 characters, so rulings come first and are never cut.
STATE's ``## Now`` and ``## Next action`` follow whole; its other sections, the ticket card and
the decision headings are added only while the total is under ``LIMIT``.  When RULINGS.md is
over its own 8,000-character budget the first line says so, and every ruling still prints: a
silent cut of a ruling is what this hook must never do.  The tracker file itself is not loaded.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LOG = Path(r"D:\RealityEngine\plans\DECISION_LOG.md")
LIMIT = 9800
#: room kept free by the over-budget warning for STATE's two whole sections
RESERVE = 1500
RULINGS_BUDGET = 8000
WHOLE = ("Now", "Next action")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        return f"UNREADABLE {path}: {exc}"


def _live_state() -> dict[str, Any]:
    """project_context.state(), and never a hook that dies on its own import."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from reality_engine.scripts import project_context

        return project_context.state(ROOT)
    except Exception as exc:
        return {"sections": {}, "dropped": [], "chars": 0,
                "card": f"project state unavailable: {exc}"[:600]}


def recent_decisions(text: str, count: int = 5) -> list[str]:
    """The last few decision headings; the entries stay in the log."""
    return re.findall(r"^## .*$", text, flags=re.M)[-count:]


def due_ideas(text: str, today: str | None = None) -> list[str]:
    """Ideas in tasks/IDEA_BOX.md that are still open and whose review date has passed (Shivam, 12 Nov: ideas must be
    re-read at their trigger and proposed for promotion, never left to sit)."""
    import datetime
    import re

    day = today or datetime.date.today().isoformat()
    out: list[str] = []
    for block in re.split(r"\n(?=## I-\d+)", text):
        head = re.match(r"## (I-\d+): (.+)", block)
        due = re.search(r"Review trigger:.*?review by (\d{4}-\d{2}-\d{2})", block)
        status = re.search(r"Status: (\S+)", block)
        if not head or not due or not status or status.group(1) not in ("parked", "next"):
            continue
        if due.group(1) <= day:
            stage = re.search(r"stage `([^`]+)`", block)
            out.append(f"- {head.group(1)} {head.group(2)} (stage {stage.group(1) if stage else '?'}, "
                       f"due {due.group(1)})")
    return out


def build() -> str:
    rulings = _read(ROOT / "tasks" / "RULINGS.md")
    parts: list[str] = []
    ideas = due_ideas(_read(ROOT / "tasks" / "IDEA_BOX.md"))
    if ideas:
        parts.append("# Ideas due for review: read each in tasks/IDEA_BOX.md and propose promote / keep / drop "
                     "to Shivam\n" + "\n".join(ideas))
    if len(rulings) > LIMIT - RESERVE:
        over = len(rulings) - RULINGS_BUDGET
        parts.append(f"RULINGS.md is {over} chars over its 8,000 budget: Opus must shorten it")
    parts.append(rulings)
    live = _live_state()
    for name in WHOLE:
        body = live["sections"].get(name)
        if body:
            parts.append(f"## {name}\n{body}")
    dropped = list(live["dropped"])
    card = live.get("card") or ""
    footer = "More state: project_state() tool or tasks/STATE.md"
    # The card and footer are reserved first, so optional STATE sections never push them past the cap.
    used = len("\n\n".join(parts)) + (len(card) + 2 if card else 0) + len(footer) + 2
    for name, body in live["sections"].items():
        if name in WHOLE:
            continue
        block = f"## {name}\n{body}"
        if used + len(block) + 2 <= LIMIT:
            parts.append(block)
            used += len(block) + 2
        else:
            dropped.append(name)
    if card:
        parts.append(card)
    heads = recent_decisions(_read(LOG))
    if heads:
        block = "# Latest decisions, full entries in the decision log\n" + "\n".join(heads)
        if used + len(block) + 2 <= LIMIT:  # decision headings are the first thing to go
            parts.append(block)
            used += len(block) + 2
    if dropped:
        parts.append(footer)
    return "\n\n".join(parts)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(build())
