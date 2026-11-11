# Rulings condensed on 11 Nov 2026 to fit the 8,000-character limit (wording only, meaning unchanged)

- Was: Until 15 Nov: work never stops for MSI RAM; copy the job's data to an HP worktree folder, run there (x64 Python `C:\RE\py313x64`), bring results back, delete the HP copy (10 Nov).
  Now: Until 15 Nov, MSI RAM short: run on the HP (`machines/HP_LAPTOP.md`), bring results back, delete the HP copy (10 Nov).
- Was: Rules and their enforcement: `reports\standing_rules.xlsx` (+ `.html`), rewritten when this file changes.
  Now: Rules sheet: `reports\standing_rules.xlsx` (+ `.html`), rewritten with this file.
- Was: After every question/answer run: an Excel + CSV in the reports folder with questions, answers, grades, errors, documents and root causes (`answer_run_report.py`; 8 Nov).
  Now: After every answer run: Excel + CSV in reports (questions, answers, grades, errors, documents, root causes; `answer_run_report.py`, 8 Nov).
- Was: new fetches may pile up locally during testing, sweep with `raw_to_drive`.
  Now: test fetches may stay local until `raw_to_drive`.
