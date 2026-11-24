# T-242 `no_referent`: widening the guard to passages that start mid-thought — measured, NOT merged

Date: 2026-11-25. Writer: dsh worker (worktree `20261124T190034Z-05ff3196`). Ticket: T-242.
Status: **candidate built, measured, reverted** — the 5% stop bar in the brief fired, so nothing is merged and
`git status` on this worktree is clean.

## What was asked

The 8 P rows of the `fy27_v3` ckpt_0003 grade are statements that read as whole sentences but whose referent sits in
the passage before them. The current guard (`no_referent_reason` in `reality_engine/v2/obs_speaker.py`) only fires on
replies under 8 words that open yes/no/right/correct/sure.

## Candidate rules (structural only, no company/sector vocabulary)

Every hit sets `status_reason` to `no_referent: ...` and turns `status` to `unverified`; the row is served, never
dropped. The guard was tested through `attach_statement_speakers` and as a pure function.

| rule | shape | catches |
|---|---|---|
| short yes/no (existing) | <8 words opening yes/no/right/correct/sure | 42652 (also below) |
| mid-sentence | first non-quote character is a lowercase letter | 42377 AETHER, 42493 ARVINDFASN, 52512 BLUECLOUDS |
| bare ordinal | opens "And third ...", "Secondly," with no list in the passage | 47115 BELRISE |
| pronoun / demonstrative | <25 words, opens (after So/And/Yes/...) on it/that/these/those, or names its topic only as "those products" | 43976 BANSWRAS, 51859 BIOCON, 42652 AUROPHARMA |
| bare percentage | <25 words whose only figure is a percent with no metric named ("we are close to 23%") | 42393 HAVELLS |

Counter-tests kept verified: "So our revenue grew 14% to Rs 2,300 crore this quarter.", "Yes, we expect EBITDA margin
of 18-19% in FY27.", "Havells expects ROCE to stay close to 23% across the year.", "Our order book stands at
INR 5,000 crores, up 12% from last quarter." A row-level check asserts a flagged statement stays in the output as
`unverified` (one row in, one row out).

## Measurement (read-only: `file:D:/RealityEngine/hy4_out/obs_transcripts_fy27_v3.db?mode=ro&immutable=1`)

28,024 statement rows; 15,517 verified, 12,507 unverified at the time of measurement.

| rule | verified -> unverified |
|---|---|
| pronoun / demonstrative | 1,303 |
| mid-sentence (lowercase start) | 410 |
| bare percentage | 146 |
| bare ordinal | 86 |
| short yes/no (already in the shipped guard) | 39 |
| **total** | **1,984 = 12.79% of 15,517** |

All 8 graded ids are flagged, each by the rule intended for it (verified row by row on the DB above).

### Cheapest sets that cover the grade, and what they cost

| set | covers | cost |
|---|---|---|
| the four shapes as specified | 8 of 8 | 12.79% (stop) |
| pronoun capped at 12 words + no figure, plus demonstrative | 8 of 8 | >= 6.8% (stop) |
| mid-sentence + ordinal + percentage + pronoun under 15 words | 7 of 8 (BIOCON missed) | 929 = 5.99% (stop) |
| mid-sentence + ordinal + percentage (all high-precision shapes) | 5 of 8 | 594 = 3.83% |

No rule set that covers the grade stays under the 5% stop bar in the brief, so the stop condition was honoured: the
candidate was reverted, nothing is committed, no prompt fingerprint changes (the candidate was a script-level pass;
`read_gate status` shows transcript v3 `2fae7ddac53e` unchanged).

## Decision for Wolf/Shivam

The corpus genuinely holds referentless statements at ~6-13% depending on how strictly the shapes are defined, so the
5% bar and the 8-row goal cannot both be met by one script rule. Options, in cost order:

1. Raise the bar for this guard (12.79% of verified statements is ~1,984 rows; statements are qualitative support,
   numbers are separately gated) and merge the candidate.
2. Keep the 5% bar and ship only the high-precision shapes (3.83%, 4 of the 8 rows) — the other 4 stay P.
3. Gate at the answer layer instead: mark these rows `unverified` only where an answer quotes them without their
   question/passage, leaving the store's verified population intact.

## The 30 samples a reviewer asked for (seed 5, of the 1,984)

