# Task — measure every agent's tool use and where the tokens go

## Goal
Build a read-only report tool, `reality_engine/scripts/tool_usage_report.py`, that measures all tool use by Claude, dsh workers and OpenCode, so the controller can grade what can be saved. Run it on everything held. You measure and report the numbers; the controller does the grading.

## Sources (read-only; discover the real layout first, state what you found)
1. **dsh workers:** `C:\Users\warri\Downloads\Info_Diffusion_Model\plugins\dsh-worker\runtime\jobs\*\result.md.events.jsonl`. Lines: `{"type":"tool_call","callId","tool","input"}`, `{"type":"tool_result","callId","status","result"}`, plus `thinking`, `text`, `status`, `final`. Check `status.json` and `progress.jsonl` for tokens and timestamps.
2. **Claude Code (both accounts share it):** `C:\Users\warri\.claude\projects\**\*.jsonl`, including `subagents/` (26+ files, 160 MB). Stream line by line. `assistant` lines carry `message.content[].type == "tool_use"` and `message.usage` (`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`). Tool results are in `user` lines. **One API message is split over several lines with the same `message.id`: count usage once per id.** Split by session name prefix where it can be recovered (`sv-` Eagle, `neo-` Wolf).
3. **OpenCode:** `C:\Users\warri\.local\share\opencode\opencode.db` (with `-wal`, live). Copy the three files to `.tmp` and open the copy; never open the live file. Discover the schema (session/message/part or similar). Report model, tool, tokens and cost fields.
4. **Codex:** `C:\Users\warri\.codex\sessions` if it exists; otherwise report absent.
5. Direct Go API readers have no tool calls; report them as out of scope and name what would be needed to count them.

## Per source, per tool class
Report calls, failures, output chars, estimated tokens (chars/4), and **context-carry tokens** (output tokens × model steps remaining in that session, since each output is re-sent on every later step; state cached vs uncached where the source gives it). Report provider-reported tokens wherever available.

Classes: LSP navigation; LSP diagnostics; `.py` read whole file; `.py` read ranged; other file reads; shell file read; shell search; shell list/stat; inline Python DB query; inline Python other; `sql` tool query; schema probe (any route); other reality-data tools; tests/compile; bench or gate runs; git; edit/write; sleep/poll; web; subagent or worker control.

## Waste detectors (one count + token estimate each, formula stated)
a. Whole-file `.py` reads ≥200 lines where the job never edited that file; and where it did, the file's size vs the size of the edited function.
b. Shell reads/searches the read, grep or LSP tools could have served.
c. Inline DB queries the `sql` tool could have served.
d. Schema probes for a table already in `tasks/worker_context/schemas/`.
e. Identical commands repeated in one session; same script run ≥3 times in one session (with its elapsed time if known).
f. Failed calls and the retry that followed; top 15 failure signatures.
g. Consecutive read-only calls sent in separate model steps that could have gone in one parallel batch; report the steps saved.
h. Calls and seconds before the first edit, per job, with the distribution.
i. Tool outputs over 10,000 chars: count, tokens, top sources.
j. Sleep/poll calls and time.

Also report:
- **Before vs after** the 30 Oct 04:15 IST code-intel change. The only post-change job so far may be `20261030T173149Z-5d66898d`; say that n is small.
- Top 10 most expensive sessions per source.
- Share of each source's tokens by class.
- Thinking output vs visible output where given.

## Accuracy
Classification is by rules, so check it: print 30 random rows per major shell class to a sample file, re-read them yourself, and report the precision per class. Fix rules until each major class reaches ≥90%. State classes that do not.

## Privacy
Output aggregates and truncated command prefixes only. No message text, no document contents. Redact anything key-like (`sk-`, `Bearer`, long hex/base64, `token=`). Nothing from `Manual Dumps`.

## Deliverables
- `reality_engine/scripts/tool_usage_report.py` with `--since` and `--out`, plus a small fixture test in `reality_engine/tests/test_tool_usage_report.py`.
- `tasks/efficiency/TOOL_USAGE_2026-10-30.md` and `.json`; samples in `tasks/efficiency/samples_2026-10-30.md`.

## Rules
- Read-only outside the workspace. No installs, no network, no paid models, no DB writes.
- Use LSP (`module_map`, `symbols`, `definition`, `references`) for Python navigation, read/grep tools rather than pwsh for files, and `mcp__reality-data__sql` for DB queries. This run is itself measured.
- Keep RAM under 1.5 GB: stream the files; do not load them whole.

## Acceptance checks
- Fixture test passes, including the `message.id` dedupe.
- Claude totals are within 2% of a separate simple count for one chosen session (show both).
- Every source is reported, or explicitly marked absent.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_tool_usage_report.py -q
```

## Report
The headline table per source; each detector's count and tokens; precision per class; before vs after; anything you could not measure and why; code-intel calls vs grep/read/pwsh; calls before first edit.
