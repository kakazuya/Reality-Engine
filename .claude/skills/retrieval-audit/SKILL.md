---
name: retrieval-audit
description: Fresh-question, non-author audit of the reality-data lookup tools (numbers, call statements, guidance) graded R/P/W/M/N against page text, comparable round to round. Use after every retrieval fix, after loading new reads, or as a rolling surprise audit.
---

# Retrieval audit

Run by a read-only worker that did not write the fix (dsh off-peak, Hydrogen or Sonnet in peak). In-process, no MCP server, no model calls besides the grader.

## 1. Pick fresh companies
Eligible universe stores (deck >= 20 and transcript >= 1 obs rows, from `C:/RealityEngine/t242/load_universe.log`), EXCLUDING every company used in earlier audits (list them in the brief), `random.Random(<new seed>).sample(..., 8)`.

## 2. Call tools the way a model would
```python
sys.path.insert(0, "plugins/reality-data/server"); os.environ["REALITY_PILOT3_DB"] = "<store>"  # always pin: the registry can route a symbol to an older store
import lookups_pilot3 as L   # fact, kpi, statements, guidance, topic
```
Read the registered tool descriptions in `server.py` and call exactly as they instruct (named call: `date_from = date_to = <call date>`).
48 questions: per company 3 numbers (printed label + period only), 2 statements naming the call date, 1 guidance. Questions must be new; plain words, not codes.

## 3. Grade
R right value/quote first; P right but not first, or extra wrong first; W wrong served as the answer; M missing though held; N not held (checked in page text). Statements: record the rank of the asked quote. Re-open page text for every W and M.

## 4. Report (`C:/RealityEngine/t242/retrieval_auditN/report.md`)
48-row table with tool call and returned value; counts by slice; comparison table with earlier audits (audit 2: 33/8/3/4, audit 3: 32/12/0/4, audit 4: 45/3/0/0 of 48); mean quote rank; top 3 remaining causes with one example each -> the next fix brief.
A read-only worker cannot write the report: save its result yourself and update the STATE audit line.
