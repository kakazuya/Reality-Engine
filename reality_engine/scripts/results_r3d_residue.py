"""Count and inspect T-242 r3d residue groups on a results observation database (read-only).

Residue definition (T-242 r3d, narrowed in r3d2): rows on one ``(doc_key, page)`` sharing one
``(printed_label, measure, basis, segment, date_key)`` with >= 2 distinct numeric values AND the same
duration word on all of them (including no duration word on any of them). A second measure printing the
same label for the same date is a different line, not residue (r3d2 abstain).

Not run during the r3d implementation handoff; meant to be executed by the reviewer on a DB copy.
"""

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

from reality_engine.db.readonly import connect_ro
from reality_engine.scripts.extract_deck_figures import parse_number
from reality_engine.v2.observations import _results_period_date_and_dur, norm_space


def collect_r3d_residue(db_path: Path, limit: int = 20) -> dict[str, Any]:
    con = connect_ro(db_path, timeout_s=60)
    try:
        rows = con.execute(
            "SELECT doc_key, page, symbol, printed_label, measure, basis, segment, period, value, value_text, "
            "period_source, status FROM observation "
            "WHERE record_type='number' AND status != 'quarantined'"
        ).fetchall()
    finally:
        con.close()
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for doc_key, page, symbol, label, measure, basis, segment, period, val, vt, p_src, status in rows:
        lbl = norm_space(label)
        if not lbl:
            continue
        date_key, dur, bare_date = _results_period_date_and_dur(str(period or ""))
        if date_key is None:
            continue
        gkey = (str(doc_key), int(page), lbl.lower(), norm_space(measure).lower(),
                norm_space(basis).lower(), norm_space(segment).lower(), date_key)
        groups[gkey].append({
            "symbol": str(symbol or ""), "doc_key": str(doc_key), "page": int(page),
            "printed_label": lbl, "basis": norm_space(basis), "segment": norm_space(segment),
            "period": norm_space(period), "bare_date": bare_date, "dur": dur,
            "val": val, "value_text": norm_space(vt), "period_source": norm_space(p_src),
            "status": str(status or ""),
        })
    residue: list[tuple[tuple[Any, ...], list[dict[str, Any]]]] = []
    for gkey, items in groups.items():
        if len(items) < 2 or len({item["dur"] for item in items}) != 1:
            continue
        distinct_vals = {
            round(float(item["val"]), 6) if item["val"] is not None
            else (parse_number(item["value_text"]) if item["value_text"] else item["value_text"])
            for item in items
        }
        if len(distinct_vals) >= 2:
            residue.append((gkey, items))
    residue.sort(key=lambda pair: (pair[1][0]["symbol"], pair[0][0], pair[0][1], pair[0][2]))
    return {
        "group_count": len(residue),
        "row_count": sum(len(items) for _, items in residue),
        "sample": residue[:max(0, limit)],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="Path to a results observation SQLite DB copy")
    ap.add_argument("--limit", type=int, default=20, help="Max residue groups to print (default: 20)")
    args = ap.parse_args()
    summary = collect_r3d_residue(Path(args.db), limit=args.limit)
    print(f"residue_groups={summary['group_count']} residue_rows={summary['row_count']}")
    for _gkey, items in summary["sample"]:
        head = items[0]
        vals = [f"{it['value_text'] or it['val']} ({it['period']}; {it['status']}; {it['period_source'] or '-'})"
                for it in items]
        print(f"  {head['symbol']} {head['doc_key']} p{head['page']} | {head['printed_label']!r} "
              f"[{head['basis'] or '-'}] -> {', '.join(vals)}")


if __name__ == "__main__":
    main()
