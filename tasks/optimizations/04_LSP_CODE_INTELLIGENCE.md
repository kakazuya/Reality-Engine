# Task 04 — LSP code intelligence for Claude Code and for DeepSeek workers

Read `tasks/optimizations/00_SHARED_CONTEXT.md` first. Worktree task. Independent of Tasks 01–03: touch only
`plugins/code-intel/` (new), its tests, `pyrightconfig.json` (new, repo root), and staged config under
`tasks/dsh_profiles/` / `tasks/optimizations/install/`.

## Goal

Workers stop finding code by `grep` + reading whole files. They (and Claude) can ask: where is X defined, who calls
it, what symbols does this module expose, what are the type errors in my diff.

## Facts (checked 2026-10-24)

- No LSP anywhere today: no Claude Code LSP plugin installed, no `pyright` / `basedpyright` on the machine; the dsh
  harness has no LSP package (only `dsh-util-code-language`). Workers' tools: read, grep, glob, edit, write, pwsh,
  job_*, web_fetch, subagent, MCP tools (they already call MCP tools like reality-data via
  `@deepseek-ai/dsh-mcp-client`, configured in `C:\Users\warri\.dsh\profiles\{headless,web}\cordis.patch.yml`).

## Deliverables

1. **Language server**: install `basedpyright` (pip package bundles its own Node; preferred) or `pyright` into the
   main Python with `--timeout 120 --retries 5`; record the exact command for Claude if your sandbox blocks the
   install. `pyrightconfig.json` at repo root: include `reality_engine`, `plugins/*/server`; exclude data, runtime,
   worktrees, `.tmp`, venvs; `pythonVersion 3.14`; `typeCheckingMode "basic"`; extraPaths for the repo root.
   Measure: cold index time and memory on this repo (8-core laptop).
2. **MCP server `plugins/code-intel/server/server.py`** (stdio, same MCP SDK + style as
   `plugins/reality-data/server/server.py`; answer the handshake fast and warm the language server in a background
   thread, exactly like reality-data's 2026-10-24 fix). It runs one long-lived `basedpyright-langserver --stdio`
   process and exposes tools:
   - `definition(symbol | file+line+col)` → file:line + 5-line snippet;
   - `references(symbol | file+line+col, limit=50)` → file:line + the line text;
   - `symbols(file | query)` → module outline (classes/functions/methods with line numbers and first docstring line);
     workspace symbol search by name substring;
   - `hover(file, line, col)` → signature + docstring;
   - `diagnostics(files=[...] | changed=True)` → type/import errors for given files or the git-changed files;
   - `callers(function)` (references filtered to call sites) and `module_map(package)` (one-line purpose per module
     from docstrings) — cheap, high value for orientation.
   Every tool bounded (timeouts, result limits), returns paths relative to the repo root, never crashes the server
   (errors as `{ok:false,error}`), lifecycle log like reality-data (`.cache/lifecycle.log`). Restart the language
   server automatically if it dies.
3. **Registration** (staged; Claude installs — you cannot write user config):
   - Claude Code: user scope `claude mcp add-json -s user code-intel '{...}'` command + project `.mcp.json` entry +
     `enabledMcpjsonServers` line for `.claude/settings.local.json`; also check whether an official Claude Code Python
     LSP plugin exists in the plugin marketplace (`claude plugin` CLI / docs) and give the install command if so.
   - DeepSeek workers: a `dsh-mcp-client` insert block for both dsh profiles (same shape as `mcp-reality-data`, with
     `reconnect: {enabled: true, maxAttempts: 40}`, `toolCallTimeoutMs: 60000`), staged as
     `tasks/dsh_profiles/code-intel.insert.yml` + exact merge instructions.
   - A short section for `tasks/worker_context/` (Task 01 will include it): "Use code-intel before grep: …" with
     3 examples.
4. Tests `reality_engine/tests/test_code_intel.py`: tool shapes on a tiny fixture package in `./.tmp/` (definition,
   references, symbols, diagnostics on a file with one deliberate error); server handshake answers before warm-up
   completes; bounded output; missing language server → clear error not a crash. Skip (not fail) LSP-dependent
   tests when the binary is absent, but they must pass on this machine after install.

## Acceptance checks

1. On the real repo: `definition("connect_ro")` → `reality_engine/db/readonly.py:<line>`; `references("connect_ro")`
   lists ≥ 3 call sites incl. `plugins/reality-data/server/core.py`; `symbols("plugins/dsh-worker/server/core.py")`
   lists `start_worker`; `diagnostics(changed=True)` returns within 30 s.
2. MCP handshake answers in < 2 s on a cold start (measure like the reality-data test on 2026-10-24: send
   `initialize` over stdio and time the reply).
3. Index of the repo completes in < 2 min and the server stays < 1.5 GB RSS (report the numbers).
4. All new tests pass; install commands for Claude are exact and complete.

## Out of scope

Tasks 01–03. Don't modify existing plugins' code.

## Budget

≤ 25 tool calls before first edit; target ≤ 140 total; wall ≤ 60 min. No paid calls.
