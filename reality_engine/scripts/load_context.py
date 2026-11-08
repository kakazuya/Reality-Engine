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


def build() -> str:
    rulings = _read(ROOT / "tasks" / "RULINGS.md")
    parts: list[str] = []
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
    used = len("\n\n".join(parts))
    for name, body in live["sections"].items():
        if name in WHOLE:
            continue
        block = f"## {name}\n{body}"
        if used + len(block) + 2 <= LIMIT:
            parts.append(block)
            used += len(block) + 2
        else:
            dropped.append(name)
    card = live.get("card") or ""
    if card:
        parts.append(card)
    heads = recent_decisions(_read(LOG))
    if heads:
        parts.append("# Latest decisions, full entries in the decision log\n" + "\n".join(heads))
    if dropped:
        parts.append("More state: project_state() tool or tasks/STATE.md")
    return "\n\n".join(parts)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(build())
