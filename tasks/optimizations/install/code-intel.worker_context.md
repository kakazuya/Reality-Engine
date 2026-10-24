## Use code-intel before grep

The `code-intel` MCP tools run a basedpyright language server over this checkout, so you can
ask where code lives instead of grepping and reading whole files. One call replaces a search
plus a 500-line read; the language server already knows every import and call site.

- **Where is it defined, who calls it?** `definition("connect_ro")` → `reality_engine/db/readonly.py:119`
  with a 5-line snippet; `callers("connect_ro")` → the call sites only (imports filtered out).
  Use `references("connect_ro")` when you also want the import lines and tests.
- **What does this module expose?** `symbols("plugins/dsh-worker/server/core.py")` → every class,
  function and method with line numbers and the first docstring line (83 symbols in 0.1 s);
  `module_map("reality_engine/processing")` → one line of purpose per module, so you can pick
  the right file before opening any.
- **Is my diff type-clean?** `diagnostics(changed=True)` → type/import errors for the git-changed
  files (5 files in ~2 s), or `diagnostics(files=[...])` for specific ones. Run it before you
  report a task done.

Fall back to `grep` for text the language server does not index: config keys, YAML/JSON values,
SQL, log messages, data files. Everything that is a *symbol* — a function, class, method,
variable — is cheaper through code-intel.

If a tool answers `{ok: false, error: {code: "lsp_missing"}}`, the language server is not
installed: the fix is `python -m pip install basedpyright --timeout 120 --retries 5`, and
`symbols(file=...)`/`module_map(...)` still work without it.
