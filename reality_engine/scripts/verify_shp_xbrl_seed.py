"""Independent re-read of the shareholding seed rows (acceptance check 3, 2026-10-31).

The parser in :mod:`reality_engine.scripts.fetch_shp_xbrl_pilot` reads the raw XBRL with
regexes and takes a class's percentage from the context with the largest number of axis
members.  This module reads the same files with :mod:`xml.etree.ElementTree` and a
different rule -- a class is the percentage fact inside the context whose
``CategoryOfShareholdersAxis`` member names that class, and exactly one such context may
exist -- so agreement between the two is evidence about the filing, not about shared code.

    python -m reality_engine.scripts.verify_shp_xbrl_seed            # .tmp seed and raw
    python -m reality_engine.scripts.verify_shp_xbrl_seed --seed <json> --raw <dir>

Exit code 1 on any row that disagrees or whose raw file is gone.  ``verify()`` is what the
pytest module calls; ``main()`` prints the table, with the classes the filing showed.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SEED = REPO / "reality_engine" / "tests" / "fixtures" / "shp_xbrl" / "seed20.json"
DEFAULT_RAW = REPO / ".tmp" / "shp_xbrl_raw"

#: member name (case-folded, trailing "Member" already stripped) -> holder class.  The
#: taxonomy spells mutual funds both ``MutualFundsOrUti`` and ``MutualFundsOrUTI`` (238 vs
#: 248 filings in this pilot), so the comparison is case-insensitive.
CLASS_BY_MEMBER = {
    "shareholdingofpromoterandpromotergroup": "promoter",
    "publicshareholding": "public",
    "institutionsforeign": "fii",
    "institutionsdomestic": "dii",
    "mutualfundsoruti": "mf",
    "insurancecompanies": "insurance",
}
PROMOTER = "shareholdingofpromoterandpromotergroup"
PATTERN = "shareholdingpattern"
PCT = "ShareholdingAsAPercentageOfTotalNumberOfShares"
PLEDGE_NUM = ("EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares",
              "PledgedOrEncumberedSharesHeldAsPercentageOfTotalNumberOfShares")
PLEDGE_FLAG = ("WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged",
               "WhetherAnySharesHeldByPromotersArePledgeOrOtherwiseEncumbered")


def _local(tag: str) -> str:
    """{namespace}Name -> Name."""
    return tag.rsplit("}", 1)[-1]


def _num(raw: str | None) -> float | None:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def read_filing(text: str) -> dict:
    """One filing -> ``{"classes", "pledge", "pledge_basis", "scale"}``.

    Raises ``ValueError`` when the same class has two contexts, because this reader has
    no tie-break rule and must not guess.
    """
    root = ET.fromstring(text)
    contexts: dict[str, tuple[str | None, str | None]] = {}
    for el in root.iter():
        if _local(el.tag) != "context":
            continue
        member = instant = None
        for sub in el.iter():
            name = _local(sub.tag)
            if name == "explicitMember" and sub.text:
                member = sub.text.strip().rsplit(":", 1)[-1]
                member = member[:-6] if member.endswith("Member") else member
            elif name == "instant" and sub.text:
                instant = sub.text.strip()
        contexts[el.get("id") or ""] = (member, instant)
    facts: dict[tuple[str, str], str] = {}
    for el in root.iter():
        cid = el.get("contextRef")
        if cid is not None and el.text is not None:
            facts[(_local(el.tag), cid)] = el.text.strip()

    total = None
    for cid, (member, _instant) in contexts.items():
        if (member or "").lower() == PATTERN:
            total = _num(facts.get((PCT, cid)))
    if total is None:
        parts = [_num(facts.get((PCT, cid))) for cid, (m, _i) in contexts.items()
                 if (m or "").lower() in (PROMOTER, "publicshareholding")]
        parts = [p for p in parts if p is not None]
        total = sum(parts) if parts else None
    factor = 100.0 if total is not None and total <= 1.5 else 1.0

    classes: dict[str, float] = {}
    for member, cls in CLASS_BY_MEMBER.items():
        cids = [c for c, (m, _i) in contexts.items() if (m or "").lower() == member]
        values = [v for v in (_num(facts.get((PCT, c))) for c in cids) if v is not None]
        if len(values) > 1:
            raise ValueError(f"{cls}: {len(values)} contexts, no tie-break rule")
        if values:
            classes[cls] = round(values[0] * factor, 4)

    pledge, basis = None, None
    promoter = [c for c, (m, _i) in contexts.items() if (m or "").lower() == PROMOTER]
    for cid in promoter:
        for concept in PLEDGE_NUM:
            value = _num(facts.get((concept, cid)))
            if value is not None:
                pledge, basis = round(value * factor, 4), "numeric"
                break
        if pledge is not None:
            break
    if pledge is None:
        flags = [v for (concept, _cid), v in facts.items() if concept in PLEDGE_FLAG]
        if flags and all(f.lower() in ("false", "0", "no") for f in flags):
            pledge, basis = 0.0, "boolean_false"
        elif flags:
            basis = "flag_true_no_value"
    return {"classes": classes, "pledge": pledge, "pledge_basis": basis,
            "scale": "percent" if factor == 100.0 else "fraction"}


def _body(raw_dir: Path, file: str) -> bytes:
    gz = raw_dir / (file + ".gz")
    if gz.exists():
        return gzip.decompress(gz.read_bytes())
    return (raw_dir / file).read_bytes()


def verify(seed_path: Path, raw_dir: Path) -> list[dict]:
    """Every seed row re-read from its raw file: ``[{..., "got", "ok", "why"}]``."""
    seed = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    cache: dict[str, dict] = {}
    out = []
    for row in seed["rows"]:
        if row["file"] not in cache:
            try:
                cache[row["file"]] = read_filing(_body(raw_dir, row["file"]).decode("utf-8", "replace"))
            except (OSError, ValueError, ET.ParseError) as exc:
                cache[row["file"]] = {"error": f"{type(exc).__name__}: {exc}"}
        got = cache[row["file"]]
        if "error" in got:
            out.append({**row, "got": None, "ok": False, "why": got["error"]})
            continue
        if row["atom"] == "hold.pct":
            value = got["classes"].get(row["dims"].split("=", 1)[1])
        else:
            value = got["pledge"]
        ok = value is not None and abs(value - row["value"]) <= 1e-6
        out.append({**row, "got": value, "ok": ok,
                    "why": "" if ok else (f"expected {row['value']}, read {value}")})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--seed", default=str(DEFAULT_SEED))
    ap.add_argument("--raw", default=str(DEFAULT_RAW))
    args = ap.parse_args()
    rows = verify(Path(args.seed), Path(args.raw))
    print(f"{'record':>8}  {'isin':<13} {'period':<10} {'known_at':<19} "
          f"{'atom':<16} {'dims':<24} {'seed':>7} {'reread':>7}  classes_reported")
    for r in rows:
        print(f"{r['record_id']:>8}  {r['isin']:<13} {r['period_end']:<10} "
              f"{r['known_at']:<19} {r['atom']:<16} {r['dims']:<24} "
              f"{r['value']:>7} {r['got']!s:>7}  {r['classes_reported']}")
    bad = [r for r in rows if not r["ok"]]
    print(f"\n{len(rows)} rows re-read with ElementTree (the parser uses regexes): "
          f"{len(rows) - len(bad)} agree, {len(bad)} disagree")
    for r in bad:
        print(f"  MISMATCH {r['record_id']} {r['atom']} {r['dims']}: {r['why']}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
