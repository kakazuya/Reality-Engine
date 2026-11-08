"""Shivam's rulings and the live project state, served on demand (T-125).

The session-start hook (``load_context.py``) prints the rulings whole.  These functions let the
reality-data ``project_rules`` and ``project_state`` tools answer the same questions for any
model from the same files, so a session does not have to carry the text.  Stdlib only: the hook
imports this module, so it stays light and never raises on a broken file.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RULINGS = Path("tasks") / "RULINGS.md"
STATE = Path("tasks") / "STATE.md"
#: doc_gate.CHAR_LIMITS["tasks/RULINGS.md"]; the hook warns when the file is over it
RULINGS_BUDGET = 8000
NOW = "Now"
NEXT = "Next action"
SNIPPET = 120


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"UNREADABLE {path}: {exc}"


def _card() -> str:
    """The ticket card. A broken tracker must never cost a session its rulings."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from reality_engine.scripts import task_board

        return task_board.card()
    except Exception as exc:
        return f"task card unavailable: {exc}"[:600]


def _blocks(text: str) -> list[tuple[str, str]]:
    """``## <heading>`` -> its body, in document order; text before the first heading is ``""``."""
    blocks: list[tuple[str, list[str]]] = []
    name: str = ""
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            blocks.append((name, body))
            name, body = line[3:].strip(), []
        else:
            body.append(line)
    blocks.append((name, body))
    return [(name, "\n".join(lines).strip()) for name, lines in blocks]


def sections(text: str) -> list[dict[str, Any]]:
    """RULINGS.md as one item per top-level ``- `` bullet: ``{"section", "text"}``.

    A bullet keeps its continuation lines (any non-blank line before the next bullet or
    heading); a blank line ends it.
    """
    items: list[dict[str, Any]] = []
    section = ""
    item: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            section, item = line[3:].strip(), None
        elif line.startswith("- "):
            item = {"section": section, "text": line[2:].strip()}
            items.append(item)
        elif not line.strip():
            item = None
        elif item is not None:
            item["text"] += "\n" + line.strip()
    return items


def _index(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The topic-less view: section name plus the first 120 characters of each bullet."""
    out: list[dict[str, Any]] = []
    for item in items:
        entry = next((e for e in out if e["name"] == item["section"]), None)
        if entry is None:
            entry = {"name": item["section"], "items": []}
            out.append(entry)
        entry["items"].append(item["text"][:SNIPPET])
    return out


def rules(topic: str | None = None, root: Path = ROOT) -> dict[str, Any]:
    """Shivam's binding rulings: the index, or every bullet matching a topic.

    A topic matches a bullet when the bullet contains every word of the topic (words of 3+
    characters, case-insensitive).  A matched bullet is returned whole, never truncated; a miss
    returns the index with ``found: false``.
    """
    items = sections(_read(root / RULINGS))
    if topic is None:
        return {"sections": _index(items)}
    words = [w for w in re.split(r"[^0-9a-z]+", topic.lower()) if len(w) >= 3]
    if not words:
        words = [topic.strip().lower()] if topic.strip() else []
    matched = [i for i in items if words and all(w in i["text"].lower() for w in words)]
    if not matched:
        return {"found": False, "topic": topic, "sections": _index(items)}
    return {"found": True, "topic": topic, "rules": matched}


def state(root: Path = ROOT, max_chars: int = 6000) -> dict[str, Any]:
    """STATE.md sections plus the ticket card; ``## Now`` and ``## Next action`` are always whole.

    The other sections are added in document order while their text fits ``max_chars``; the ones
    left out are named in ``dropped`` so the caller can point at this function or the file.
    """
    text = _read(root / STATE)
    blocks = _blocks(text)
    if not any(name for name, _ in blocks) and text.strip():  # unreadable or heading-less file
        blocks = [(NOW, text)]
    out: dict[str, str] = {}
    dropped: list[str] = []
    used = 0
    for name, body in blocks:
        if not name:
            continue
        if name in (NOW, NEXT):
            out[name] = body
        elif used + len(body) <= max_chars:
            out[name] = body
            used += len(body)
        else:
            dropped.append(name)
    return {"sections": out, "dropped": dropped, "chars": used, "card": _card()}
