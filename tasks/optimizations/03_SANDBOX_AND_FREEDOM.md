# Task 03 — Give workers working tools: sandbox fixes, dependencies, data-writer mode, first-edit metric

Read `tasks/optimizations/00_SHARED_CONTEXT.md` first. Shivam (2026-10-25): "give them more freedom in their tools
and write/edit commands so they can work without wasting 70% of the time on workarounds and dependencies."
Worktree task, touching `plugins/dsh-worker/server/` (you own `supervisor.py` env/sandbox setup, the permission
modes in `core.py` start params, and new files; Task 01 owns brief assembly in `start_worker` — keep your `core.py`
edits to parameters/validation and the job record).

## Goal

A worker can install what it needs, use a temp dir, write where its task is approved to write, and commit — without
workarounds. Measure how long orientation takes so we can see the improvement.

## Deliverables

1. **Understand the current sandbox first** (≤ 15 calls): how `permission` (read-only / workspace-write / full access
   names as the code calls them) maps to dsh sandbox settings — read `core.py` start_worker, `supervisor.py` launch,
   the dsh profile `C:\Users\warri\.dsh\profiles\headless\cordis.patch.yml` and the dsh packages' sandbox options in
   `C:\Users\warri\.bun\install\cache\@deepseek-ai\` (search names containing `sandbox`, `pwsh-sandbox`,
   `file-sandbox`, `permission`). Write the mapping into `tasks/worker_context/SANDBOX.md` (Task 01 includes it).
2. **Temp dir**: the supervisor creates `<workspace>/.tmp/` per job and sets `TMP`, `TEMP`, `TMPDIR`,
   `npm_config_cache=<.tmp>/npm-cache`, `PIP_CACHE_DIR=<.tmp>/pip-cache`, `UV_CACHE_DIR`, `PYTHONPYCACHEPREFIX`
   for the worker process; `.tmp/` gitignored (root `.gitignore` + worktrees). Verify `tempfile.mkdtemp()` works in a
   live sandboxed worker (this failed on 2026-10-24).
3. **Dependencies**: `requirements-worker.txt` at repo root with what workers repeatedly needed (pymupdf, pyyaml,
   requests, numpy, pandas, duckdb, rapidocr / rapidocr-onnxruntime only if a 3.14 wheel exists, openpyxl, xlrd,
   pytest-free; check each has a cp314 Windows wheel; list the ones that don't). A script
   `reality_engine/scripts/setup_worker_env.py` that installs them into the main Python (user site) with
   `--timeout 120 --retries 5`, idempotent, prints what changed. Pip/uv config file so workers inherit the timeouts.
   Also allow per-task venvs under `<workspace>/.venv-*` (gitignored) and document it.
4. **Write freedom by mode** (new `start_worker` param `write_scope`, default `"workspace"`):
   - `"workspace"`: as today + `.tmp`.
   - `"data"`: additionally writable `REALITY_DATA_ROOT` (`reality_engine/data`) and `D:\RealityEngine` — for
     approved data jobs; requires `confirm_data_write=true`; the supervisor takes the existing named locks
     (`db:<file>` for each DB the brief lists in a new `writes=[...]` param) so two writers never share a DB; records
     the scope in the job record and in progress digests.
   - `"full"`: the dsh danger/full-access mode where the platform supports it (never default; requires
     `confirm_full_access=true`; Claude asks Shivam before using it).
   Implement via whatever the dsh sandbox config supports (extra writable roots, or permission profile per job); if
   the dsh profile must change, stage it in `tasks/dsh_profiles/` (headless + web) and give Claude the install steps —
   you cannot write `~/.dsh`. Also fold in the already-staged pwsh timeout (`timeoutMs 600000`, consider
   `promoteOnTimeout: false`) from `tasks/dsh_profiles/README.md`.
5. **Worktree commits**: make `git commit` work from inside a worktree job (the index/objects live in the main repo's
   `.git/worktrees/<id>` — add that path to the job's writable roots, or have the supervisor run the commit on the
   worker's request via a small command). The OCR worker on 2026-10-24 could not commit (blocked index write).
6. **Long-running processes**: a supported way for a worker to launch a detached background process that survives its
   own shell (e.g. a `launch_detached(cmd, log)` helper the supervisor runs via WMI `Win32_Process.Create`, logging
   pid + command to the job record), restricted to `write_scope="data"`/`"full"` jobs.
7. **Metric**: progress digests and the final job record gain `tool_calls_before_first_edit` (first `edit`/`write`
   event index) and `orientation_seconds`; `list_workers` shows it. Backfill it for the 2026-10-24 jobs from their
   events files into `tasks/worker_context/orientation_baseline.json` (job, task, calls before first edit, total
   calls, wall) — this is the "before" baseline.

## Acceptance checks

1. In a real sandboxed demo job (fake launcher or a tiny real worker): `tempfile.mkdtemp()`, `pip install --target
   .tmp/x <tiny pkg>`, `npx --version` all succeed with caches inside `.tmp/`.
2. `write_scope="data"` without `confirm_data_write` → refused; with it → the demo can create a file under
   `reality_engine/data/_sandbox_probe/` and a second data job naming the same DB is refused (`resource_busy`).
3. A worktree demo job can `git commit` its change itself.
4. `tool_calls_before_first_edit` appears in progress.jsonl, status and list_workers; baseline JSON written with
   ≥ 10 jobs from 2026-10-24.
5. dsh-worker suite passes (73 + yours); `setup_worker_env.py --dry-run` lists packages and wheel availability.
6. Report lists every file Claude must copy/install outside your sandbox (profiles, pip config) with exact commands.

## Out of scope

Context pack + brief template (01), toolbelt (02), LSP (04). Never enable jobs.yaml jobs; never run data jobs.

## Budget

≤ 25 tool calls before first edit (step 1 is your orientation and is capped at 15); target ≤ 160 total;
wall ≤ 75 min. No paid calls.
