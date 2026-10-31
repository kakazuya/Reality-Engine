# Task — code-intel: fix stale symbol lookups and give dsh workers a CLI

## Goal
Two defects found on 30 Oct 2026:
1. **Stale lookups.** After `router.py` changed on disk (git merges), `definition("period_bounds")` returned line 210 (true: 219), and `references("period_bounds")` returned router.py lines 406/469 (true: 487/554), whose text was a docstring line. The language server keeps the text it was first given, and nothing tells it when a file changes on disk (git merges, worker edits, other sessions). Outlines (`symbols(file=…)`) and `diagnostics` were correct because they re-read the file.
2. **Workers can't use it.** Across every dsh job on record, workers made 0 code-intel calls. Their harness only has edit/pwsh/read/write, not MCP. Meanwhile workers spent 25–77 tool calls orienting before their first edit.

Fix both. Then measure.

## Inputs
- `plugins/code-intel/server/core.py`: the `_opened` map near line 135 and `_sync`/didOpen/didChange near lines 290–310; `definition`, `references`, `symbols`; the cold-index wait.
- `plugins/code-intel/README.md`, `plugins/code-intel/tests/`, `plugins/code-intel/server/.cache/lifecycle.log`.
- `tasks/worker_context/CONTEXT.md` and its builder (find it via the dsh-worker plugin: the context-pack generator). Read only; see Rules.

## Do
1. **Freshness.** Before every position or name query (definition, references, hover, workspace symbol), make the server's view of each relevant file match the disk:
   - track mtime + size (or a content hash) per file;
   - send a full-text `didChange` for changed files;
   - for name lookups (workspace/symbol), first sync the files changed since the last call — use `git diff --name-only` against the last-seen HEAD, plus the mtime of tracked `.py` files under the include roots, kept cheap.
   - If correctness cannot be guaranteed, prefer answering from an `ast` index with mtime invalidation over returning a stale position.
2. **Regression test:** copy a small module to a temp include path, query a symbol, insert 9 lines above it on disk (no editor event), query again, and assert the new line. Do the same for `references`.
3. **CLI for workers:** `python -m plugins.code_intel.cli <definition|references|symbols|outline|diagnostics|module_map> …` or a `plugins/code-intel/ci.py` script.
   - Output is JSON on stdout. It works from PowerShell inside a dsh worktree, with paths relative to that worktree's root.
   - Fast paths must not need the language server: outline, module_map, name definition and references from an `ast` + text index with mtime invalidation, cached on disk under the worktree `.tmp` (`<0.5 s` warm).
   - `diagnostics` may start basedpyright (state its cold cost).
   - It must run inside the dsh sandbox: test it from this worker's own shell, and if the sandbox blocks something, report exactly what.
4. Write a short "How to use from a dsh worker" section in `plugins/code-intel/README.md`: 6 example commands, including one that replaces a grep + read.
5. **Measure:**
   - Run the CLI against 5 real questions a worker asked tonight (e.g. where `period_bounds` is defined and every caller; the outline of `planners/screen.py`; who reads `company_sector_pit`; the `envelope` signature; diagnostics on `screen.py`).
   - Report wall time and the equivalent number of grep/read calls it replaces.

## Rules
- Write only `plugins/code-intel/**` (code, tests, README).
- Do NOT edit the dsh-worker plugin, the context-pack builder, or `tasks/worker_context/*`. Instead, report the 3–5 lines the controller should add to the worker standing header.
- No installs (basedpyright is already installed). No paid models.
- Keep the MCP tool signatures backward compatible.

## Acceptance checks
- `python -m pytest plugins/code-intel/tests -q` passes (or the repo's existing runner for those tests), including the new freshness test.
- The CLI answers `definition period_bounds` with `reality_engine/query/router.py:219` on the current main.
- The README has the worker usage section.

## Test command(s)
```bash
python -m pytest plugins/code-intel/tests -q
```

## Report
- The root cause, as confirmed.
- What changed.
- The freshness test.
- The CLI commands and their timings.
- The sandbox findings.
- The standing-header lines for the controller.
- Tool-call count.
