# Task — download filters: NSE announcement buckets + concall widen/rescue lists (code + offline checks only)

## Goal
Shivam's rulings (2026-10-28 afternoon):
1. **NSE announcements:** download an attachment only when it can be classified **before download**, from `desc` + `raw.attchmntText`, as a transcript/meet OR a material announcement (orders, management/director/auditor change, acquisition, merger, results, presentation, press release, rating, capex/plant, fund raise, litigation, insolvency, etc.). Procedural items (newspaper ads, share-certificate loss/duplicate, trading window, depository certificates, record date, book closure, AGM notices / scrutinizer reports, ESOP exercises, RTA/contact changes, compliance certificates) are **not downloaded**. Anything unclear is **not downloaded**. The JSONL metadata row is always kept.
2. **Concall widen:** of the 2,301 fresh widened rows, fetch only those whose headline or attachment name contains a transcript word (≈1,595). The rest are invites / outcomes / schedules.
3. **Concall dedupe rescue:** the 2,838 rows dropped by the (ISIN, quarter) dedupe are 93% invites/presentations; 214 carry a transcript word and include distinct events (AGM transcripts, later analyst meets). Fetch those 214; the existing content dedupe drops true duplicates after download. List: `D:\RealityEngine\raw\concall_refetch\dedupe_rescue_214.json`.

## Do
1. `reality_engine/scripts/nse_announcements.py`:
   - Add `bucket(record) -> 'transcript' | 'material' | 'procedural' | 'unclear'`.
   - Start from the draft `tasks/dsh_tasks/nse_buckets_draft.py`, which already gives 1,373 / 3,904 / 3,663 / 692 on the pilot. Tighten it: e.g. "Outcome of Board Meeting" for a trading-window or AGM-only outcome is procedural; "Intimation of changes in senior management" in Updates is material.
   - Add `--download-buckets` (default `transcript,material`). Store the bucket in each JSONL row.
2. `reality_engine/scripts/concall_refetch.py`:
   - Add `--transcript-word` (with `--widen`: keep only rows with a transcript word in the headline or attachment name).
   - Add `--rescue-file PATH` (fetch exactly the newsids listed there, through the same validate/classify/dedupe path).
   - `--dry-run` prints the counts.
3. **Hand-check offline** on `D:\RealityEngine\raw\nse_announcements\pilot_2026-10-28\*.jsonl`:
   - 40 random rows per bucket, judged by the headline text.
   - Report precision for material and transcript, and how many material items wrongly fall in procedural or unclear.
   - Target ≥90% on both.
4. Report the projected downloads (count and MB from `raw.fileSize`) for these two runs:
   - the 114 NSE-only companies, transcript + material;
   - the transcript-gap run, transcript only.
5. Tests: extend `test_nse_announcements` and `test_concall_refetch` with offline cases.

## Rules
- **No network.** Write only in this worktree. All databases read-only. No commits.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_nse_announcements reality_engine.tests.test_concall_refetch
```

## Report
Give:
- the bucket counts and the hand-check precision;
- the projected downloads;
- the exact commands for the full NSE run and for the concall widen and rescue fetches;
- your tool-call count.
