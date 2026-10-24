# code-intel — install steps (Claude runs these; the worker sandbox cannot)

Everything below is staged by Task 04. Nothing here is applied yet.

## 1. Language server (required)

```powershell
C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe -m pip install basedpyright --timeout 120 --retries 5
```

Verified from this network on 2026-10-24: `basedpyright 1.40.2` (13.7 MB wheel) and
`nodejs-wheel-binaries 24.19.0` (42.4 MB wheel, bundles `node.exe`); no Node install needed.
The worker could not run it — pip's user install is denied and site-packages is not writable
under the DSH file sandbox — so it installed the same wheels into `.tmp/lspvenv/` for
verification (gitignored, disposable). The server finds the language server in this order:

1. `CODE_INTEL_LANG_SERVER` (absolute path to `basedpyright-langserver[.exe]`)
2. `basedpyright-langserver` / `pyright-langserver` on `PATH`
3. `basedpyright.langserver` / `pyright.langserver` importable by the server's interpreter
   (the main Python, or `.tmp/lspvenv` / `.venv` inside the repo)

So the pip install above is enough even though the console script is not on `PATH`.
Check it:

```powershell
C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe -c "import basedpyright, json; print(json.dumps({'ok': True}))"
```

## 2. Claude Code — user scope (one command)

```powershell
claude mcp add-json -s user code-intel '{"type":"stdio","command":"C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe","args":["C:/Users/warri/Downloads/Info_Diffusion_Model/plugins/code-intel/server/server.py"],"env":{"CODE_INTEL_REPO_ROOT":"C:/Users/warri/Downloads/Info_Diffusion_Model","PYTHONUTF8":"1"}}'
```

Verified syntax against the installed CLI: `claude mcp add-json [options] <name> <json>`,
`-s/--scope` accepts `local|user|project`. Restart Claude Code afterwards.

## 3. Claude Code — project scope

`C:/Users/warri/Downloads/Info_Diffusion_Model/.mcp.json` — add this entry next to
`dsh-worker` and `reality-data` (staged verbatim in `code-intel.mcp.json.snippet`):

```json
"code-intel": {
  "type": "stdio",
  "command": "C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe",
  "args": ["C:/Users/warri/Downloads/Info_Diffusion_Model/plugins/code-intel/server/server.py"],
  "env": {
    "CODE_INTEL_REPO_ROOT": "C:/Users/warri/Downloads/Info_Diffusion_Model",
    "PYTHONUTF8": "1"
  }
}
```

`C:/Users/warri/Downloads/Info_Diffusion_Model/.claude/settings.local.json` — a project
`.mcp.json` server is not used until it is enabled:

```json
{
  "enabledMcpjsonServers": ["dsh-worker", "reality-data", "code-intel"]
}
```

(Keep every server already listed there; if the file does not exist, create it with that
one line.)

## 4. Claude Code — official LSP plugin (optional, different surface)

The official marketplace **does** ship one: `pyright-lsp@claude-plugins-official`
("Python language server (Pyright) for type checking and code intelligence", Anthropic,
v1.0.0). It declares:

```json
"lspServers": {"pyright": {"command": "pyright-langserver", "args": ["--stdio"],
                           "extensionToLanguage": {".py": "python", ".pyi": "python"}}}
```

```powershell
claude plugin install pyright-lsp@claude-plugins-official
```

It runs `pyright-langserver` from `PATH`, so with the step-1 install alone it will not
start. Either add the script directory to the user `PATH`:

```powershell
# console script installed by `pip install basedpyright` into the main Python (no --user)
$env:PATH = "C:/Users/warri/AppData/Local/Programs/Python/Python314/Scripts;$env:PATH"
```

…or install the `pyright` package instead, which ships a `pyright-langserver` script too.
This plugin and the code-intel MCP server are complementary, not alternatives: the plugin
gives Claude Code hover/diagnostics in its editor, code-intel gives the *model* callable
tools (and gives DeepSeek workers, who have no plugin surface, the same answers).

## 5. DeepSeek workers — dsh profiles

Staged block: `tasks/dsh_profiles/code-intel.insert.yml`. Merge its single list item into
the existing `- insert:` list of **both** profiles, directly after `mcp-reality-data`:

```text
C:/Users/warri/.dsh/profiles/headless/cordis.patch.yml
C:/Users/warri/.dsh/profiles/web/cordis.patch.yml
```

Back up first, then verify and restart dsh:

```powershell
Copy-Item C:/Users/warri/.dsh/profiles/headless/cordis.patch.yml C:/Users/warri/.dsh/profiles/headless/cordis.patch.yml.bak-20261024-code-intel
Copy-Item C:/Users/warri/.dsh/profiles/web/cordis.patch.yml      C:/Users/warri/.dsh/profiles/web/cordis.patch.yml.bak-20261024-code-intel
dsh --profile headless --dump-config | Select-String -Context 2,6 code-intel
dsh --profile web      --dump-config | Select-String -Context 2,6 code-intel
```

Worker tool names become `mcp__code-intel__definition`, `__references`, `__callers`,
`__symbols`, `__hover`, `__diagnostics`, `__module_map`. `toolCallTimeoutMs: 60000`
matches the cold-start worst case (first call after a restart can wait for the index).

## 6. Worker context (owned by Task 01)

Append `code-intel.worker_context.md` to whatever `tasks/worker_context/` lands as —
it is the "Use code-intel before grep" section with three examples.

## 7. Verify

```powershell
cd C:/Users/warri/Downloads/Info_Diffusion_Model
C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe -m unittest reality_engine.tests.test_code_intel -v
C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe plugins/code-intel/tests/acceptance_check.py
```

Expected: 13 tests OK (none skipped once the language server is installed) and
`ALL CHECKS PASSED` with the numbers in `plugins/code-intel/README.md`.