- `1572` 360ONE p10 — mid-sentence: "allowed us to sustainably grow that business without any accidents, and hopefully no accidents to come in the future."
- `2626` ADVENZYMES p15 — short yes/no: "No. We will not be closing."
- `5485` AFFLE p18 — pronoun: "They were just barely breaking even."
- `5806` AEQUS p8 — demonstrative: "And we are taking precautions to do this most probably for another two quarters till we see the stabilization."
- `8637` AJAXENGG p5 — ordinal: "Lastly, we remain firmly committed to disciplined cash flow generation and prudent working capital management ..."
- `14094` AMBER p15 — mid-sentence: "in which form also we are raising a fundraise. We'll update you as soon as we finalize the same."
- `14340` AMBER p5 — demonstrative: "If we add back that, this will further increase to INR141 crores."
- `14916` AADHARHFC p8 — demonstrative: "We are quite confident of drawing these back and the credit cost back to our 25 basis points as we end the financial year."
- `22518` APPL p13 — demonstrative: "That entire CAPEX will not be managed from preferential, we will do the CAPEX of Rs 25 crores from the preferential issue."
- `23351` ARVINDFASN p11 — demonstrative: "Hence this basically changes our goal of becoming a net debt zero Company in about maybe in 9 to 12 months."
- `24520` ARVSMART p8 — mid-sentence: "approval linked. So we haven't come to annual guidance so far on the revenue recognition part."
- `30063` AUSTERE p9 — demonstrative: "No, that is, like, once we will start getting the orders, we will just report it."
- `30208` AURUM p18 — mid-sentence: "in a different form, where the intent at Housing can be captured across developers, brokers and consumers ..."
- `33464` AXISCADES p10 — mid-sentence: "close this quarter. We are, we are committing back to our guidance that we had made originally ..."
- `34504` AYE p7 — ordinal: "And third is that an improving asset quality trajectory is quite visible and we also are carrying a robust provisional coverage reserve or PCR of 64%."
- `39296` BANDHANBNK p10 — demonstrative: "So considering all the impact of these external factors, we thought that we need to be transparent to our investors."
- `41017` BANSWRAS p4 — demonstrative: "Operations have stabilized, and we expect this positive momentum to continue over the coming quarters." (reviewer call: "this positive momentum" names its own topic — a probable false positive of the demonstrative rule)
- `41187` BANKBARODA p20 — bare percentage: "Our GNPA ratio has improved by 38 bps YoY and stands at 1.78%." (probable false positive: "ratio" is the named metric and was missing from the metric list)
- `42328` ABDL p13 — demonstrative: "So, this is one agenda point that is going to keep us busy this year."
- `45306` BCLIND p8 — pronoun: "It's about INR300 crores, INR335 crores, including fund-based and non-fund based."
- `45410` BCLIND p4 — mid-sentence: "liter in Q1 FY26, the company continues to actively compete in the market to secure orders and maintain 100% capacity utilization."
- `48418` BHARATFORG p9 — pronoun: "It's converting into revenue from quarter 1 of '28."
- `50151` BIKAJI p3 — demonstrative: "And that's the target what we're taking for this year also."
- `51881` BIOCON p20 — demonstrative: "So, let's watch how this pans out."
- `51889` BIOCON p20 — demonstrative: "That will be too much of a granularity, but happy to talk."
- `53271` ABSLAMC p13 — demonstrative: "Therefore, it doesn't give us any added advantage that, okay, we have won this mandate ..."
- `54594` BMW p4 — demonstrative: "These should be read in the context of the greenfield project."
- `56242` BOSCHLTD p28 — pronoun: "It's a 50-50 joint venture so we will share."
- `57656` BRITANNIA p11 — demonstrative: "And our team is very confident that during the course of the quarter, that movement has already begun and should stabilize."
- `57673` BRITANNIA p12 — demonstrative: "This category is vibrant."

## Reproduce

```python
import sqlite3
from reality_engine.v2.obs_speaker import no_referent_reason  # with the candidate applied
con = sqlite3.connect("file:D:/RealityEngine/hy4_out/obs_transcripts_fy27_v3.db?mode=ro&immutable=1", uri=True)
rows = con.execute("SELECT observation_id, symbol, page, statement FROM observation "
                   "WHERE record_type='statement' AND status='verified'").fetchall()
hits = [(o, s, p, no_referent_reason(t)) for o, s, p, t in rows if no_referent_reason(t)]
```

## Tests while the candidate was in the tree

`python -m pytest reality_engine/tests/test_obs_speaker.py -q` = 23 passed (3 of them need a temp dir; this sandbox
denies dirs created with mode 0o700, so the run used a job-local plugin forcing default-mode temp dirs — the plain
command gives 20 passed / 3 `tmp_path` errors here and is clean on a normal host). Baseline in the reverted tree:
22 passed with the same plugin. Typecheck on the reverted files: no new error.
