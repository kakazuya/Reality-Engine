# Orchestrating OpenCode headlessly (how Claude drives the OpenCode accounts)

Written 2026-10-13 after two days of running the annual-report (AR) and deck readers through OpenCode. Read this before
touching anything OpenCode-related. Companion files:
- `tasks/ar_study/READER_FINDINGS.md`: which models passed, and the quotas.
- `reality_engine/scripts/reader_profiles.json`: per-model prompt, piece size, limits and slots.
- `reality_engine/scripts/zen_models.json`: register of passed Zen models.

## 1. Install: bun only (Shivam 2026-10-13)

- **Install / update:** `bun add -g @opencode/cli` (v2.x).
  - The binary is `~/.bun/install/global/node_modules/@opencode/cli/bin/opencode.exe`; the shim is `~/.bun/bin/opencode.exe`.
  - Do **not** use npm. npm 12 and bun both block package postinstall scripts; without the postinstall, `opencode.exe`
    is a ~229-byte placeholder and Windows reports "16-bit application" / "not a valid application".
- **The trust setting:** bun's fix is `bun pm -g trust @opencode/cli`, done 2026-10-13. It is recorded under
  `trustedDependencies` in `~/.bun/install/global/package.json`, so updates now run the postinstall.
  - If the binary is ever < 1 MB again, run `bun pm -g trust @opencode/cli`.
  - `ar_queue.opencode_exe()` refuses binaries under 1 MB.
- **npm copies removed 2026-10-13** (`npm uninstall -g @opencode/cli opencode-ai`).
- **Auth, config and sessions** live in `~/.local/share/opencode` and `~/.config/opencode`, shared by any install.

## 2. The background service, and why no OpenCode window is needed

- **The service:** OpenCode v2 runs a background service (`opencode serve --service`, e.g. `http://127.0.0.1:49374`;
  `opencode service status|start|stop`). Every `opencode run` connects to it and starts it if needed.
- **The TUI is just a client.** Closing it changes nothing for the pipeline.
- **Everything is driven from scripts:**
  - **One headless call:** `opencode run -m opencode/<model> --title "<label>" "<instruction>" -f <file> [-f <image>]`
    with **stdin = DEVNULL**; without it, `run` can wait forever.
    - Put the instruction **before** `-f`.
    - Attached files reach the model whole (checked with a 4,000-line file), so long prompts go in a file.
    - Read the answer from stdout; strip ANSI codes and the `> build · <model>` lines.
    - Python examples: `ar_queue.read_piece()` and `extract_deck_figures.Client._post_cli()`.
    - Call `opencode.exe` directly, not the `.cmd`/`.ps1` shims, so a timeout can kill it.
  - **Talk to an existing session:** `opencode run -s <session-id> "<message>"`. It returns when that turn ends, so
    run it as a background job and its completion wakes Claude.
  - **Read any session**, including turns the user typed: `opencode session export <id>` (JSON).
    `opencode session list` lists sessions.
  - **New collaborator session:** `opencode run -m opencode/<model> --title "<title>" "<brief>"`.
- **Other useful commands:**
  - `opencode models` lists models per provider. `opencode/*` = Zen, `opencode-go/*` = Go, `kilo/*`.
  - `opencode stats --days 0 --models --cost --json` shows token usage per model, the only usage view.
  - `opencode auth list | login` manages credentials. Claude must never type keys; the user runs `auth login`.
  - `opencode debug config | paths`.
- **Every `opencode run` creates a session.** Hundreds of `ar-queue …` / `deck …` sessions are normal and can be deleted.

## 3. Zen (free models) vs Go (subscription)

