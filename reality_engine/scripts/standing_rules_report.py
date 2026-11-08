"""Shivam's standing-rules sheet (8 Nov 2026): ``D:\\RealityEngine\\reports\\standing_rules.xlsx`` and ``.html``.

Every ruling in ``tasks/RULINGS.md`` (parsed by ``project_context.sections``), and for each one HOW it reaches every
session and worker:

* Prompt   - the SessionStart hook ``reality_engine/scripts/load_context.py`` prints the whole file into every
             Claude session (startup, resume, clear, compaction), never cut (T-125).
* MCP      - ``project_rules(topic)`` / ``project_state()`` on the reality-data server, the same text for Claude,
             dsh (DeepSeek) and agy (Gemini) workers that load that server.
* Worker   - the dsh context pack (``tasks/worker_context/CONTEXT.md``, prepended to every brief) tells the worker
             the rulings bind it and where they are.
* Code     - a gate that refuses the action (the ``[check: ...]`` tag of the ruling, mapped in ``CODE_GATES``).
* Memory   - Claude's auto-memory files whose description shares the ruling's distinctive words (keyword match,
             shown with its score so a weak match is visible).

Rewritten by the ``post-commit`` hook whenever a commit on main touches ``tasks/RULINGS.md``, and by hand:

    python reality_engine/scripts/standing_rules_report.py
"""
from __future__ import annotations

import html
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = Path(os.environ.get("REALITY_REPORTS_DIR", r"D:\RealityEngine\reports"))
MEMORY_DIRS = [Path(os.environ.get("USERPROFILE", "")) / d / "projects" / "C--Users-warri-Downloads-Info-Diffusion-Model" / "memory"
               for d in (".claude", ".claude-neo")]
CODE_GATES = {
    "doc_gate": "pre-commit `reality_engine/scripts/doc_gate.py`: refuses a main commit/merge without docs, and start files over their size",
    "start gate": "dsh-worker `start_worker`: refuses a start without `permission`, without the seven brief fields, a peak-hour DeepSeek start, or an unknown ticket",
    "test_hp_headless": "test `test_hp_headless` + HP launcher: no window on the HP",
    "T-050 stop hook": "Stop hook `session_hooks.py stop`: blocks ending a turn while a job runs without a watch",
    "commit-msg": "commit-msg hook: a main commit must name a real ticket",
    "task_board + post-commit hook": "`task_board` add/set/done/drop and the post-commit hook rewrite the Excel ticket board",
}
#: Code that enforces a ruling without a ``[check: ...]`` tag in its text (regex on the ruling -> gate).
CODE_EXTRA = [
    (r"off-peak", "dsh-worker `start_worker` refuses a DeepSeek start in peak hours"),
    (r"`agy` runs only", "agy-worker MCP pins the model to gemini-3.8-flash-medium"),
    (r"ticket first", "`.claude/settings.json` denies hand edits of tasks/TASKS.md; only `task_board` writes it"),
    (r"Shivam_Private", "`.claude/settings.json` denies Read of D:/Shivam_Private/**"),
    (r"Push without", "dsh-worker `push` refuses without confirm=true"),
    (r"Every worker start names `permission`", "dsh-worker `start_worker` refuses a start without the seven brief fields"),
]
MECHANISMS = [
    ("Prompt (session start)", "`.claude/settings.json` SessionStart -> `load_context.py` prints `tasks/RULINGS.md` whole, then STATE and the ticket card",
     "every Claude session, Wolf and Eagle, incl. after compaction", "model must follow it (not enforced)"),
    ("MCP tool", "`project_rules(topic)`, `project_state()` on reality-data (`reality_engine/scripts/project_context.py`)",
     "Claude, dsh and agy workers that load reality-data (after /mcp restart)", "same source for every model; model must ask"),
    ("Worker context pack", "`tasks/worker_context/CONTEXT.md` prepended to every dsh brief",
     "every dsh worker", "pointer only; brief carries the task-specific limits"),
    ("Code gate / hook", "git hooks (pre-commit, commit-msg, post-commit), dsh start gate, Stop hook, tests",
     "everyone committing on main or starting a worker", "ENFORCED: the action is refused"),
    ("Memory file", "Claude auto-memory (`MEMORY.md` index loaded at start, files read when relevant)",
     "Claude sessions on both accounts (shared folder)", "model recall; not enforced"),
    ("Skill / plugin", "`plugins/dsh-worker/skills/dsh-worker/SKILL.md`, plugins `dsh-worker`, `reality-data`, `code-tools`, `agy-worker`",
     "Claude when it uses those tools", "tool behaviour is code; skill text is guidance"),
]
STOP = set("the a an and or of to in on for is are be by with from it its at as this that not no only any every each "
           "his her their our we you they them before after then than when one two all per via into over under more "
           "most must never always shivam nov oct claude".split())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9_-]{3,}", text.lower()) if w not in STOP}


def memories() -> list[tuple[str, str, set[str]]]:
    seen, out = set(), []
    for d in MEMORY_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            if f.name == "MEMORY.md" or f.name in seen:
                continue
            seen.add(f.name)
            text = f.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^description:\s*(.+)$", text, re.M)
            desc = m.group(1) if m else ""
            out.append((f.name, desc, _words(desc + " " + f.stem.replace("_", " "))))
    return out


