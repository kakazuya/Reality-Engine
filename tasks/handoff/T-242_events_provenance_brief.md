# T-242 brief: read provenance columns on filing events (dsh DeepSeek, off-peak, 26 Nov, Wolf)

Ticket: T-242
permission: workspace-write (worktree)

Goal: every event row written by reality_engine/research/filing_events.py carries the four read-provenance columns
Shivam ruled on 26 Nov (skill `.claude/skills/read-provenance/SKILL.md` - read it first): `read_model`,
`read_gateway`, `read_harness`, `prompt_fp`, beside the existing read time. Same pattern as
reality_engine/v2/observations.py `read_provenance()` / `gateway_of()` (reuse them, do not copy).

Evidence: observations rows got these in 89730bea (`MIGRATIONS`, `write_rows`); the event table has none
(`PRAGMA table_info(event)` on C:/RealityEngine/t242/fresh9/events_mf_fresh9.db). Events read with hy4 on OpenCode Go
via filing_events' own HTTP call; script-only rows (method='script') have no model.

## Steps
1. Add the four TEXT NOT NULL DEFAULT '' columns to the event table schema and a migration for existing DBs.
2. Fill them at write: model rows -> the model/gateway the call used + harness 'reality_engine.research.filing_events
   (direct HTTP)' (env REALITY_READ_HARNESS overrides) + prompt_fp = the event prompt fingerprint already computed
   (`prompt_fp` / `EVENT_PROMPT_V1`); script / computed rows -> read_model 'script', read_gateway '',
   read_harness 'reality_engine.research.filing_events', prompt_fp ''.
3. reality_engine/scripts/load_observations.py loads events into store `filing_event` with a column union - confirm the
   new columns flow through (no code change if the union already handles it; else add them).
4. Tests in reality_engine/tests/test_filing_events_model.py: a model row and a script row get the right four values;
   an old DB without the columns is migrated.
5. Docs: one line in the DEVELOPER_GUIDE.md read-provenance bullet; update the "Not yet done" line of
   .claude/skills/read-provenance/SKILL.md.

Files: reality_engine/research/filing_events.py, reality_engine/scripts/load_observations.py (only if needed),
reality_engine/tests/test_filing_events_model.py, docs/DEVELOPER_GUIDE.md, .claude/skills/read-provenance/SKILL.md.
Accept: python -m pytest -q reality_engine/tests/test_filing_events_model.py ; test_filing_events.py ;
test_load_observations_gate.py - each separately, all pass; VERIFIED_KINDS and event logic unchanged.
Stop if: any existing test needs changing beyond adding columns: report and stop.
Pitfalls: pytest, not unittest; never write under C:/RealityEngine or D:/RealityEngine; no model calls; never kill
processes by name.
Budget: ~45 minutes, ~60 tool calls.
