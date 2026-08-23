"""Task 4: Business Model Profiles archetype/recurrence/pricing_power backfill"""

import sqlite3, pathlib
DB = pathlib.Path(__file__).parent.parent / "data" / "equity_intelligence.db"

SAMPLES = [
    ("HAL", "Tollbooth", 85, 5, 4, 3, "Defence OEM tollbooth, high switching, Govt contract"),
    ("TITAGARH", "Asset-Heavy OEM", 40, 3, 3, 4, "Rail OEM asset-heavy, capex timeline"),
    ("POLYPLEX", "Asset-Heavy OEM", 35, 2, 2, 4, "BOPET film asset-heavy, commodity + D-PAC"),
    ("RELIANCE", "Platform", 90, 5, 2, 5, "Jio platform network effects"),
]

def seed_demo():
    con=sqlite3.connect(DB)
    cur=con.cursor()
    cur.execute("DROP TABLE IF EXISTS business_model_profiles_demo")
    cur.execute("CREATE TABLE business_model_profiles_demo (symbol TEXT PRIMARY KEY, archetype TEXT, revenue_recurrence_pct REAL, pricing_power_score INTEGER, capital_intensity_score INTEGER, operating_leverage_score INTEGER, notes TEXT)")
    for sym, arch, rec, pp, ci, ol, notes in SAMPLES:
        cur.execute("INSERT OR REPLACE INTO business_model_profiles_demo VALUES (?,?,?,?,?,?,?)", (sym, arch, rec, pp, ci, ol, notes))
    con.commit()
    cur.execute("SELECT * FROM business_model_profiles_demo")
    for r in cur.fetchall():
        print(r)
    con.close()
    print(f"seeded {len(SAMPLES)} profiles")

if __name__ == "__main__":
    seed_demo()
