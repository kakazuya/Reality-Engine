# T-113 A round 10: verified needs a second independent source; six new wrong classes (CONTINUE)

Ticket: T-113

CONTINUE: the checker (`reality_engine/pilot3/row_checks.py`) is at round 9 (commits 0e3845a, 63c82dd) plus main's
T-107/T-115 changes. Fresh session: read `docs/DB_BUILD_GUIDELINES.md` section 13 and `git log -6 --stat --
reality_engine/pilot3/row_checks.py` first. Same rules: never edit extractors (`kpi.py`, `guidance.py`, `stores.py`,
`lexicon/`), no company or metric literals, no shared word lists.

Goal: a `verified` kpi row is right at least 95% of the time on companies nobody has tuned on.

Evidence (Opus's hidden read of six unseen companies, 8 Nov; the companies stay hidden, find your own examples):
- 40 verified rows: 27 right, 2 partly, 11 wrong. Split by the checker's own `corroborated` flag: corroborated rows
  15 right of 16; NOT corroborated rows 12 right of 24 (50%). The earlier hidden read (hold6) had the same rate before
  rounds 8-9. Fixing one wrong class per round does not converge: each new company set brings new classes.
- The 11 wrong rows fall in these general classes:
  1. a footnote or asterisk note's amount taken as the metric ("Net Debt *Includes investments in liquid funds and FDs
     of X"): the number belongs to the note, not the label;
  2. a third party's projection stored as the company's actual ("is estimated at 1.1 times in fiscal 2026 and is
     expected to remain stable": rating agency text);
  3. a regulator's allowed or normative rate stored as the company's ratio ("return on equity of 15.5%" in a regulated
     utility: the tariff's allowed return);
  4. a segment / vertical word in the quote ("of our flagship <X> vertical", "hospital business") on a total row;
  5. a nearer foreign label: "gross debt when we have a cash of INR 3,165 crores" stored as gross debt (the label
     nearest the number is "cash");
  6. a past level in narrative stored as the current period ("net debt almost nearing INR 20,000 crores" said about
     years earlier, stored for the call's quarter).

Steps:
1. Tests first (`reality_engine/tests/test_row_checks.py`), one per class with an invented sentence of the same shape
   (do not search for the hidden companies), plus a right row for each that must stay verified or unverified.
2. The structural rule: a kpi row is `verified` only when `corroborated` is true (another independent document agrees,
   or a filed statement pins it), except `xbrl_segment` rows (they ARE the filing). An uncorroborated row that passes
   every check becomes `unverified` with soft `single_source`. Measure on both dev dbs: verified count before/after,
   and the share of verified rows that are corroborated.
3. Checks for classes 1-6, hard where the row is wrong for sure (1, 3, 5), soft where a reader must look (2, 4, 6).
   Third-party projections: words like 'is estimated at', 'is expected to', 'we expect' by a rating agency, 'rating',
   'outlook' near the number on a page that is a rating rationale / credit rating letter (page text), or future
   fiscal year after the number on a past-period row. Regulated rate: the phrase 'return on equity' with a regulator /
   tariff / 'allowed' / 'normative' / 'regulated' word in the same sentence. Nearer label: reuse the round-3 rule for
   guidance (a foreign metric's label nearer the number than the row's own) for kpi rows.
4. Run on both dev dbs (paths as in earlier briefs: `scratchpad/ho/u6_eval.db` + `unseen6_profile.json`,
   `D:/RealityEngine/pilot10/scratch/t113_p10_v2.db` + `tasks/night_loop/pilot10_profile.json`); before/after counts per
   status and per new check, 5 hits each. Never open other dbs in `scratchpad/` (hidden hold-outs live there).
5. Docs: section 13 (the single_source rule, the six checks, counts). Final answer starts with `Docs updated:`.

Accept: `python -m pytest reality_engine/tests/test_row_checks.py -q` passes; every verified kpi row on both dev dbs
is corroborated or xbrl_segment; run under 15 s on the pilot10 dev db.
Limits: read-only dbs, outputs under `.tmp/`; `PYTHONIOENCODING=utf-8`; regexes in files, never `\b` in a non-raw
string; pytest `tmp_path` is unusable in the sandbox: shadow it with a `.tmp` fixture as the existing tests do; the
controller applies your diff (the sandbox cannot commit), so do not spend calls on git commit.
Budget: 110 tool calls, 2 hours.
Stop if: a class cannot be caught without a company or metric literal: report it with an invented example and stop.
