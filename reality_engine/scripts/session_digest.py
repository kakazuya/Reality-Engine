"""Whole-conversation context for worker models (Shivam, 2026-10-20: "how would DeepSeek know what happened in the whole
chat?"). Turns a Claude Code session transcript (~/.claude/projects/<project>/<session>.jsonl) into a readable digest a
worker can load, so the orchestrator never has to retell the story (no orchestrator tokens: a script does it).

Kept: Shivam's messages, Claude's replies, and (--tools brief) one line per command Claude ran with the start of its
result. Dropped: Claude's private reasoning, images (shown as [image]), and system reminders. Keys are masked.
Output: data/dsh_tasks/session_digest.md (overwritten). Pair with worker_context.py (live state) and tasks/STATE.md.

    python -m reality_engine.scripts.session_digest [--session <id|path>] [--tools none|brief|full] [--since HH:MM]
"""
import argparse
import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJ = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(ROOT))
OUT = ROOT / "reality_engine" / "data" / "dsh_tasks" / "session_digest.md"
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
SECRET = re.compile(r"((?:api[_-]?)?key|token|secret|password|Bearer)([=: ]+)[A-Za-z0-9._\-]{12,}", re.I)


def clean(s):
    return SECRET.sub(r"\1\2***", REMINDER.sub("", s)).strip()


def when(e):
    ts = e.get("timestamp")
    if not ts:
        return ""
    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30)))
    return t.strftime("%m-%d %H:%M")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="", help="session id or .jsonl path (default: most recently written)")
    ap.add_argument("--tools", choices=["none", "brief", "full"], default="brief")
    ap.add_argument("--since", default="", help="only entries at/after this IST 'MM-DD HH:MM' or 'HH:MM'")
    a = ap.parse_args()
    if a.session.endswith(".jsonl"):
        src = Path(a.session)
    elif a.session:
        src = PROJ / f"{a.session}.jsonl"
    else:
        src = max(PROJ.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    L = [f"# Session digest: {src.stem}", f"Made {dt.datetime.now():%Y-%m-%d %H:%M} IST from {src.name}. Shivam = the user, "
         "Claude = the orchestrator. Times IST. Commands are one line each (tools=" + a.tools + ").", ""]
    pending = {}
    with src.open(encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            t, m, ts = e.get("type"), e.get("message") or {}, when(e)
            if a.since and ts and (ts if len(a.since) > 5 else ts[-5:]) < a.since:
                continue
            content = m.get("content")
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
            for b in blocks:
                k = b.get("type")
                if t == "user" and k == "text":
                    txt = clean(b.get("text", ""))
                    if txt and not txt.startswith("[Request interrupted"):
                        L += [f"## {ts} Shivam", txt, ""]
                elif t == "user" and k == "image":
                    L += [f"## {ts} Shivam", "[image]", ""]
                elif t == "assistant" and k == "text" and b.get("text", "").strip():
                    L += [f"## {ts} Claude", clean(b["text"]), ""]
                elif t == "assistant" and k == "tool_use" and a.tools != "none":
                    inp = b.get("input") or {}
                    what = inp.get("description") or inp.get("command") or inp.get("file_path") or inp.get("query") or ""
                    pending[b.get("id")] = f"- {ts} [{b.get('name')}] {clean(str(what))[:200]}"
                elif t == "user" and k == "tool_result" and a.tools != "none":
                    head = pending.pop(b.get("tool_use_id"), None)
                    if head is None:
                        continue
                    res = b.get("content")
                    if isinstance(res, list):
                        res = " ".join(x.get("text", "") for x in res if isinstance(x, dict))
                    res = clean(str(res or "")).replace("\n", " | ")
                    n = 300 if a.tools == "brief" else 4000
                    L.append(f"{head}\n  -> {res[:n]}{' ...' if len(res) > n else ''}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {OUT.stat().st_size / 1024:.0f} KB (~{OUT.stat().st_size / 4 / 1000:.0f}k tokens)")


if __name__ == "__main__":
    main()
