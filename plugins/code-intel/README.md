# code-intel — LSP code intelligence for Claude Code and DeepSeek workers

Ask the language server instead of grepping and reading whole files: where is X
defined, who calls it, what does this module expose, what are the type errors in
my diff. One long-lived `basedpyright-langserver --stdio` child answers every
tool call; `definition`/`references`/`hover`/`symbols(query)`/`diagnostics` go
through LSP, the module outline and module map read the file with `ast` (instant,
and they work before the server has warmed).

Two 2026-10-30 fixes: before every position or name query the server is given the
disk's current text for anything that changed (a git merge or another session's
write never arrives as an editor event), and when its index still answers a stale
line the tool falls back to the mtime-invalidated ast index instead of returning
it. dsh workers, whose harness has no MCP, get the same answers from
`plugins/code-intel/ci.py` — see [How to use from a dsh worker](#how-to-use-from-a-dsh-worker).

## Tools

| Tool | Purpose |
|---|---|
| `definition(symbol=`\|`file,line,col)` | Where a symbol is defined: file:line + 5-line snippet. |
| `references(symbol=`\|`file,line,col, limit=50)` | Every use (declaration excluded), sorted by file then line, capped at 500. |
| `callers(function, limit=50)` | References filtered to call sites: imports and the definition are dropped. |
| `symbols(file=`\|`query)` | Module outline (classes/functions/methods, line numbers, first docstring line) or workspace symbol search by name substring. |
| `hover(file, line, col=1)` | Signature + docstring at a position (1-based line/col). |
| `diagnostics(files=[...]` \| `changed=True)` | Type/import errors for the listed files or the git-changed ones (max 20 files, 100 per file, ~25 s budget). |
| `module_map(package)` | One line of purpose per module from its docstring. |

Every path returned is relative to the repo root. Every tool is bounded (request
timeout 30 s, `diagnostics` 25 s, result caps) and errors come back as
`{ok: false, error: {code, message}}` — never an MCP protocol failure. On a dead
language server the next call restarts it once and retries.

## How to use from a dsh worker

A dsh worker has `pwsh`, `edit`, `read`, `write` — not MCP. `ci.py` is the same
code intelligence from a shell: JSON on stdout, paths relative to the worktree
you are standing in. Run it from the worktree root:

```powershell
# 1. where is it defined — replaces grep + read of the module
python plugins/code-intel/ci.py definition period_bounds
# -> {"ok":true,...,"definitions":[{"file":"reality_engine/query/router.py","line":219,...}]}

# 2. every mention and call site with its line text — replaces grep -n + a read per hit
python plugins/code-intel/ci.py references period_bounds --limit 50

# 3. a module's classes/functions/methods with line numbers — replaces reading the whole file
python plugins/code-intel/ci.py outline reality_engine/query/planners/screen.py

# 4. who reads a table, column or constant, SQL strings included — the grep + read replacement
python plugins/code-intel/ci.py references company_sector_pit

# 5. one line of purpose per module in a package — replaces listing + opening every file
python plugins/code-intel/ci.py module_map reality_engine/query

# 6. type/import errors on one file — the only command that starts basedpyright (~3 s cold)
python plugins/code-intel/ci.py diagnostics reality_engine/query/planners/screen.py
```

- stdout is one JSON object; exit 0 on success, 1 with `{"ok": false, "error": {...}}`.
- `--root <dir>` (before the subcommand) points at another checkout; the default is
  the checkout the script lives in.
- Commands 1–5 read an mtime-invalidated ast index cached in
  `<root>/.tmp/code-intel-index.json` (`.tmp/` is gitignored): ~3.5 s once per
  checkout, ~0.2–0.3 s warm. No language server is involved.
- `diagnostics` starts `basedpyright-langserver` (~3 s on this box, then ~1 s per
  file); a file outside `pyrightconfig.json`'s `include` comes back in `skipped`
  instead of burning the budget on a timeout no diagnostic will ever answer.
- Freshness is not optional: every disk edit (worker write, `git merge`, another
  session) is detected by `(mtime, size, ctime)` and, for name queries, by a moved
  `git HEAD`, and re-sent to the server before the answer is computed.

Measured 2026-10-30 on this box, warm cache, six real worker questions:

| Question | Command | Wall | Equivalent grep/read calls |
|---|---|---|---|
| where is `period_bounds` defined | `definition period_bounds` | 0.31 s → `router.py:219` | 2 (`grep -n` + `read`) |
| every caller of `period_bounds` | `references period_bounds` | 0.22 s → 16 hits in 5 files | ~5 (grep + a read per file) |
| outline of `planners/screen.py` | `outline ...` | 0.20 s → 17 symbols, 795 lines | 1 read of 795 lines |
| who reads `company_sector_pit` | `references company_sector_pit` | 0.29 s → 44 hits in 10 files | ~11 (grep + up to 10 reads) |
| the `envelope` signature | `definition envelope` | 0.22 s → `planners/__init__.py:14` | 2 |
| type errors on `screen.py` | `diagnostics ...` | 3.2 s (cold) → 4 errors | not reachable with grep/read |

## Install

The language server is the only external piece:

```powershell
C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe -m pip install basedpyright --timeout 120 --retries 5
```

Discovery order: `CODE_INTEL_LANG_SERVER` (full path to `basedpyright-langserver`
or `pyright-langserver`) → `basedpyright-langserver`/`pyright-langserver` on
`PATH` → `basedpyright.langserver` / `pyright.langserver` importable by the
running interpreter or by `.tmp/lspvenv` / `.venv` in the repo. With no language
server the LSP tools answer `{ok: false, error: {code: "lsp_missing", install:
...}}` and the `ast` tools keep working.

`pyrightconfig.json` at the repo root is the program definition (see below).

## Run / test

```powershell
# stdio server (normally launched by the host)
C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe plugins/code-intel/server/server.py

# unit + end-to-end tests (skips the LSP ones when no language server is installed)
C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe -m unittest reality_engine.tests.test_code_intel -v

# freshness + CLI: a disk edit with no editor event must move the answer
python -m unittest discover -s plugins/code-intel/tests -p "test_*.py" -v
python -m pytest plugins/code-intel/tests -q        # same tests, if pytest is installed

# acceptance: definition/references/symbols/diagnostics + handshake/index/RSS numbers
C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe plugins/code-intel/tests/acceptance_check.py

# lifecycle + language-server stderr (gitignored)
Get-Content plugins/code-intel/server/.cache/lifecycle.log -Tail 5
```

## pyrightconfig.json

`include`: `reality_engine` plus the three `plugins/*/server` directories —
**explicitly**, because a `plugins/*/server` glob in `include` is accepted but
silently matches nothing (measured: 362 files found = `reality_engine` only).
`exclude`: data, runtime, `.tmp`, venvs, caches, worktrees, build outputs.
`pythonVersion: "3.14"`, `typeCheckingMode: "basic"`, `extraPaths: ["."]`, and
one `executionEnvironments` entry per plugin server dir so their co-located
`import core` resolves to the right module instead of a sibling plugin's.

## Registration

Staged by the worker (it cannot write user config):

- Claude Code user scope and project scope: `tasks/optimizations/install/code-intel.install.md`.
- dsh `headless` + `web` profiles: `tasks/dsh_profiles/code-intel.insert.yml`.
- Worker prompt section: `tasks/optimizations/install/code-intel.worker_context.md`.

Anthropic's official marketplace also ships `pyright-lsp`
(`claude plugin install pyright-lsp@claude-plugins-official`), which wires the
language server into Claude Code's own editing surface. It needs
`pyright-langserver` on `PATH`; this plugin's MCP server needs the same binary
but finds it through the importable package, so installing `basedpyright` covers
both only if the console script is on `PATH` — see the install doc for the exact
two-line fix.

## Measured on this box (2026-10-24, 8-core laptop; 2026-10-30 rows marked)

| What | Number |
|---|---|
| Program size | 362 Python files in `reality_engine` (+ ~60 in the plugin servers) — pyright logs "Found 362 source files" for `reality_engine` alone, which is how the `plugins/*/server` glob bug was caught |
| Cold start (language server up + first parse) | 2.8 s / 8.1 s / 9.6 s across three runs (machine-load dependent), budget 2 min; **6.1–7.9 s on 2026-10-30** |
| `definition("connect_ro")` | 4.9 s when it is the first call, 0.4 s warm → `reality_engine/db/readonly.py:119` |
| `references("connect_ro")` | 11 sites in 5 files, 0.4 s on 2026-10-24; **64 sites in 19 files on 2026-10-30** (the repo grew) |
| `symbols("plugins/dsh-worker/server/core.py")` | 83 symbols in 0.1 s, `start_worker` listed with container `Manager`; 89 on 2026-10-30 |
| `diagnostics(changed=True)`, 5 changed files | 2.0–3.2 s (budget 25 s); **0.7 s for 1 changed file on 2026-10-30** |
| Freshness sweep per position/name query (2026-10-30) | 25 ms (`stat` sweep of 500 files) + 20 ms (`git rev-parse HEAD`), nothing pushed when the disk is unchanged |
| Ast index warm/cold (2026-10-30) | 55 ms read + 25 ms sweep warm; 3.8 s to build 500 files / 9 MB once per checkout |
| CLI, 6 worker questions (2026-10-30) | 0.20–0.31 s warm (definition, references, outline, module_map); `diagnostics` 3.2 s cold |
| MCP handshake, cold | 1.9 s best, 2.1–2.7 s otherwise; `import mcp.server` alone measures 1.9–3.2 s on this box and reality-data's handshake measures 2.4–3.2 s the same way, so the reply is at the protocol floor and the warm-up adds nothing |
| Language server RSS | 606 MB node + ~30 MB launcher python (total 686 MB when the acceptance run's other new processes are counted); 853 MB total on 2026-10-30 |

## Known gaps

- Freshness is a sweep, not a filesystem watcher: a file changed after the sweep
  but before the answer is only caught on the next call. The sweep is one
  `os.scandir` + `stat` pass over the include roots (25 ms for 500 files) plus a
  `git rev-parse HEAD`, so it runs before every position/name query rather than
  being throttled. When the server's index answer still points at a line that does
  not hold the name, `definition`/`references`/`symbols(query)` answer from the ast
  index and say `"source": "ast"` (the ast index covers the pyright include roots
  plus `plugins/code-intel`; a name outside them still answers `"stale": true`).
- `diagnostics` uses pyright's `openFilesOnly` mode, so each file is opened (a
  full-text `didChange` when it is already open) and the answer waits for that
  file's `publishDiagnostics`. A file pyright refuses to analyse (e.g. syntax
  error in an import) comes back as an `lsp_timeout` error instead of a guess, and
  a file outside `pyrightconfig.json` `include` is listed in `skipped` (pyright
  never publishes diagnostics for it).
