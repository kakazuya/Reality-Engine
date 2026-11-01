# Workspace review, 1 Nov 2026 (Wolf)

**Verdict: the data work is real; the control system around it is not.** Rules are written, but they are enforced by one reviewer's attention, so the same failures repeat and work in progress is about five times what that reviewer can absorb: 15 unmerged branches, 19 worktrees, 7 finished jobs waiting. The gate says 12.7% contract-strict; the read grade says 0 of 127 answered rows right (0.00%, upper bound 0.40%). Both are true; only the second is about truth. Claude (Wolf) runs this workspace and is graded here without softening.

**Method.** 46 sources opened (arXiv, practitioner blogs, standards, vendor docs, one RCT), typed and dated, disagreements named in the Sources sheet: AGENTS.md saves runtime and tokens (arXiv 2601.20404) but does not raise success and adds >20% cost (arXiv 2602.11988). The named files were read read-only and measured with `git log/branch/worktree list`, `doc_gate.py --sweep`, pytest collection, file counts and `DATA_INVENTORY.md`. Grades come from evidence, "not measured" where it is missing.

**Five findings**

1. **We grade our own homework.** The gate counted answer shape while the design's author chose the metric. The worker's "30 of 30 accuracy" passed a NIM of 90% and 125 MW stored as `inr_cr`; a hand read of 25 answered rows found 0 right. Research agrees: exact-match agreement overstates chance-corrected kappa by 33-41 points (arXiv 2606.19544), and visible tests saturate while held-out tests fail (arXiv 2605.21384).
2. **Rules are prose; checks are not.** The filing-timing rule lived only in chat (27 Oct); a rebuild undid Shivam's bank rulings (1 Nov); two "not held" removals were wrong while 186 NSDL files and 1,932 F&O files sat on disk; 37 doc references point at files that no longer exist. A six-week study found written rules did not change agent behaviour and a lint check did (arXiv 2610.32578); 63.2% of AI pull requests change code with no docs, and that debt compounds (arXiv 2610.27381).
3. **Review is the bottleneck and it is unbounded.** 15 unmerged branches (oldest 8 days), 19 worktrees, 7 finished jobs awaiting review, 428 live task docs, one reviewer who is also builder and merger. Google's guidance is ~100-line changes (S21); ours arrive as whole subsystems.
4. **Defaults fail silently.** Workers start read-only (HP lost a night; this review lost its first start), leases die at 30 minutes (prototype worker, 03:50), a missing wake-up lost 5 hours on 31 Oct, a memory reaper lost 9 hours of fetching. Each was caught by a human noticing, not by the system refusing.
5. **Scope is measured in questions, not capability.** The bank was rewritten three times to 1,901 questions before any engine score on it; a 60-name extraction run started before a prototype passed and was cancelled 15 minutes later. Shivam has repeatedly been the one to cut scope, which means the system has no governor of its own.

**Do first.** Make the read grade the gate headline and the contract a footnote. Cap WIP at 2 branches and 2 worktrees with a daily merge train. Delete the 32 leftover test temp dirs and 37 dead doc references. Then the write-time typed contract, tested on the same three companies.

**Full detail** — 16 graded criteria with benchmarks and evidence, 40 traced incidents, 5 root causes, 10 ranked fixes, 6 milestones, 46 sources, and the outside advice that does not fit this project: **`tasks/management/WORKSPACE_REVIEW_2026-11-01.xlsx`**.

**Limits.** No paid model; `Manual Dumps/` not read; no code, store, branch or worktree changed. Incident costs are estimates from logs, not invoices.
