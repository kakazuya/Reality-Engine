# code-tools

Run-and-exit code tools for dsh workers. Replaces the code-intel language
server (retired 4 Nov 2026, T-054: a resident `basedpyright-langserver` cost
~800 MB per worker and code-intel was 1.5% of 28,787 tool calls). Nothing here
stays resident between calls.

| tool | what it does |
|---|---|
| `outline(file)` | every class / function / method with `name`, `kind`, `line`, `end_line`, parent class and first docstring line, from Python `ast` |
| `typecheck(files)` | one `basedpyright --outputjson` run with the repo's `pyrightconfig.json`, 120 s cap; returns `{errors: [{file, line, message}], error_count, seconds}` |

Both are read-only. Paths resolve against `CODE_TOOLS_ROOT` (the worker's
checkout; the MCP server is started with it set, the CLI defaults to the current
directory).

## CLI

```bash
python plugins/code-tools/ct.py outline reality_engine/pilot3/kpi.py
python plugins/code-tools/ct.py typecheck reality_engine/pilot3/build.py
```

JSON on stdout; exit 1 with `{"ok": false, "error": ...}` when the file is
missing or basedpyright cannot run.

## Test

```bash
python -m pytest plugins/code-tools/tests -q
```
