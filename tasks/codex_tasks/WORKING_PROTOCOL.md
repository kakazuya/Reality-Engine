# Standing chain of command — Shivam, 2026-10-21

Applies in every session until Shivam changes it. Supersedes older conflicting role descriptions and timed handoff arrangements. FRAMEWORK remains the project authority; only Shivam changes it.

**Shivam directs Codex. Codex reports to Shivam.**

- **Off-peak:** DeepSeek through dsh writes project code, boilerplate, tests and bug fixes. Codex supplies the full brief/context, launches and monitors the worker, reviews the actual changes, and runs independent checks. Every defect goes back to DeepSeek through dsh for repair and another review. Codex does not patch project code itself off-peak, including after a worker failure.
- **Peak:** Codex implements and fixes directly. Peak is Monday–Friday **06:30–09:30 and 11:30–15:30 IST**. Other times and weekends are off-peak. Codex checks the clock itself; no timing-confirmation question.
- DeepSeek uses `python -m reality_engine.scripts.run_deepseek_harness`, **xhigh**, stable session IDs, and permissions suitable for the task. The current project coding/backtesting workflow, including H01, is explicitly approved paid DeepSeek use off-peak. Unrelated paid model use still needs approval.
- Direct Codex planning, reading, task briefs, monitoring, verification, and memory/state updates are part of orchestration. Implementation and bug fixes obey the timing split above.
- Claude remains an advisor for targeted consultation when requested, with a complete named-file brief and awareness of the remaining subscription allowance.
- Ollama is dropped. Do not pursue its missing key or expiring promotion.

Global copy: `C:/Users/warri/.codex/AGENTS.md`. Core memory: `C:/Users/warri/.codex/claude_memory/feedback_codex_deepseek_chain_of_command.md`, indexed first in MEMORY.md. This file records Shivam's instruction; it does not modify FRAMEWORK.

## dsh operation checked on installed 0.2.1-rc.2

- Reasoning effort and output-token caps are separate controls. Keep normal DeepSeek work at xhigh, as Shivam requested; do not keep adjusting reasoning per task.
- `--max-output-tokens` is an optional main-request cap. Thinking tokens count toward it. It is not a total task token budget; a tool-using task can make many model requests. Without this flag, adapter/model defaults apply; do not describe that as unlimited.
- A response hitting the cap ends the current turn with `max-tokens`; headless returns a nonzero exit rather than automatically continuing that truncated turn. Inspect the actual outcome and hand unfinished work back to DeepSeek with context.
- Our launcher also has a separate wall-clock timeout, 900 seconds by default. Set an appropriate longer timeout for substantial implementation instead of accidentally killing productive work. Monitor progress and review completion independently.
- Tiny 128–1024-token caps were connectivity-probe settings, not normal coding settings. Normal worker briefs, xhigh, sufficient response capacity and runtime, and the review/fix loop are the intended workflow.
