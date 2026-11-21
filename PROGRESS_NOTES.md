# T-228 stage 2c — progress notes

- 21 Nov, worktree 20261121T052428Z-17494c2e: implemented stage 2c (period_norm, units, order_kind, part
  scope, collapsed-range repair, event repair, --repair/--repair-report) — 101 tests passed, typechecked.
- First repair: verified 1,954 / unverified 5,724 / duplicate 2,256; Wolf review asked the event row to be the
  earliest VERIFIED member (no verified fact behind an unverified event).
- Re-done: event row = earliest verified member; earlier unverified copies keep their status with dup_of.
  Final DB `.tmp/t228/claims_91_s2c.db`: verified 2,036 / unverified 5,853 / duplicate 2,045 / quarantined
  168; 410 of 2,449 pre-repair verified rows folded (16.7%); 211 earlier unverified copies linked; 13 rows
  re-judged (10 passed). Verified capex 200; verified inflow orders 251. Tests 102, typecheck clean.
- Docs: `docs/research/T-228_driver_claims.md` §5, §6, §8, §10, §12 end and §13 reflect the verified-event rule
  and the final counts.
