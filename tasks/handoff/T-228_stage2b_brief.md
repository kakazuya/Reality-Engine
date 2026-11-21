# T-228 stage 2b brief: five fixes, then claims on all 91 stores

Ticket: T-228 (Shivam 20-21 Nov 2026). Reviewer: Wolf (Opus). Stage 2a is merged (b13de056); read
`docs/research/T-228_driver_claims.md` sections 11 and 11.x first.

Goal: the factor study (T-229) needs dated forward claims for more companies and months. Fix the defects Wolf's hand
read found, then run every doc source on all 91 stores, so T-229's text factors can be re-tested.

Evidence: (real)
- Pilot DB `D:/RealityEngine/t228/s2a/claims_s2_pilot.db` (read-only); Wolf's per-claim grades
  `D:/RealityEngine/t228/s2a/wolf_read_s2a.md` (40 verified claims, seed 97: 23 right / 14 minor / 3 wrong).
- Defects with claim ids in that pilot DB:
  a. Unit/plant scope (all 3 wrong are here): 577 "around INR250 crores from next financial year" is a new unit's
     revenue stored as company revenue.total sign 0; 573 "30% to 40% of the revenues of the total potential" (new unit
     ramp) stored as revenue.mix; 1130/735/437 segment "total" though the text names a unit/plant/product.
  b. 1342 "at least 20% to 25%" stored 25-25 with base "20%" (range low end dropped).
  c. 247 "Rs. 117.74 Crores including GST": `base` empty; other orders are ex-GST.
  d. 982 CRISIL "Revenue in fiscal 2025 is estimated ... Rs 2400-2450 crore": a rating agency's estimate stored as
     the company's claim.
  e. Same fact twice: 132/1003 (dividend from AR and from board outcome), 735/1130 (guidance row and its transcript).
  f. 522 one-time loan settlement payment sign 0 (should be -); dividends sign 0.
- Stage 1 final claims `D:/RealityEngine/t228/claims_91.db` (transcripts + guidance, 91 stores) - read-only.

Steps:
1. Fix a: prompt + judge rule: when the quote or its paragraph names a unit, plant, product, subsidiary or new line,
   set `segment` to it and treat the value as an increment (sign +, base "new unit") never a company-wide level.
   Add a script check: segment "total" with a revenue.total level claim whose paragraph contains plant/unit/line words
   -> judge must confirm or the claim stays unverified.
2. Fix b: range rule: "at least A to B" / "A% to B%" -> low A high B; test.
3. Fix c: script reads "including GST"/"inclusive of GST"/"excluding GST" in the quote or paragraph into `base`.
4. Fix d: new field `speaker_scope` (company / rating_agency / other); script tags paragraphs from rating-rationale
   pages (CRISIL, ICRA, CARE, India Ratings, Acuite, Brickwork + "estimate/expects/rating") as rating_agency; such
   claims are kept but never verified as the company's claim (status unverified, reason third_party).
5. Fix e: cross-source dedupe per (symbol, node, segment, value_low, value_high, unit, effective_period): keep the
   earliest known_at row, record the others' ids in a `dup_of` column.
6. Fix f: sign from node + verbs (pay off, repay, settle, reduce -> debt.level -; dividend declared/recommended -> +).
7. Pass the claim's known_at to the judge, so "FY25" in a document filed in 2025-05 is judged as past/forward by the
   document date (stage 1b judge period_ok failures on stale guidance).
8. Tests for 1-7 (synthetic; use the quoted texts above as fixtures).
9. Re-run the 12 pilot stores to `.tmp/t228/claims_s2b_pilot.db`; report the same counts as stage 2a and list how the
   ids above now come out. STOP and report (message, then wait for Wolf's go via followup).
10. On Wolf's go: all 91 stores, all doc sources (transcript, guidance, annual_report, press_release, announcement),
    `--start 15 --unleashed`, to `.tmp/t228/claims_91_s2.db`; resume on quota stop (honour Retry-After). Report: claims
    by status, node, source_kind; companies and month-ends with >=1 verified claim, before (claims_91.db) vs after.

Files: `reality_engine/research/driver_claims.py`, `reality_engine/tests/test_driver_claims.py`,
`docs/research/T-228_driver_claims.md` (new section 12). No other file; do not edit tasks/STATE.md.

Accept: `python -m pytest -q reality_engine/tests/test_driver_claims.py` passes; typecheck clean; step 9 report.

Limits and pitfalls:
- Read-only on every store and on D:/RealityEngine/t228/*; write only in your worktree.
- hy4-flash-free and beam-free only. The hy4 window cap was hit at 02:55 IST today after ~33k pages: on a quota
  429 with Retry-After, sleep it out and resume; never hammer. Another hy4 job (T-230 deck observations) shares the key.
- Do not loosen the verified rule to raise counts. Run pytest per file.

Stop if: quarantined > 10% or empty replies > 20% in step 9; the 91-store run would send > 60,000 model items
(report counts and stop).

Budget: about 2 hours for steps 1-9, DeepSeek max effort; step 10 is a run, not coding.
