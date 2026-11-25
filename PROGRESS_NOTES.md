# T-242 AR gates r4 (dsh worker) — progress

- 26 Nov 03:00 · Read context pack, brief, `C:/RealityEngine/t242/ar_grade_r3/fix.md`, both deck grades.
- Implemented in `reality_engine/v2/observations.py` (prompt fingerprints unchanged):
  - `SCOPES` + `canonical_scope` gain `jv`/`associate`; `_ar_jv_scope`/`_ar_jv_heading` read a JV/associate heading
    from the page (or the previous page's last 700 chars, heading-like lines only); unnamed jv/associate rows never
    verify (`ar_jv_unnamed`, `AR_ENTITY_NAME_RE`), with the company's own equity-method lines exempt
    (`AR_EQUITY_METHOD_LABEL_RE`); `gate_not_company` holds unnamed jv/associate rows unverified.
  - `_ar_parent_backed`/`scope_unbacked` reset an unbacked `parent` claim; the bare-acronym subsidiary cue now needs
    a printed subsidiary/associate table (`#17 ABFRL` NSDL).
  - a `% of holding` measure under a subsidiaries table is the group's own figure -> `company` (`#10 APOLLOHOSP`).
  - `junk_ordinal_reason` drops edition/AGM ordinals, celebration slogans and appointment-term echoes on AR and deck;
    `recheck_db` deletes a dropped deck row (`deck_dropped`).
  - `deck_untied_reason`: no label/axis/group with a measure-less series title (`#11 ASIANPAINT`), or a matrix label
    that is a different period (`#56 ANGELONE`) -> `deck_untied_value`.
- Tests: 8 new cases; 257 pass across test_observations / test_ar_sections / test_deck_guards / test_results_gates
  (needs the local `.tmp/pytest_sandbox_shim.py` here: this sandbox's `Path.mkdir(mode=0o700)` makes pytest tmp dirs
  unlistable, so every `tmp_path` fixture errors without it).
- Measured on read-only copies (`.tmp/measure/`, seed 7): AR 505/20,620 verified rows (2.45%; 298 status = 1.45%),
  deck 42/66,542 (0.06%); 0 graded-R rows hit in ar_grade_r3 / decks_wide_ckpt4 / audit_deck1; all 7 AR W/J and
  3 deck W/J rows hit by their intended rule.
- Docs updated: `docs/DEVELOPER_GUIDE.md`, `docs/V2_SCHEMA_CONTRACT.md`, `machines/MSI_LAPTOP.md`, `tasks/STATE.md`.
- Next: fresh non-author grade of a rechecked AR/deck copy (controller), then load.
