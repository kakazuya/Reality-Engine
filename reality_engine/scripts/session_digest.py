"""Whole-conversation context for worker models (Shivam, 2026-10-20: "how would DeepSeek know what happened in the whole
chat?"). Turns Claude Code session transcripts (~/.claude/projects/<project>/<session>.jsonl) into readable digests a
worker can load, so the orchestrator never has to retell the story (no orchestrator tokens: a script does it).

Kept: Shivam's messages, Claude's replies, and (--tools brief) one line per command Claude ran with the start of its
result. Dropped: Claude's private reasoning, images (shown as [image]), and system reminders. Keys are masked.
Output (part of the hotline, see data/hotline/README.md): data/hotline/generated/sessions/<session id>.md per session
plus data/hotline/generated/sessions/INDEX.md (newest first, with each session's first request). Default: every session
written in the last --hours hours; --session for one.

    python -m reality_engine.scripts.session_digest [--hours 24] [--session <id|path>] [--tools none|brief|full]
"""
import argparse
import datetime as dt
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJ = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(ROOT))
OUT_DIR = ROOT / "reality_engine" / "data" / "hotline" / "generated" / "sessions"
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
SECRET = re.compile(r"((?:api[_-]?)?key|token|secret|password|Bearer)([=: ]+)[A-Za-z0-9._\-]{12,}", re.I)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def clean(s):
    return SECRET.sub(r"\1\2***", REMINDER.sub("", s)).strip()


def when(e):
    ts = e.get("timestamp")
    if not ts:
        return ""
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST).strftime("%m-%d %H:%M")


def digest(src, tools):
    """-> (markdown lines, first request of Shivam, number of Shivam messages)"""
    L, pending, first, n_user = [], {}, "", 0
    with src.open(encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            t, m, ts = e.get("type"), e.get("message") or {}, when(e)
            content = m.get("content")
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
            for b in blocks:
                k = b.get("type")
                if t == "user" and k == "text":
                    txt = clean(b.get("text", ""))
                    if txt and not txt.startswith("[Request interrupted"):
                        L += [f"## {ts} Shivam", txt, ""]
                        n_user += 1
                        first = first or txt[:160].replace("\n", " ")
                elif t == "user" and k == "image":
                    L += [f"## {ts} Shivam", "[image]", ""]
                elif t == "assistant" and k == "text" and b.get("text", "").strip():
                    L += [f"## {ts} Claude", clean(b["text"]), ""]
                elif t == "assistant" and k == "tool_use" and tools != "none":
                    inp = b.get("input") or {}
                    what = inp.get("description") or inp.get("command") or inp.get("file_path") or inp.get("query") or ""
                    pending[b.get("id")] = f"- {ts} [{b.get('name')}] {clean(str(what))[:200]}"
                elif t == "user" and k == "tool_result" and tools != "none":
                    head = pending.pop(b.get("tool_use_id"), None)
                    if head is None:
                        continue
                    res = b.get("content")
                    if isinstance(res, list):
                        res = " ".join(x.get("text", "") for x in res if isinstance(x, dict))
                    res = clean(str(res or "")).replace("\n", " | ")
                    n = 300 if tools == "brief" else 4000
                    L.append(f"{head}\n  -> {res[:n]}{' ...' if len(res) > n else ''}")
    return L, first, n_user


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24, help="digest every session written in the last N hours")
    ap.add_argument("--session", default="", help="one session id or .jsonl path instead")
    ap.add_argument("--tools", choices=["none", "brief", "full"], default="brief")
    a = ap.parse_args()
    if a.session:
        srcs = [Path(a.session) if a.session.endswith(".jsonl") else PROJ / f"{a.session}.jsonl"]
    else:
        cut = time.time() - a.hours * 3600
        srcs = [p for p in PROJ.glob("*.jsonl") if p.stat().st_mtime >= cut]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index = []
    for src in sorted(srcs, key=lambda p: -p.stat().st_mtime):
        L, first, n_user = digest(src, a.tools)
        if not n_user:
            continue
        upd = dt.datetime.fromtimestamp(src.stat().st_mtime, IST)
        head = [f"# Session {src.stem}", f"Digest made {dt.datetime.now(IST):%Y-%m-%d %H:%M} IST; transcript last written "
                f"{upd:%Y-%m-%d %H:%M}. Shivam = the user, Claude = that session's agent. Times IST.", ""]
        out = OUT_DIR / f"{src.stem}.md"
        out.write_text("\n".join(head + L) + "\n", encoding="utf-8")
        index.append(f"- {upd:%m-%d %H:%M} [{src.stem}]({src.stem}.md) {n_user} messages from Shivam, "
                     f"{out.stat().st_size / 1024:.0f} KB. First request: {first}")
    (OUT_DIR / "INDEX.md").write_text("# Claude Code sessions (newest first)\n\n" + "\n".join(index) + "\n", encoding="utf-8")
    print(f"wrote {len(index)} session digests to {OUT_DIR}")


if __name__ == "__main__":
    main()
