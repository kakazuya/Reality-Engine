# T-230 stage H brief: picture-reading fixes (maps, unlabelled charts, axis ticks, stacked bars, image-only text)

Ticket: T-230 (Shivam 21 Nov 2026). Reviewer: Wolf (Opus). Use the new fix loop (T-233, merged 702e49ba):
`docs/FIX_LOOP.md`, `reality_engine/scripts/regress.py`, `--only` selectors. Never re-run all pages to test a fix.

Goal: Wolf's visual audit graded 24 deck pages by picture type (detail `D:/RealityEngine/t230/wolf_visual_audit.md`,
renders in the audit's scratch dir listed there). Recall is 93-98% on every type; precision is not:
maps 47% (71% without one page), unlabelled/sparse charts 61%, diagrams 94%, labelled bars 95%. Fix the reader before
the 403-company deck reading (T-232).

Evidence (from the audit; read the per-page detail):
1. Unlabelled charts: bar heights are estimated and stored; POLYPLEX capacity chart 20 bars estimated, 7 marked
   verified because they equal axis-tick numbers in the text layer; AFCOM stored its 9 y-axis ticks (8,00,000..0)
   as ASEAN trade values; POLYPLEX's unlabelled guidance bar (Q1 25-26 = 26) stored as actual EBITDA.
2. Maps: neighbouring call-outs swapped (CONFIPET: Haryana's printed 03 stored as 120 = Rajasthan's); three maps on
   one page merged into one series (Punjab 12, 07, 41 indistinguishable); ESAF 25 pins with no printed state.
3. Diagrams: closing level of an EBITDA waterfall (24.5) stored as a change; "top 10 customers" became a 10% share.
4. Labelled bars: stacked "existing" segments stored as totals (OCCL two capacity totals per year); CAGR as yoy.
5. Image-only text: correct values quarantined because the chart text is in the image, not the text layer
   (CONFIPET 37 of 40 right rows quarantined).
6. Regression the T-233 gate caught: RSYSTEMS "EBITDA for Year 2024, Rs. 2,611 mn" graded RIGHT as `ebitda`, now stored
   as `ebitda.delta` (row 118618): the stage-D bridge rule turns a level into a delta. Fix it.

Steps:
1. Prompt: never estimate a value that is not printed (no bar heights, no reading against gridlines); mark any
   unlabelled bar as omitted; a forecast/guidance bar (E, F, Guidance, Target, shaded/hatched legend) gets
   period_kind estimate/target, never actual.
2. Script: a value whose only text-layer match is part of an evenly spaced tick ladder (>=4 numbers, constant step)
   cannot verify (`axis_tick`); keep unverified.
3. Maps: one series per map panel (model returns panel title; script splits); a geography is verified only when its
   name is printed adjacent (text-layer word boxes: nearest label within the call-out distance used elsewhere in
   page_words/reference_geom); else geography null, unverified.
4. Waterfall: first and last bars are levels of the walked measure; only middle bars are deltas (fix 3 and 6).
   Stacked bars: a segment label inside a stack is a part with its segment dim, never the total; the total only
   when printed as total. "Top N customers" is a count/rank, not a share, unless % is printed.
5. Image-only text: for pages whose text layer lacks the values, run the existing OCR route (Kilo Dots on the page
   image, see `reality_engine/v2/page_reader.py` / memory "OCR: Kilo Dots + Haiku") to build a text layer for the
   check; values found in OCR text verify with `text_source='ocr'`. If Dots is unavailable, keep them unverified
   (never quarantined) with reason `image_text`.
6. Fix loop: write one selector per fix (pages of the audit + all pages with the same defect signature, found by
   SQL on `D:/RealityEngine/t230/obs_91.db`); run scoped recheck (script fixes) or scoped re-read (prompt fixes)
   into `.tmp/t230h/obs_91_h.db` with `--baseline D:/RealityEngine/t230/obs_91.db`; run
   `regress observations --db .tmp/t230h/obs_91_h.db --baseline D:/RealityEngine/t230/obs_91.db`. Gate: zero newly
   broken. Report scoped page counts (cap 1,500 re-read pages in total).
7. Tests for each rule (synthetic). Doc: section 17 stage H.

Files: `reality_engine/v2/observations.py`, `reality_engine/tests/test_observations.py`, `docs/V2_SCHEMA_CONTRACT.md`.
Stage G (dictionary tables) is editing the same file in another worktree: keep away from the measure dictionary
tables. Do not edit tasks/STATE.md.

Accept: tests pass; typecheck clean; regress gate pass; report under 25 lines with per-fix scoped counts, the audit
pages' before/after per type (recall, precision, invented values), and the regress summary.

Stop if: a fix needs > 1,500 re-read pages; regress shows any newly broken row you cannot explain.

Budget: about 3 hours, DeepSeek max effort.
