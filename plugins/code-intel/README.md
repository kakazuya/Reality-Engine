# code-intel — LSP code intelligence for Claude Code and DeepSeek workers

Ask the language server instead of grepping and reading whole files: where is X
defined, who calls it, what does this module expose, what are the type errors in
my diff. One long-lived `basedpyright-langserver --stdio` child answers every
tool call; `definition`/`references`/`hover`/`symbols(query)`/`diagnostics` go
through LSP, the module outline and module map read the file with `ast` (instant,
and they work before the server has warmed).

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

## Measured on this box (2026-10-24, 8-core laptop)

| What | Number |
|---|---|
| Program size | 362 Python files in `reality_engine` (+ ~60 in the plugin servers) — pyright logs "Found 362 source files" for `reality_engine` alone, which is how the `plugins/*/server` glob bug was caught |
| Cold start (language server up + first parse) | 2.8 s / 8.1 s / 9.6 s across three runs (machine-load dependent), budget 2 min |
| `definition("connect_ro")` | 4.9 s when it is the first call, 0.4 s warm → `reality_engine/db/readonly.py:119` |
| `references("connect_ro")` | 11 sites in 5 files, 0.4 s (includes `plugins/reality-data/server/core.py`) |
| `symbols("plugins/dsh-worker/server/core.py")` | 83 symbols in 0.1 s, `start_worker` listed with container `Manager` |
| `diagnostics(changed=True)`, 5 changed files | 2.0–3.2 s (budget 25 s) |
| MCP handshake, cold | 1.9 s best, 2.1–2.7 s otherwise; `import mcp.server` alone measures 1.9–3.2 s on this box and reality-data's handshake measures 2.4–3.2 s the same way, so the reply is at the protocol floor and the warm-up adds nothing |
| Language server RSS | 606 MB node + ~30 MB launcher python (total 686 MB when the acceptance run's other new processes are counted) |

## Known gaps

- `diagnostics` uses pyright's `openFilesOnly` mode, so each file is opened (a
  full-text `didChange` when it is already open) and the answer waits for that
  file's `publishDiagnostics`. A file pyright refuses to analyse (e.g. syntax
  error in an import) comes back as an `lsp_timeout` error instead of a guess.
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
