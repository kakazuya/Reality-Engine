# T-238 stage N brief: lift the verified share of hy4 deck figures (model-free)

Ticket: T-238 (Shivam 23 Nov 2026: "start optimising the extraction now"). Reviewer: Wolf (Opus).

Goal: the 394-company deck read (`.tmp/t232read/obs_decks394.db` in the MAIN checkout
`C:/Users/warri/Downloads/Info_Diffusion_Model`; work on a copy) holds 761,306 figures: 480,459 verified, 279,488
unverified, 1,359 quarantined. Unverified reasons (a row can carry several): measure not in dictionary 110,513;
no_period 83,009; basis_conflict 62,003; no_unit 18,581; printed_axis not in text 18,256; image_text 15,027;
printed_label not in text 11,862. Most of these rows were read before stage M, so their measure is a free-coined id.
Recover the right rows by rules, never by loosening a check.

Evidence:
- DBs: the deck copy above; `D:/RealityEngine/t230/obs_91_i.db` (91-set decks, golden-gated);
  `D:/RealityEngine/t238/obs_transcripts_m.db`, `obs_measure_m.db` and the `*.new_merges.csv` review files (stage M).
- Hand-graded measure choices: `D:/RealityEngine/t237/measure_grade/grade{1,2}.md` (40 cases; hy4 force-fits:
  profit before exceptional items stored as profit_before_tax x4, receivables/payables swapped x3).
- Opus reference facts for one company: `D:/RealityEngine/t237/opus_facts.db` (SOMANYCERA; dictionary + NEW ids with
  definitions).
- Code: `reality_engine/v2/observations.py` (measure_dict/measure_alias, `--recheck`, `--only`), `docs/FIX_LOOP.md`.

Steps:
1. Coined-id map: count every non-dictionary measure id in the deck copy (and obs_91_i) by rows and companies;
   normalise (case, separators, dotted prefixes, `_growth_yoy`/`_pct`/`_pp` suffixes); map to an existing dictionary id
   only when name + unit family + printed labels agree; propose new driver measures for clusters with >= 20 companies;
   write `D:/RealityEngine/t238/stageN_aliases.csv` (or `.tmp/t238n/` if D: is denied): id, rows, companies, sample
   labels, action (alias/new/leave), target, reason. Governance and industry-wide figures stay unmapped.
2. Period on deck pages: a value without a printed period takes the period printed in the slide title / header line
   ("Q2 FY26 Investor Update", "H1FY26 Performance"), else, for a snapshot KPI (capacity, share count, plant list,
   shareholding), the deck's own as-of quarter with `period_source='deck_asof'`; never for a flow figure in a
   multi-period chart.
3. Basis on deck pages: when every basis word printed in the deck is one basis, unlabelled financial rows of that deck
   take it with `basis_source='deck'`; a deck printing both stays a conflict on unlabelled rows.
4. Force-fit vetoes: a row printed under "Profit before exceptional items" is never `profit_before_tax`; a cash-flow
   change in receivables/payables is never the balance; add the right ids if missing.
5. Scoped recheck on the copy and on obs_91_i (`--only` selector of rows carrying the reasons above); regress
   observations (gate 0 newly broken); report verified before/after per rule and 20 sample changed rows with page refs
   for Wolf's hand-read.
6. Tests per rule (synthetic); doc V2_SCHEMA_CONTRACT section 17 stage N; DEVELOPER_GUIDE line.

Files: `reality_engine/v2/observations.py`, `reality_engine/tests/test_observations.py`, `docs/V2_SCHEMA_CONTRACT.md`,
`docs/DEVELOPER_GUIDE.md`. Do not edit tasks/STATE.md.

Pitfalls: jobs append to `D:/RealityEngine/t238/obs_transcripts_91.db` and `.tmp/t238read/obs_91_j.db` all night:
never write them; a full recheck of 761k rows is long - scope with `--only` and run it once in the background;
an alias must not change any golden RIGHT row; no model calls.

Accept: tests pass; typecheck clean; regress gate 0 newly broken on obs_91_i; report under 20 lines with per-rule
counts, verified before/after on the deck copy, and the 20 sample rows.

Stop if: a rule upgrades rows whose value is not in the page text/OCR words; more than 2% of verified rows change
measure.

Budget: about 3 hours, DeepSeek max effort.
