"""Deterministic checks for the night loop (``tasks/night_loop/GOAL.md`` v2).

The Phase 1 question-set checks Q1-Q3 (:mod:`qset`), the Phase 2 measure A1 (:mod:`answerable`), the guards
A3-A7 (:mod:`guards`), the ACCEPT / REJECT decision (:mod:`decide`), the hidden loop launch (:mod:`run_loop`)
and the transcript audit (:mod:`audit`).  Standard library and sqlite3 only; no model or network call.

Every script prints a summary and writes a json the wrapper reads; the commands are in ``README.md`` here.
"""
