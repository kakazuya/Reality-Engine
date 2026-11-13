# T-208 round 2: OCR the unseen stores' bad pages on the HP, then rebuild

Ticket: T-208

Goal: the three unseen stores (`D:/RealityEngine/s10/{kei,medanta,pvrinox}/`) were built from text layers only. 409
pages have no or a jumbled layer (`<sym>/ocr_needed.csv`: KEI 169, MEDANTA 56, PVRINOX 184), and at least one page the
check passed is garbage: PVRINOX Q2 FY27 results `quarterly_results/fa10203c-...pdf` page 3 reads "Revpnul' from
ooerulions", so revenue_from_operations is missing for Q2 FY27 and consolidated `exceptional_items` = 3,511 (the PBT).
OCR every such page on the HP with TextRecognizer, put the OCR text into each `pages.db` the way the T-189 AUROPHARMA
build did, rebuild the 13 parts, and show the PVRINOX defect gone. No model calls.

Evidence:
- HP OCR driver: `reality_engine/pilot3/hp_ocr.py` (`plan --pdf-dir`, `run`, `fetch --words-out`, `cleanup`; `run`
  refuses while the HP console is locked); rules `machines/HP_LAPTOP.md` (headless: nothing on its screen, hidden
  tasks only; TextRecognizer stays installed, T-190). How T-189 routed text layer vs HP OCR into the aurobindo store:
  `docs/DEVELOPER_GUIDE.md` T-189 bullets and `docs/PILOT3_BLUEPRINT.md`; follow that path, do not invent a new one.
- Build recipe and part order: `docs/DEVELOPER_GUIDE.md` block "T-208 unseen stores".

Steps:
1. Find garbled layers the check missed: on every results, press-release and deck page of the three stores, score the
   share of tokens that are dictionary words or clean numbers (the label dictionary the build already has); list pages
   under a threshold you fix BEFORE looking at which pages fall under it, and say the threshold. Add them to the OCR
   list. Report the count per company and confirm PVRINOX fa10203c p3 is on it. (Script in `.tmp/`, not a new module.)
2. OCR the list on the HP (`hp_ocr.py`), fetch, merge into each `pages.db` as T-189 did (OCR text replaces a garbled
   layer; keep the old layer's method label for audit).
3. Back up each `<sym>.db` as `<sym>_before_ocr_2026-11-14.db`, rebuild all 13 parts, rc=0.
4. Show: PVRINOX Q2FY27 revenue_from_operations standalone and consolidated now present with page and value (standalone
   should read 20,620 Rs mn on p3); exceptional_items no longer the PBT; per-company before/after counts in
   `D:/RealityEngine/s10/coverage_after_ocr.csv`.
5. Docs: extend the DEVELOPER_GUIDE "T-208" block (OCR counts, threshold, commands); PROGRESS_NOTES lines.

Files: data under `D:/RealityEngine/s10/` only; `docs/DEVELOPER_GUIDE.md`; scripts only under `.tmp/`. No code change
in `reality_engine/`; if one is needed, stop and describe it.
Accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/s10/coverage_after_ocr.csv').exists() else 1)"
Pitfalls: never put anything on the HP's screen; HP RAM 16 GB, run one company at a time; delete the copied PDFs on the
HP after fetch (`cleanup` keeps the package); do not touch bluestar/aurobindo stores or the live registry.
Stop if: the HP console is locked (say so; Claude asks Shivam to unlock it); OCR error rate over 10%; 3 hours.
Budget: 3 hours, 250 tool calls.
