# Task — run the deterministic macro claim → target extractor over all 21,552 policy events, then check it on a fresh sample

## Goal
The merged pilot (`reality_engine/pilot/macro_claims.py`; DB at `D:\RealityEngine\pilot\macro_pilot.db`) maps policy claims to sectors, industries and companies. On the 58 policy-rooted ripple cases it lifted the RIPPLE planner from 0 to 28 answered. The other 30 failed mainly because their policy event wasn't among the 300 sampled claims.

Its precision of 1.000 was measured on labels the same worker wrote, so it needs an independent check. The extractor is deterministic and cheap, so run it on every claim. The result is a pilot T1-style table, the same as the whole-market market_state.

## Do
1. Run the extractor on all `policy_events` rows, with quote_ok preferred and the others flagged. Build `.tmp/pilot_all/macro_all.db` with the same DDL. Report rows, targets per type and runtime.
2. **Independent check:** draw 80 claims with a new seed (20261029), stratified by source and excluding the 300 pilot claims.
   - Judge each mapping only against the claim text and the source document. Don't reuse the old labels or the alias lists as ground truth.
   - Report precision and recall, with the Wilson lower bound, and list every miss with its reason.
3. Fix the top defect classes, then re-run. Keep it deterministic and idempotent. Add tests.
4. **Trigger matching:** the RIPPLE trigger is free text and picked an unrelated policy (a coal/freight case matched a Tamil Nadu budget claim). Make the match require the policy's issuer, date window and topic overlap, and score each candidate. Re-run the 58 ripple cases on the full table and report before/after.
5. Parse prose effective dates ("end of 2026", "from April") into a date with `pit_conf`, so the market-window hop works.

## Rules
- Read-only on live DBs. Write only in this worktree. No network, no paid models, no commits.

## Acceptance checks
- `python -m unittest reality_engine.tests.test_macro_claim_target` passes.
- `tasks/macro_pilot/REPORT_ALL.md` has the full-run counts, the independent 80-claim precision/recall, and the 58-case before/after.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_macro_claim_target
```

## Report
Give:
- the counts;
- the independent precision/recall, with the Wilson lower bound;
- the 58-case result;
- the defects fixed;
- your tool-call count.
