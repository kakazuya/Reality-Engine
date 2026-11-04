# Worker: HP workers can serve a profile database

Goal: an HP worker's `reality-data` MCP can serve the 10-company database, so answer runs and later jobs use the idle HP. `python -m reality_engine.scripts.hp_worker start <brief.md> --pilot-db <local path> ...` copies that file to the HP and sets `REALITY_PILOT3_DB` for the job.

Ticket: T-070

Evidence: read by Opus on 5 Nov.
- `reality_engine/scripts/hp_worker.py:302` `mcp_patch(home, paths)` writes the `mcp-reality-data` entry; its `env` block (about line 318) has only `REALITY_DATA_ROOT`, `REALITY_DATA_REPO_ROOT` and `PYTHONUTF8`.
- `plugins/reality-data/server/lookups_pilot3.py:46` and `:89`: with `REALITY_PILOT3_DB` set, the tools read that file and take their companies from its `company` table; unset, only three companies are accepted.
- `hp_worker.py:485` `sync_dbs(names)` copies names under `DATA_ROOT` to `C:\RE\data` once and re-copies only when the local file is newer, using `stage_db` (`:462`). `D:\RealityEngine\pilot10\pilot10.db` is outside `DATA_ROOT`. The parser is at `:1060`; `start` at `:549`; `cmd_start` at `:650`.
- The MSI profile sets the same variable: `~/.dsh/profiles/headless/cordis.patch.yml` line 42. Do not edit that file.

Do: add `--pilot-db PATH` to `hp_worker start`, pass it through `start`, copy the file with the existing staging and meta logic to `C:\RE\data\<basename>`, and add `REALITY_PILOT3_DB: C:/RE/data/<basename>` to that job's MCP `env`. Without the flag the patch is byte-for-byte what it is today. Refuse a path that does not exist.

Files: `reality_engine/scripts/hp_worker.py`, `reality_engine/tests/test_hp_worker.py`, the worker section of `machines/HP_LAPTOP.md`, your line in `docs/DEVELOPER_GUIDE.md`. Do not touch `tasks/STATE.md`.

Accept:
1. `python -m pytest reality_engine/tests/test_hp_worker.py -q`, with new tests: the flag adds the env line; no flag leaves the patch unchanged; a missing path is refused.
2. `mcp__code-tools__typecheck` on the changed files: no new errors.

Rules: do not start an HP job and do not ssh to the HP: Opus runs the first real job. Do not touch the main checkout, `~/.dsh/profiles` or any running job's folder.

Stop if: the copy cannot reuse `stage_db` and the meta logic; report why.

Budget: 20 tool calls. End with what changed, test results, and a `Docs updated:` line.
