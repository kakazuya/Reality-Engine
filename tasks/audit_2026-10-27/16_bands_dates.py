"""A16 - price-band date continuity (fills the §8 claim)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
eq = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)
print("2026:", eq.execute("""SELECT COUNT(DISTINCT date), MIN(date), MAX(date), COUNT(*),
                                    COUNT(DISTINCT symbol)
                             FROM price_bands WHERE date >= '2026-01-01'""").fetchone())
print("2026 dates:", [r[0] for r in eq.execute(
    "SELECT DISTINCT date FROM price_bands WHERE date >= '2026-01-01' ORDER BY date")])
print("total distinct dates:", eq.execute("SELECT COUNT(DISTINCT date) FROM price_bands").fetchone())
print("2022-02:", eq.execute("""SELECT COUNT(DISTINCT date), MIN(date), MAX(date)
                                FROM price_bands WHERE date LIKE '2022-02%'""").fetchone())
print("2022-01 dates:", eq.execute(
    "SELECT COUNT(DISTINCT date) FROM price_bands WHERE date LIKE '2022-01%'").fetchone())
print("2020 first month:", eq.execute("""SELECT COUNT(DISTINCT date), MIN(date), MAX(date)
                                         FROM price_bands WHERE date LIKE '2020-10%'""").fetchone())
eq.close()
