# Claude Code CLI setup — 2026-10-21

- Installed with Anthropic's official Windows command, `irm https://claude.ai/install.ps1 | iex`, in a verified non-admin PowerShell process.
- Native version verified: **2.1.305**. Launcher: `C:/Users/warri/.local/bin/claude.exe`. Its directory was added to the user's PATH without changing other entries.
- Launched a visible terminal running `claude auth login --claudeai`. The launch environment excludes `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, and third-party provider flags, to select subscription login instead of API billing. Persistent credentials/settings were not read or changed by this launcher.
- Last filtered auth check: `loggedIn=false`, `authMethod=none`. Browser sign-in is pending Shivam's action. No Claude model request has been made.
- After sign-in, verify `claude auth status` in the same cleaned environment, printing only method/login/subscription fields. Advisor calls should use `-p`, `--model opus`, `--effort medium` and subscription authentication. Current reported weekly usage is 95%; keep requests short and targeted.
- Each advisor brief must explicitly name the files to review and supply the relevant current context, including FRAMEWORK, STATE, the relevant H01 artifacts and standing-memory references. Do not assume a fresh CLI session shares the Desktop conversation or automatically loads arbitrary AGENTS/memory folders.

## Ollama check

No Ollama-named environment settings were found at process, user or machine scope, including `OLLAMA_API_KEY`, `OLLAMA_CLOUD_API_KEY`, and `OLLAMA_KEY`. Therefore no authenticated Ollama inference request was made. The PC's key has not been recovered from secret files or archives.

Ollama's current official listing identifies the requested model as `minimax-m3.1-flash` for direct cloud API requests (`minimax-m3.1-flash:cloud` for the Ollama CLI). A working laptop API key is required before testing. The public listing shows token prices; Shivam's account-specific free-through-22-Oct promotion has not been independently verified.

Sources: [Claude native Windows installation](https://code.claude.com/docs/en/setup), [Claude CLI login flags](https://code.claude.com/docs/en/cli-reference), [Ollama MiniMax model](https://ollama.com/library/minimax-m3.1-flash%3Acloud).