- The CLI's `references` is a whole-identifier text match: it includes the
  definition line and matches inside strings/comments (which is what makes it a
  `grep` replacement). The MCP `references` tool is the language-server one and
  excludes the declaration.
- `mcp.server` / `mcp.types` show up as unresolved imports in
  `diagnostics(files=["plugins/*/server/server.py"])`. That is the repo's
  existing state (`plugins/reality-data/server/server.py` reports the same two
  warnings) — pyright does not see the harness's `mcp` package. Only warnings.
- Reference/definition positions assume ASCII columns (LSP columns are UTF-16
  code units). A non-ASCII line before the symbol on the same line shifts the
  column by one per astral character.
- `callers` is a line heuristic (`name(` present, no `from`/`import` prefix), so
  a function passed as a callback (`map(helper, xs)`) is listed but a call split
  across lines is not.
- The language server is per-MCP-server: Claude and each dsh profile get their
  own process (~640 MB each) if they run at the same time.
- `mcp.server` / `mcp.types` show up as unresolved imports in
  `diagnostics(files=["plugins/*/server/server.py"])`. That is the repo's
  existing state (`plugins/reality-data/server/server.py` reports the same two
  warnings) — pyright does not see the harness's `mcp` package. Only warnings.
- Reference/definition positions assume ASCII columns (LSP columns are UTF-16
  code units). A non-ASCII line before the symbol on the same line shifts the
  column by one per astral character.
- `callers` is a line heuristic (`name(` present, no `from`/`import` prefix), so
  a function passed as a callback (`map(helper, xs)`) is listed but a call split
  across lines is not.
- The language server is per-MCP-server: Claude and each dsh profile get their
  own process (~640 MB each) if they run at the same time.
