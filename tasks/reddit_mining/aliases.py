"""Resolve mined aliases through the same code path as the reality-data tool.

Writes tasks/reddit_mining/aliases.csv: alias, symbol, isin, frequency,
resolves, note. `resolves` is yes only when an ACTIVE equity match comes back.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "plugins" / "reality-data" / "server"))
import core  # noqa: E402

HERE = Path(__file__).resolve().parent
NOT_COMPANY = {
    "ADANI_GROUP": "group basket, no single ISIN",
    "TATA_GROUP": "group basket, no single ISIN",
    "BAJAJ_GROUP": "group basket, no single ISIN",
    "PSU_BASKET": "theme basket, no ISIN",
    "PSU_BANKS": "theme basket, no ISIN",
    "DEFENCE_THEME": "theme basket, no ISIN",
    "RAILWAY_THEME": "theme basket, no ISIN",
    "NIFTY50_INDEX": "index, not a company",
    "BANKNIFTY_INDEX": "index, not a company",
    "SENSEX_INDEX": "index, not a company",
    "ZERODHA": "unlisted broker",
    "GROWW": "broker; resolves only if a listed equity exists",
    "M&M": "",
    "LT": "",
    "SBIN": "",
    "HDFCBANK": "",
    "ICICIBANK": "",
}


def classify(alias: str) -> tuple[str, str, str, str]:
    """Return (resolves, symbol, isin, note)."""
    try:
        res = core.resolve(alias)
    except Exception as exc:  # resolve must never break the report
        return "error", "", "", f"resolve raised {type(exc).__name__}"
    matches = res.get("matches") or []
    equities = [m for m in matches if m.get("kind") == "equity"]
    active = [m for m in equities if (m.get("status") or "").lower() == "active"]
    if active:
        m = active[0]
        return "yes", m.get("nse_symbol") or "", m.get("isin") or "", m.get("name") or ""
    if equities:
        m = equities[0]
        return ("delisted_only", m.get("nse_symbol") or "", m.get("isin") or "",
                f"{m.get('name')}; last trade {m.get('last_trade')}")
    if matches:
        kinds = sorted({m.get("kind") for m in matches})
        return "wrong_kind", "", "", f"matched only {','.join(kinds)}"
    return "no", "", "", "no master/security/ETF match"


def main() -> int:
    stats = json.loads((HERE / "work" / "mine_stats.json").read_text(encoding="utf-8"))
    rows = []
    for a in stats["aliases"]:
        alias, sym, freq = a["alias"], a["symbol"], a["n"]
        if freq < 20:
            continue
        resolves, rsym, risin, note = classify(alias)
        if sym in NOT_COMPANY and rsym in {"", None}:
            note = NOT_COMPANY[sym] or note
        rows.append({
            "alias": alias,
            "target": sym,
            "symbol": rsym or (sym if sym not in NOT_COMPANY else ""),
            "isin": risin,
            "frequency": freq,
            "resolves": resolves,
            "note": note,
        })
    with (HERE / "aliases.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["alias", "target", "symbol", "isin",
                                           "frequency", "resolves", "note"])
        w.writeheader()
        w.writerows(rows)
    bad = [r for r in rows if r["resolves"] != "yes"]
    print(f"aliases {len(rows)}; not-resolving {len(bad)}")
    for r in sorted(bad, key=lambda x: -x["frequency"])[:15]:
        print(f'  {r["frequency"]:>5}  {r["alias"]:<16} {r["resolves"]:<13} {r["note"][:60]}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
