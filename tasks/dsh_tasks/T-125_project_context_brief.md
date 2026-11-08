# T-125 round 1: project rules and state served by tools, start files capped by characters

Ticket: T-125

Goal: every model (Claude, DeepSeek, Gemini) reads Shivam's rulings and the live state from ONE source through
tools, and the session-start hook never silently drops a ruling. Code only; Opus rewrites the text of
RULINGS.md and STATE.md himself.

Evidence (Opus, 8 Nov 2026, measured):
- `reality_engine/scripts/load_context.py` (SessionStart hook) joins `tasks/RULINGS.md` (12,473 chars) and
  `tasks/STATE.md` (33,616 chars) and cuts the whole text at `LIMIT = 9500`. RULINGS alone is over the cap, so
  the end of the rulings ("Each extractor ...", sections `## Never`, `## Telling Shivam`, `## Agreed direction`)
  and ALL of STATE never reach a session. Nothing warns about it except a cut marker at the end.
- `reality_engine/tests/test_load_context.py::test_rulings_come_first_and_fit_the_hook_cap` asserts
  `"## Next action" in text`; with today's files it fails.
- `reality_engine/scripts/doc_gate.py` line 24 `LINE_LIMITS = {STATE: 40, "AGENTS.md": 150, "tasks/RULINGS.md": 40,
  "tasks/TASKS.md": 150}` caps lines only; STATE.md keeps 40 lines but each line is a paragraph.
- reality-data MCP tools are declared in `plugins/reality-data/server/server.py` with `@server.tool(name=...,
  description=..., annotations=ToolAnnotations(read_only_hint=True, ...))` and wrapped in `_safe(lambda: ...)`;
  see the `schema` tool near line 120 for the exact pattern. The repo root is `REALITY_DATA_REPO_ROOT`.

Steps (numbered, do them in order):
1. New module `reality_engine/scripts/project_context.py` (no third-party imports):
   - `sections(text) -> list[dict]`: split RULINGS.md on `## ` headings; each top-level `- ` bullet (with its
     continuation lines) is one item `{"section", "text"}`.
   - `rules(topic: str | None = None, root: Path = ROOT) -> dict`: no topic -> `{"sections": [{name, items:
     [first 120 chars of each bullet]}]}`; a topic -> every bullet whose text contains ALL the topic's words
     (case-insensitive, words >= 3 chars), full text, with its section; zero matches -> the section index plus
     `"found": false`. Never truncates a matched bullet.
   - `state(root: Path = ROOT, max_chars: int = 6000) -> dict`: STATE.md split by `## ` headings into
     `{heading: text}`; `"## Now"` and `"## Next action"` always whole; other sections fill up to `max_chars`;
     plus `task_board.card()` (try/except like `load_context._card`).
2. `plugins/reality-data/server/server.py`: two read-only tools `project_rules(topic: str | None = None)` and
   `project_state()` calling step 1 with the repo root from `REALITY_DATA_REPO_ROOT` (fallback: two parents up
   from the module). Descriptions say: "Shivam's binding rulings for this project; call before deciding scope,
   briefing a worker or reporting" and "the live project state and next action".
3. `load_context.py` `build()`: order = RULINGS (never cut) -> STATE `## Now` + `## Next action` sections
   (whole, then any remaining sections only while under LIMIT) -> card -> decisions. If RULINGS alone is over
   `LIMIT - 1500`, put ONE first line `RULINGS.md is N chars over its 8,000 budget: Opus must shorten it` and
   still print every ruling (the hook cap is 10,000; use `LIMIT = 9800`). When STATE sections are dropped, end
   with `More state: project_state() tool or tasks/STATE.md`.
4. `doc_gate.py`: add `CHAR_LIMITS = {STATE: 4000, "tasks/RULINGS.md": 8000}` checked like `LINE_LIMITS` (only
   when the file is staged), message `"{name} has {n} characters, limit {limit}: ..."`, and make
   `_rule_of`/the `start_files` classification (line ~121) recognise it.
5. Tests: `reality_engine/tests/test_project_context.py` (fixture RULINGS/STATE in a temp dir: index, topic hit,
   topic miss, state keeps Now + Next action whole), extend `test_load_context.py` (rulings never cut with a
   12,000-char fixture; warning line present), extend `test_doc_gate.py` (char limit refuses a staged 4,001-char
   STATE). Use the temp-dir fixture style already in `test_load_context.py` (`make_temp_dir`). Replace the
   failing `"## Next action" in text` assertion of the live-file test with: rulings complete (its last `## `
   heading is present) - the live files are Opus's to shorten.
6. Docs: one paragraph in `docs/DEVELOPER_GUIDE.md` next to the existing load_context / doc_gate text, and the
   two tools in `plugins/reality-data/README.md`.

Files: reality_engine/scripts/project_context.py (new), reality_engine/scripts/load_context.py,
reality_engine/scripts/doc_gate.py, plugins/reality-data/server/server.py, reality_engine/tests/test_project_context.py
(new), reality_engine/tests/test_load_context.py, reality_engine/tests/test_doc_gate.py, docs/DEVELOPER_GUIDE.md,
plugins/reality-data/README.md. Do NOT edit tasks/RULINGS.md, tasks/STATE.md, tasks/TASKS.md, AGENTS.md or memory.

Accept / Test command(s):
`python -m pytest -q reality_engine/tests/test_project_context.py reality_engine/tests/test_load_context.py reality_engine/tests/test_doc_gate.py plugins/reality-data/tests/test_reality_data.py`
all pass; `python reality_engine/scripts/load_context.py` prints the full rulings (its output contains
`## Agreed direction`) and stays under 10,000 characters or prints the over-budget warning line; typecheck the
changed .py files with the code-tools `typecheck`.

Pitfalls: Windows paths and UTF-8 (`encoding="utf-8"` everywhere; `sys.stdout.reconfigure(encoding="utf-8")` in
`__main__`); the hook must never raise (a broken file still prints the rulings); do not import the server's heavy
modules from `project_context.py`; keep the server's start fast (no file reads at import).

Stop if: a change needs RULINGS/STATE text edits, or the reality-data server tests fail for reasons outside your
two tools; report and stop.

Budget: about 60 tool calls, 90 minutes. Use `outline` before reading whole files.
