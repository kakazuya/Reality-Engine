from pathlib import Path

from reality_engine.scripts.load_context import LIMIT, build, recent_decisions

ROOT = Path(__file__).resolve().parents[2]


def test_rulings_come_first_and_fit_the_hook_cap():
    text = build()
    assert text.startswith("# Shivam's rulings")
    assert len(text) <= LIMIT + 100
    assert "## Next action" in text, "STATE was cut off: shorten tasks/STATE.md or tasks/RULINGS.md"


def test_recent_decisions_returns_last_headings():
    log = "## one\nbody\n## two\n## three\n"
    assert recent_decisions(log, 2) == ["## two", "## three"]


def test_session_start_hook_also_fires_after_compaction():
    settings = (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert "SessionStart" in settings and "compact" in settings and "load_context.py" in settings
