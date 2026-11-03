# T-054 progress (DSH_WORKER_PROGRESS_NOTES was unset in this sandbox, so the file sits at the worktree root; drop it at merge)

- 2026-11-04: code-tools plugin written and wired (harness, HP patch, .mcp.json, pyrightconfig, context pack, progress prefixes); TOOL_INSTRUCTION rename; Evidence required with tests; docs, STATE and dsh_profiles updated. Next: final accept run, diagnostics, report. Blocker: pytest tmp_path denied in the sandbox (11 hp_worker errors) and the stdio test is skipped on the named-pipe block.
