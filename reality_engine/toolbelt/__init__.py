"""Ready-made, read-only tools for dsh workers (Task 02).

Each module is a small CLI with an importable function and JSON output:

    python -m reality_engine.toolbelt.sample_rows --db equity_intelligence --table insider_trades_v2 --n 5
    python -m reality_engine.toolbelt.find_docs --symbol DEEDEV --doc-type CONCALL_TRANSCRIPT

See ``README.md`` in this package for the full table.
"""

__all__ = [
    "sample_rows",
    "find_docs",
    "drive_fetch",
    "render_pages",
    "cost_ledger",
    "mod_test",
    "job_peek",
]