def rules() -> list[dict]:
    from reality_engine.scripts import project_context

    text = (ROOT / "tasks" / "RULINGS.md").read_text(encoding="utf-8")
    mems = memories()
    out = []
    for i, item in enumerate(project_context.sections(text), 1):
        body = item["text"]
        checks = re.findall(r"\[check:\s*([^\]]+)\]", body)
        gates = [CODE_GATES.get(c.strip(), c.strip()) for c in checks]
        gates += [g for rx, g in CODE_EXTRA if re.search(rx, body) and g not in gates]
        words = _words(body)
        scored = sorted(((len(words & w) / (len(w) or 1), name) for name, _d, w in mems), reverse=True)
        mem = [f"{name} ({score:.2f})" for score, name in scored[:3] if score >= 0.25]
        out.append({"n": i, "section": item["section"], "rule": body.lstrip("- ").strip(),
                    "prompt": "yes", "mcp": "yes (project_rules)", "worker": "yes (context pack -> RULINGS.md)",
                    "code": "; ".join(gates) or "none: relies on the model", "memory": "; ".join(mem) or "none matched"})
    return out


def write(out_dir: Path | None = None) -> list[str]:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = rules()
    stamp = time.strftime("%Y-%m-%d %H:%M IST")
    cols = ["n", "section", "rule", "prompt", "mcp", "worker", "code", "memory"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Rules"
    ws.append(["#", "Section", "Standing rule", "Prompt (session start)", "MCP tool", "dsh worker brief",
               "Code gate (refuses the action)", "Memory file (keyword match score)"])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="334155")
    for r in data:
        ws.append([r[c] for c in cols])
    for col, w in zip("ABCDEFGH", (4, 16, 90, 12, 16, 20, 45, 45)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    m = wb.create_sheet("Mechanisms")
    m.append(["Mechanism", "Where it lives", "Who it reaches", "Strength"])
    for c in m[1]:
        c.font = Font(bold=True)
    for row in MECHANISMS:
        m.append(list(row))
    for col, w in zip("ABCD", (24, 70, 45, 35)):
        m.column_dimensions[col].width = w
    m.append([])
    m.append([f"Synced {stamp} from tasks/RULINGS.md (source of the rules). Edit rules by telling Claude; this file is rewritten."])
    tmp = out_dir / f".standing_rules.{os.getpid()}.xlsx"
    wb.save(tmp)
    os.replace(tmp, out_dir / "standing_rules.xlsx")

    esc = lambda v: html.escape(str(v))  # noqa: E731
    parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Standing Rules</title><style>
:root{{--bg:#fafaf9;--fg:#1c1917;--mut:#57534e;--line:#e7e5e4;--card:#fff;--ok:#15803d}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--line:#44403c;--card:#292524;--ok:#4ade80}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,Segoe UI,sans-serif;margin:0 auto;padding:24px 16px;max-width:1200px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:17px;margin:28px 0 8px}} .mut{{color:var(--mut)}} .wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;background:var(--card)}} th,td{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}
th{{color:var(--mut);font-size:12px}} .ok{{color:var(--ok);font-weight:600}}
</style></head><body><h1>Standing rules and how each is enforced</h1>
<div class="mut">Synced {esc(stamp)} from tasks/RULINGS.md. Same content: standing_rules.xlsx.</div>
<h2>Mechanisms</h2><div class="wrap"><table><tr><th>Mechanism</th><th>Where</th><th>Reaches</th><th>Strength</th></tr>"""]
    parts += [f"<tr><td>{esc(a)}</td><td>{esc(b)}</td><td>{esc(c)}</td><td>{esc(d)}</td></tr>" for a, b, c, d in MECHANISMS]
    parts.append('</table></div><h2>Rules</h2><div class="wrap"><table><tr><th>#</th><th>Section</th><th>Rule</th>'
                 "<th>Code gate</th><th>Memory</th></tr>")
    for r in data:
        code = f'<span class="ok">{esc(r["code"])}</span>' if not r["code"].startswith("none") else f'<span class="mut">{esc(r["code"])}</span>'
        parts.append(f"<tr><td>{r['n']}</td><td>{esc(r['section'])}</td><td>{esc(r['rule'])}</td><td>{code}</td>"
                     f"<td class=\"mut\">{esc(r['memory'])}</td></tr>")
    parts.append('</table></div><p class="mut">Every rule also reaches every Claude session through the session-start '
                 "prompt, every model through the project_rules MCP tool, and every dsh worker through its context pack.</p></body></html>")
    tmp = out_dir / f".standing_rules.{os.getpid()}.html"
    tmp.write_text("".join(parts), encoding="utf-8")
    os.replace(tmp, out_dir / "standing_rules.html")
    return [str(out_dir / "standing_rules.xlsx"), str(out_dir / "standing_rules.html")]


if __name__ == "__main__":
    try:
        print(write())
    except OSError as exc:
        print(f"standing rules not synced: {exc} (close it in Excel; the next sync retries)", file=sys.stderr)
        sys.exit(1)
