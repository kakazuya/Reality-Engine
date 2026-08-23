"""Seed countries + industries for Fundamental Reality Engine — PG primary, SQLite fallback demo."""

import json
import pathlib
import sqlite3

SEED_PATH = pathlib.Path(__file__).parent.parent / "data" / "seed" / "fundamental_seed.json"
DB_PATH = pathlib.Path(__file__).parent.parent / "data" / "equity_intelligence.db"

def load_seed():
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))

def seed_sqlite_demo():
    """Demo: store seed into SQLite table fundamental_seed_demo for verification without PG."""
    data = load_seed()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DROP TABLE IF EXISTS seed_countries_demo")
    cur.execute("CREATE TABLE seed_countries_demo (country_id TEXT PRIMARY KEY, country_name TEXT, political_stability_score REAL, rule_of_law_index REAL, currency TEXT)")
    for c in data["countries"]:
        cur.execute("INSERT OR REPLACE INTO seed_countries_demo VALUES (?,?,?,?,?)", (c["country_id"], c["country_name"], c["political_stability_score"], c["rule_of_law_index"], c["currency"]))
    cur.execute("DROP TABLE IF EXISTS seed_industries_demo")
    cur.execute("CREATE TABLE seed_industries_demo (industry_name TEXT PRIMARY KEY, sector_name TEXT, secular_growth_score REAL, lifecycle_stage TEXT, tam_growth_cagr REAL)")
    for ind in data["industries"]:
        cur.execute("INSERT OR REPLACE INTO seed_industries_demo VALUES (?,?,?,?,?)", (ind["industry_name"], ind["sector_name"], ind["secular_growth_score"], ind["lifecycle_stage"], ind["tam_growth_cagr"]))
    con.commit()
    # Verify
    cur.execute("SELECT COUNT(*) FROM seed_countries_demo")
    print(f"seed_countries_demo {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM seed_industries_demo WHERE secular_growth_score>=4.0")
    print(f"industries >=4.0 (pass funnel) {cur.fetchone()[0]}/12")
    cur.execute("SELECT industry_name, secular_growth_score FROM seed_industries_demo ORDER BY secular_growth_score DESC LIMIT 5")
    for r in cur.fetchall():
        print(r)
    con.close()

if __name__ == "__main__":
    seed_sqlite_demo()
    print("Seed demo complete — PG `psql -f postgres_schema.sql` + `COPY` will use same JSON via `seed_fundamental.sql` when PG is provisioned (RDS/Cloud SQL).")
