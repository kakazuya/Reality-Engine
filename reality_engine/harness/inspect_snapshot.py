"""Read-only schema and small metadata audit. No joins before DESCRIBE.

Run: python -m reality_engine.harness.inspect_snapshot
"""
import json
from .data import Snapshot

TABLES = ("results_key", "results_filings", "bse_ann", "security_master",
          "px_daily", "px_nse", "px_bse", "index_tri", "tax_rules",
          "symbol_isin_history", "snapshot_meta", "truth_report",
          "unexplained_jumps")


def main():
    with Snapshot() as snapshot:
        tables = {r[0] for r in snapshot.connection.execute("SHOW TABLES").fetchall()}
        result = {"schemas": {t: snapshot.describe(t) for t in TABLES},
                  "tables": sorted(tables)}
        if "substrate_quarantine" in tables:
            result["schemas"]["substrate_quarantine"] = snapshot.describe("substrate_quarantine")
        for t in ("snapshot_meta", "truth_report", "tax_rules"):
            result[t] = snapshot.connection.execute(f'SELECT * FROM "{t}" LIMIT 100').fetchall()
        print(json.dumps(result, default=str, indent=2))


if __name__ == "__main__":
    main()
