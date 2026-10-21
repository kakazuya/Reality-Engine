# Live provider checks — 2026-10-21

Shivam explicitly approved this small paid connectivity/control test, including non-DeepSeek Go calls, DeepSeek reasoning off/on, and one cheapest-model DeepInfra call. This is a one-off exception to normal paid-use restrictions. The current IST clock was off-peak; no timing confirmation was requested.

## Results from actual requests

| Route | Account | Controls observed on the wire | Result |
|---|---|---|---|
| OpenCode / LongCat 2.5 Preview Free | Go 1 | thinking disabled, max_tokens 64 | HTTP 200; expected answer |
| OpenCode / GLM-5.3-Flash | Go 2 | thinking disabled, max_tokens 128 | HTTP 400; upstream says disabling thinking is unsupported |
| OpenCode / GLM-5.3-Flash | Go 2 | high reasoning, max_tokens 512 | HTTP 200; expected answer; reasoning returned |
| OpenCode / GLM-5.3-Flash | Go 2 | low reasoning, max_tokens 64 | HTTP 200; expected answer |
| OpenCode / GLM-5.3-Flash | Go 2 | high reasoning, max_tokens 256 | HTTP 200; expected answer; reasoning returned |
| dsh / DeepSeek V4.1 Flash | Go 2 | thinking disabled, max_tokens 128 | HTTP 200; expected answer; no reasoning returned |
| dsh / DeepSeek V4.1 Flash | Go 2 | thinking enabled, xhigh, max_tokens 512 | HTTP 200; expected answer; trivial prompt used no reasoning |
| dsh / DeepSeek V4.1 Flash | Go 2 | thinking enabled, xhigh, max_tokens 1024 | HTTP 200; reasoning returned; nontrivial modular-arithmetic answer 7417 independently verified |
| DeepInfra / Mistral-Nemo-Instruct-2407 | DeepInfra key | max_tokens 16; 10 input + 4 output tokens used | HTTP 200; expected answer; reported cost $0.00000041 |

Caps above are the transmitted controls, accepted by successful requests. These were not stress tests intended to exhaust each cap. Reasoning text is not reproduced here.

Estimated Go usage cost, using returned usage/cached tokens and current published token rates: **$0.006406348**, plus the DeepInfra call, approximately **$0.00641 total**. This is a calculated estimate, not an account billing reconciliation. Failed local configuration attempts never reached the provider; two rejected auxiliary requests were stopped locally.

## Stable sessions and controls

The dsh wrapper sends a deterministic `go_session.session_id('dsh', model, key_env)` header. It was identical across off/on/xhigh tests.

OpenCode 2.1.1 overrides a configured x-opencode-session header with its native session ID. For reuse, pass `--session` with a deterministic ID derived from the shared helper, for example `ses_` plus the UUID with hyphens removed. The low-64/high-256 GLM requests used the same native session ID on the wire, and the second request retained conversation history. Merely configuring provider headers does not prove stable sessions for this CLI.

OpenCode v2 request controls work through provider/model request `body` fields: `max_tokens`, `thinking.type`, and `reasoning_effort`. Use the stock `build` agent. The custom probe agent was not registered through the tested config translation; switching to the stock agent resolved that local failure.

The DeepSeek wrapper now accepts `--max-output-tokens`, `--reasoning off|on` and an explicit `--smoke-test`. Normal runs remain xhigh; off/lower effort requires a bounded smoke test. `--smoke-test` requires a cap of 1–1024. Its localhost audit-proxy option refuses remote URLs. Node 24 is prepended for reliable dsh startup. Credentials remain environment references.

The audit caught dsh's automatic title plugin requesting 4096 tokens despite a smaller main-request cap. The local guard refused forwarding these auxiliary calls. The wrapper now disables LLM session titling whenever an explicit output cap is supplied; the final reasoning probe made only its capped main request.

Four local control tests pass: stable production defaults, account-separated session headers, bounded probe/title configuration, and changing caps without changing session routing.

Reproducible configs, whitelisted request controls, provider usage and local diagnostic output are retained under gitignored `reality_engine/data/logs/provider_probe_2026-10-21/`. The temporary audit server was closed after the tests. No account keys were printed or written into probe configs.

## DeepInfra model choice

Selected among active, public, nondeprecated text-generation models in the official metadata, ordered by the sum of standard input/output token prices. Mistral Nemo was cheapest under that equal-token comparison at $0.029 input / $0.030 output per million. Cheapest depends on input/output mix and service tier; this was a standard-tier connectivity call, not a task-quality recommendation.

Sources: [DeepInfra live model metadata](https://api.deepinfra.com/models/list), [Mistral Nemo pricing](https://deepinfra.com/mistralai/Mistral-Nemo-Instruct-2407), [OpenCode Go pricing/session guidance](https://opencode.ai/v2/docs/console/go/). Installed dsh package READMEs and the current OpenCode JSON schema were also inspected.

## Git and Claude connection

Fetched GitHub and fast-forwarded main from d62ef62 to **c980314**. Local changes and untracked H01 artifacts were preserved; HEAD matches origin/main. No push or stash.

Claude Desktop is installed. No Claude MCP tool is exposed to this chat, and no Claude Code CLI was found on PATH or in the standard checked CLI locations. The existing advisor route remains a dated question in `tasks/codex_tasks/ask_claude.md` relayed by Shivam. No Claude inference request was made during this check; the user reports its weekly usage is 95%.
