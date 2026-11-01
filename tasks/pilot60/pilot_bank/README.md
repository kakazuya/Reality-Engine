# Pilot question bank builder

Builds `tasks/pilot60/PILOT_BANK_2026-10-31.jsonl` (1,901 questions) and its Excel copy. The bank is frozen: a rebuild can drift from Shivam's rulings in `PILOT_BANK_REMOVED_RULINGS_2026-11-01.json`, so diff any rebuild against the bank before accepting it.

| File | Purpose |
|---|---|
| `run.py` | Entry point: load every rule file, then build |
| `build.py` | Build the bank from the hand-written rules; read-only on stores |
| `engine.py` | Fill question rules with values read from the stores |
| `rules_a.py` | Rules for MB0001-MB0330 |
| `rules_b.py` | Rules for MB0331-MB0630 |
| `rules_c.py` | Rules for MB0631-MB0830 |
| `rules_d.py` | Rules for MB0831-MB1073 |
| `rules_e.py` | Corrections after the first build and audit |
| `rules_f.py` | Shivam's review of the removed questions, 1 Nov 2026 |
| `reads.py` | DeepSeek reads passages for each question and stock, and decides nothing else |
| `reads.jsonl` | Those reads |
| `loop.py` | Read, rebuild, and read replacements, up to five rounds |
| `finish.py` | Final reads and final build. It brought back ruled-out questions once: diff first |
| `audit.py` | Audit independent of the rule templates; exit 1 on any failure |
| `export_xlsx.py` | Write the bank to Excel, keeping Shivam's comments |
