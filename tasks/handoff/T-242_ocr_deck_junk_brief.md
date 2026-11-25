# T-242 brief: drop decorative numbers read from OCR'd image-only deck slides

Goal: rows that hy4 reads from OCR text of image-only slides (observation.text_source='ocr') are dropped when the number is a slide/section/page serial, a year or quarter digit taken from a title, an establishment year or foundation ordinal, a standard/model code, or a digit inside a brand name.
Files: reality_engine/v2/observations.py (deck row gates / junk gate), reality_engine/tests/test_deck_guards.py, docs/DEVELOPER_GUIDE.md
Accept: python -m pytest -q reality_engine/tests/test_deck_guards.py ; python -m pytest -q reality_engine/tests/test_observations.py ; python -m pytest -q reality_engine/tests/test_ar_sections.py  (all pass)
Evidence: grade C:/RealityEngine/t242/ocr_grade1 (pack_part00/01.jsonl with observation rows + slide image paths). Part 1 (rows 31-60): 5R/4P/0W/21J; every verified row R; all 21 J unverified junk. Kinds with ids: section/card/page serials 31 33 41 48 51 53 57; year/period from title 40 43 46 54 ("4" of "Q4") 58 59 ("26" of "FY26"); establishment year / foundation ordinal 44 58 60 ("119th"); standard or model code 35 ("ISO 13485:2016") 49 ("CyberKnife M6"); brand-name digit 38 ("5paisa"); mock-up/decorative 39 47. Source DB D:/RealityEngine/hy4_out/obs_decks_wide.db (4,054 ocr rows, read-only).
Stop if: a rule drops any R row of ocr_grade1, decks_wide_ckpt4 or audit_deck1 (by observation_id); a rule drops > 40% of the ocr rows that are not J-like (measure on a copy); per-company rules.
Budget: ~70 tool calls
Ticket: T-242

## Steps
1. Extend the r4 junk gate (`junk_ordinal_reason`, merged 98ae61ac) for deck rows: a value that is (a) a lone 1-2 digit section/divider/page/card number with no unit and a label that is a section title or empty; (b) a digit or year that is part of the slide title/period token itself (FY26 -> 26, Q4 -> 4, "2026 Investor Presentation"); (c) a year/ordinal next to "established", "since", "founded", "years of", "th year"; (d) part of an alphanumeric code (ISO/IEC/model numbers like "13485:2016", "M6"); (e) a digit inside a brand/company token ("5paisa"). Structural cues only.
2. Apply to all deck rows (not only ocr) but measure separately for text_source='ocr' and others.
3. Measure on a COPY of obs_decks_wide.db (scratch in your worktree .tmp): rows dropped by rule and text_source; 20 random dropped rows (seed 7); graded-R rows hit (must be 0).
4. Tests per rule; docs.

## Limits
Never write live DBs (D:/RealityEngine/hy4_out, C:/RealityEngine/tg_build). No model calls. pytest per file. Never kill processes by name.

## Added 04:17 (part 0 of the same grade; note C:/RealityEngine/t242/ocr_grade1/fix.md)
Overall 17R/12P/1W/30J of 60; VERIFIED OCR rows 13R/1P/0W/0J - the gate must not drop verified company figures (measure verified rows dropped separately, target 0).
More junk kinds: demo/mock dashboard or phone-UI values (rows 4, 20 incident ticket ID; 15 "126" mock phone; 28 "P2: 28" sample dashboard); a completion date stored as a number (6 "Mar 2027" -> 2027); a year in an award list (24 "2020"); a name containing a number (14 "Forbes India Select 200"); product dosage (27 "20mg"); yarn count range (8 "Ne 40"); ISO 27001 (26).