| | OpenCode Zen free tier (`opencode/<model>`) | OpenCode Go (`opencode-go/…` or API) |
|---|---|---|
| How to call | **only inside OpenCode**: `opencode run` with the **stock agent**. Direct API calls get 403 "free tier can only be used from within OpenCode"; custom agent prompts (`.opencode/agents/*.md`) are refused the same way | direct API: `POST https://opencode.ai/zen/go/v1/chat/completions` with `Authorization: Bearer <key>` **and an `x-opencode-session: <uuid>` header** (without it: 400 MissingSessionID) |
| Limit | **one daily allowance per machine/IP**, shared by all models and both accounts: ~1,800 calls / ~35M tokens, **resets 00:00 UTC (05:30 IST)**, used up in ~1.5-2 h at full speed. "Rate limit exceeded" | free models (LongCat, Step) "Unlimited" per the docs. LongCat: no limit hit in 35 h at 32 slots. Step: refused for the rest of the day once its upstream limit is hit, back at 00:00 UTC |
| Accounts | logging in ("OpenCode Console") routes calls to the account (they appear in its console logs) but does not lift the IP limit | two subscriptions ($10/month each): `OPENCODE_GO_API_KEY` (account 1) and `OPENCODE_GO_API_KEY_2` (account 2, subscribed 2026-10-13). Each key runs its own LongCat reader (`go_keys` in the profile) and deck Step reader (`step-5-preview-free@go2`) |
| Paid models | none enabled | **do not use** (Shivam: free models only). GLM-5.3-Flash etc. draw on the plan's paid allowance |

- **Throughput measured:** Go LongCat ~56-69k AR pages/day per account; Zen ~6.5k pages/day in total. Go is ~10x Zen.
- **Free models are time-limited promotions.** OpenCode announces them on X: LongCat, Space Bunny and Step each ran
  for days to weeks. `new_reader_check.py`, run daily by the watchdog, diffs the model lists and auto-tests new Zen models.

## 4. How the work is split and kept alive

- **Workers,** all `ingest_annual_reports.py` routes, each a watchdog job:
  - `python` (main run): Go LongCat on each Go key, plus Gemma 31B on 30 Google keys. Newest reports first.
  - `zen`: Zen models via `opencode run`.
  - `google`, `google_3.1fl`, `google_gemma-4-26b`: Flash-Lite 3.5, Flash-Lite 3.1 and Gemma 26B.
  - Every route except `python` claims reports oldest-first in `ar_facts.db` table `ar_claims`, so no report is read twice.
- **Per-model settings** come from `reader_profiles.json`: prompt `plain` / `exhaustive` / `exhaustive_core`, piece
  size, rpm/tpm/rpd and slots. Edit it, then restart the worker by killing its python process; its `run_ar_*.cmd`
  loop restarts it in 30 s.
- **Rate limits:**
  - A Zen model that is refused benches itself for 20 min and retries; there is no retest and no restart.
  - A Google key at its daily cap rests 1 h and retries (the daily quota behaved like a rolling window).
  - Hand-backs go to an unbounded retry list. A bounded `queue.put()` deadlocked the Zen worker on 10-13.
- **Testing a model:**
  - `ar_queue.py test-export --run t-x --model <spec> [--piece-chars N] [--exhaustive] [--core] [--indian]`, then
    `drive --run t-x`, then `test-score --run t-x`.
  - Model specs: `<zen id>` (opencode run), `go:<id>`, `gemini:<id>@KEY1,KEY2`, `kilo:<id>@KEYENV`, `th:<id>`.
  - Pass rule: 25/25 must-find; < 1% numbers not in the text; regrouped < 0.5%; depth >= 4,500 facts; <= 2% of
    pieces unanswered.
  - Pieces that failed on rate limits are a quota problem, not a model failure: re-run them before scoring
    (`profile_tuner.py` waits for quota).
- **Watching:**
  - `resource_watchdog.py` restarts dead or stuck jobs, including a job that logs but reads no pages for 30 min.
  - It runs the daily reader check and an `ar_review.py` report every 200 finished reports.
  - Claude's own Monitor watches expire after 30 min and must be re-armed. Keep them quiet: report only problems.

## 5. Things that went wrong (do not repeat)

- **Hand-built test agents were refused.** The OpenCode session itself was used as an orchestrator with subagents:
  the custom agents were refused, and the `general` subagent reads with the session's own model, so it could not test
  other models. Use `opencode run` per piece instead.
- **Rate limits were scored as failures.** Tests were scored while the Zen quota was out; pieces lost to rate limits
  looked like misses (Gemma 31B, Space Bunny). Check the `.err.txt` files before scoring.
- **A malformed PDF froze a whole worker for 4 h,** with PyMuPDF holding the GIL. PDF text is now split in a child
  process with a 3-minute limit.
- **A wrong answer allowance caused 429s.** The token pacer assumed a 1,500-token answer; exhaustive answers are about
  3x longer, so the allowance is now 5,000 tokens for exhaustive prompts.
