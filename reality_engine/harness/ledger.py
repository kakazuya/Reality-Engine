"""The only writable database: append-only variant audit ledger."""
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

LEDGER = Path(__file__).resolve().parents[1] / "data/backtests/ledger.duckdb"


def previous_tests():
    """All prior tested rows remain in the multiple-testing family."""
    if not LEDGER.exists():
        return []
    import duckdb
    with duckdb.connect(str(LEDGER),read_only=True) as conn:
        return conn.execute('SELECT run_id,p FROM variants ORDER BY run_timestamp,row_id').fetchall()


def append_run_note(run_id, note):
    """Append a correction annotation without rewriting any variant row."""
    import duckdb
    with duckdb.connect(str(LEDGER)) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS run_notes (
            note_id VARCHAR PRIMARY KEY, run_id VARCHAR, noted_at TIMESTAMPTZ, note VARCHAR)''')
        conn.execute('INSERT INTO run_notes VALUES (?,?,?,?)',
                     [str(uuid4()),run_id,datetime.now(timezone.utc),note])


def annotate_superseded_h01_runs(corrected_run_id):
    """Keep defective tests in BH; append annotations, never update/delete."""
    import duckdb
    with duckdb.connect(str(LEDGER), read_only=True) as conn:
        runs = [r[0] for r in conn.execute("""SELECT DISTINCT run_id FROM variants
            WHERE card_id='H01' AND json_extract_string(variant_params, '$.entry_timing') IS NULL
            ORDER BY run_id""").fetchall()]
    for run in runs:
        append_run_note(run, json.dumps({'status': 'superseded_by_bugfix',
                                        'corrected_run_id': corrected_run_id,
                                        'reason': 'special-weekend missing exits booked as total losses; timing sensitivity added'}))
    return runs


def append_variants(rows, *, snapshot, git_hash, coverage, run_id=None,
                    source_hashes=None, card_id="H01"):
    import duckdb
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    run_id = run_id or str(uuid4())
    timestamp = datetime.now(timezone.utc)
    # No update/delete API. All pass/fail rows are one transaction.
    with duckdb.connect(str(LEDGER)) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS variants (
            row_id VARCHAR PRIMARY KEY, run_id VARCHAR, card_id VARCHAR,
            variant_params JSON, n_events BIGINT, mean_net_excess DOUBLE,
            median_net_excess DOUBLE, t_stat DOUBLE, p DOUBLE, bh_q DOUBLE,
            placebo_p DOUBLE, per_year_signs JSON, coverage JSON,
            code_git_hash VARCHAR, snapshot_name VARCHAR, run_timestamp TIMESTAMPTZ,
            status VARCHAR, details JSON)''')
        conn.execute("BEGIN TRANSACTION")
        try:
            for row in rows:
                conn.execute("INSERT INTO variants VALUES (" + ",".join(["?"] * 18) + ")", [
                    str(uuid4()), run_id, row.get("card_id", card_id), json.dumps(row["params"]), row["n_events"],
                    row.get("mean_net_excess"), row.get("median_net_excess"), row.get("t_stat"),
                    row.get("p"), row.get("bh_q"), row.get("placebo_p"),
                    json.dumps(row.get("per_year_signs", {})), json.dumps(coverage),
                    git_hash, snapshot, timestamp, row.get("status", "provisional"),
                    json.dumps({**row,'source_sha256':source_hashes}, default=str)])
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return run_id
