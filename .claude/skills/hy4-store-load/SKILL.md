---
name: hy4-store-load
description: Move gated hy4 reads (or a re-checked copy) into the company stores the reality-data tools serve, safely: recheck on a copy, verify counts, swap with a backup, reload only touched symbols, keep frozen copies for frozen-bank scoring. Use after a gate fix, a passing grade, or when stores lack new reads.
---

# hy4 reads -> stores

Rules: databases and builds on C: SSD only (D: holds raw docs and hy4 output DBs). One writer per DB (ops_gate flags two). Nothing loads from a doc type whose latest grade failed (AR gated until a pass).

## 1. Recheck on a copy (after gate code changes)
```
cp D:/RealityEngine/hy4_out/<db>.db C:/RealityEngine/t242/<job>/<db>_r1.db
REALITY_RAW_FETCH=0 python -m reality_engine.v2.observations --recheck --doc-types deck|transcript|annual_report \
  --stores-root C:/RealityEngine/tg_build/universe_fy27 --out <copy>      # logs only at the end; watch <copy>-journal
```
## 2. Verify before swap
Counts by status and status_reason, before vs after; the changes must match what the fix measured (e.g. deck gates: ~81 bound + 11 combined-label unverified, 242 heading basis). 0 rows of the latest passing grade's R set may change status.
## 3. Swap
Back up the live DB (`<db>_before_<fix>_<date>.db`), confirm nothing writes it (no hy4 loop on that output), move the copy in.
## 4. Load only touched symbols
```
python .tmp/load_symbols.py --from-db D:/RealityEngine/hy4_out/<db>.db     # or SYM1 SYM2 ... ; log C:/RealityEngine/t242/load_symbols.log
```
Pilot stores also hold these symbols (24 overlap): load them too (`load_observations --store <pilot>`), but first keep `<store>_before_obs_<date>.db` beside it. Frozen-bank runs pin `REALITY_PILOT3_DB` to the frozen copy; the registry skips `_before_` copies.
## 5. Check serving
In-process spot check of 3 symbols (skill `retrieval-audit`, step 2) and `python -m reality_engine.scripts.ops_gate` clean. STATE line + commit naming the ticket.
