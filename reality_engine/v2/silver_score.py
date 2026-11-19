"""Silver-label scorer for the T-225 page-figure checker.

Reads separate reader SQLite files (``read_dots.db``, ``read_hy4.db``, ...)
read-only and marks cells where two or more distinct readers agree on value,
row label and column header as silver labels.  Scores each reader's checker
recall proxy (``verified / silver``), wrong-verified count on ``silver_wrong``
cells (must be 0), and loss reasons on unverified silver cells.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict, deque
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from reality_engine.v2.reference_geom import _header_tokens
from reality_engine.v2.reference_pages import _norm_value

_TOK_RE = re.compile(r"[a-z0-9]+")
_STATUS_RANK = {"verified": 3, "unverified": 2, "quarantined": 1}
_CSV_COLS = [
    "store", "tag", "doc_key", "page", "row_label", "col_header",
    "value_text", "status", "conflict", "silver_tags", "kind",
]


def _label_tokens(text: str) -> set[str]:
    return set(_TOK_RE.findall(str(text or "").casefold()))


def _jaccard(sa: set[str] | frozenset[str], sb: set[str] | frozenset[str]) -> float:
    return (len(sa & sb) / len(sa | sb)) if (sa and sb) else 0.0


def _label_match_toks(sa: frozenset[str], sb: frozenset[str]) -> bool:
    return bool(sa and sb) and (_jaccard(sa, sb) >= 0.6 or (min(len(sa), len(sb)) >= 2 and (sa <= sb or sb <= sa)))


def label_match(a: str, b: str) -> bool:
    """True when labels share Jaccard >= 0.6 or one contains the other (min 2 tokens)."""
    return _label_match_toks(frozenset(_label_tokens(a)), frozenset(_label_tokens(b)))


def header_match(a: str, b: str) -> bool:
    """True when header token sets match, falling back to label-style Jaccard when both are empty."""
    sa, sb = set(_header_tokens(a)), set(_header_tokens(b))
    return (_jaccard(_label_tokens(a), _label_tokens(b)) >= 0.6) if (not sa and not sb) else (sa == sb)


def load(paths: Sequence[Path | str]) -> list[dict[str, Any]]:
    """Load and per-tag-dedupe ``page_cell`` rows from reader DBs opened read-only."""
    deduped: dict[tuple[str, str, int, str, str, str], dict[str, Any]] = {}
    for p in paths:
        path = Path(p)
        tag = path.stem.removeprefix("read_")
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM page_cell").fetchall()
        finally:
            conn.close()
        for row in rows:
            d = dict(row)
            doc_key, page = str(d.get("doc_key") or ""), int(d.get("page") or 0)
            row_label, col_header = str(d.get("row_label") or ""), str(d.get("col_header") or "")
            value_text, status = str(d.get("value_text") or ""), str(d.get("status") or "")
            value_key = _norm_value(value_text)
            dkey = (tag, doc_key, page, " ".join(row_label.split()).casefold(),
                    " ".join(col_header.split()).casefold(), value_key)
            cell: dict[str, Any] = {
                "tag": tag, "doc_key": doc_key, "page": page, "row_label": row_label,
                "col_header": col_header, "value_text": value_text, "value_key": value_key,
                "status": status, "conflict": str(d.get("conflict") or ""),
                **{k: str(d.get(k) or "") for k in ("symbol", "known_at", "reader", "table_title", "unit_text")},
            }
            prev = deduped.get(dkey)
            if prev is None or _STATUS_RANK.get(status, 0) > _STATUS_RANK.get(prev["status"], 0):
                deduped[dkey] = cell
    return list(deduped.values())


def _hdr_ok(ha: frozenset[str], hb: frozenset[str], raw_a: str, raw_b: str) -> bool:
    return (ha == hb) if (ha or hb) else header_match(raw_a, raw_b)


def _classify(cells: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ltoks = [frozenset(_label_tokens(c.get("row_label", ""))) for c in cells]
    htoks = [frozenset(_header_tokens(c.get("col_header", ""))) for c in cells]
    vkeys = [c.get("value_key") or _norm_value(c.get("value_text", "")) for c in cells]
    val_groups: dict[tuple[str, int, str], list[int]] = defaultdict(list)
    for i, c in enumerate(cells):
        if vkeys[i] and ltoks[i]:
            val_groups[(c["doc_key"], c["page"], vkeys[i])].append(i)

    kinds = ["single"] * len(cells)
    silver_tags: list[list[str]] = [[] for _ in cells]
    clusters: list[dict[str, Any]] = []
    for (doc_key, page, vkey), idxs in val_groups.items():
        if len({cells[i]["tag"] for i in idxs}) < 2:
            continue
        adj: dict[int, list[int]] = defaultdict(list)
        for pos, i in enumerate(idxs):
            for j in idxs[pos + 1:]:
                if (cells[i]["tag"] != cells[j]["tag"] and _label_match_toks(ltoks[i], ltoks[j])
                        and _hdr_ok(htoks[i], htoks[j], cells[i]["col_header"], cells[j]["col_header"])):
                    adj[i].append(j)
                    adj[j].append(i)
        seen: set[int] = set()
        for start in idxs:
            if start in seen or start not in adj:
                continue
            comp, q = [], deque([start])
            seen.add(start)
            while q:
                cur = q.popleft()
                comp.append(cur)
                for nxt in adj[cur]:
                    if nxt not in seen:
                        seen.add(nxt)
                        q.append(nxt)
            tags = sorted({cells[i]["tag"] for i in comp})
            for i in comp:
                kinds[i], silver_tags[i] = "silver", tags
            clusters.append({
                "doc_key": doc_key, "page": page, "value_key": vkey,
                "row_label": cells[comp[0]]["row_label"], "col_header": cells[comp[0]]["col_header"],
                "tags": tags, "cells": [cells[i] for i in comp], "_idx": comp,
            })

    silver_b: dict[tuple[str, int, frozenset[str]], list[dict[str, Any]]] = defaultdict(list)
    for cl in clusters:
        silver_b[(cl["doc_key"], cl["page"], htoks[cl["_idx"][0]])].append(cl)
    cell_b: dict[tuple[str, int, frozenset[str]], list[int]] = defaultdict(list)
    for i, c in enumerate(cells):
        if vkeys[i] and ltoks[i]:
            cell_b[(c["doc_key"], c["page"], htoks[i])].append(i)

    for i, c in enumerate(cells):
        if kinds[i] == "silver" or not vkeys[i] or not ltoks[i]:
            continue
        bkey = (c["doc_key"], c["page"], htoks[i])
        hit_cl = next((
            cl for cl in silver_b.get(bkey, ())
            if cl["value_key"] != vkeys[i] and c["tag"] not in cl["tags"]
            and any(_label_match_toks(ltoks[i], ltoks[m])
                    and _hdr_ok(htoks[i], htoks[m], c["col_header"], cells[m]["col_header"])
                    for m in cl["_idx"])
        ), None)
        if hit_cl is not None:
            kinds[i], silver_tags[i] = "silver_wrong", hit_cl["tags"]
        elif any(j != i and kinds[j] != "silver" and cells[j]["tag"] != c["tag"] and vkeys[j] != vkeys[i]
                 and _label_match_toks(ltoks[i], ltoks[j])
                 and _hdr_ok(htoks[i], htoks[j], c["col_header"], cells[j]["col_header"])
                 for j in cell_b.get(bkey, ())):
            kinds[i] = "disputed"

    return clusters, [{**c, "value_key": vkeys[i], "kind": kinds[i], "silver_tags": silver_tags[i]}
                      for i, c in enumerate(cells)]


def silver(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return silver clusters where >= 2 distinct tags agree on (doc_key, page, value, label, header)."""
    return [{k: v for k, v in cl.items() if k != "_idx"} for cl in _classify(cells)[0]]


def conflict(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return cells classified as ``silver_wrong`` or ``disputed``."""
    return [c for c in _classify(cells)[1] if c["kind"] in ("silver_wrong", "disputed")]


def _empty_bucket() -> dict[str, Any]:
    return {"cells": 0, "silver": 0, "verified": 0, "recall_proxy": 0.0,
            "silver_wrong": 0, "wrong_verified": 0, "disputed": 0, "conflicts": Counter()}


def score(store_dir: Path | str) -> dict[str, Any]:
    """Score all reader DBs in ``store_dir`` per tag and per page."""
    store_path = Path(store_dir)
    paths = sorted(store_path.glob("read_*.db")) or sorted(store_path.glob("*.db"))
    _, rows = _classify(load(paths))
    by_tag: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    by_page: dict[tuple[str, int], dict[str, Any]] = defaultdict(_empty_bucket)
    for row in rows:
        for b in (by_tag[row["tag"]], by_page[(row["doc_key"], row["page"])]):
            b["cells"] += 1
            if row["kind"] == "silver":
                b["silver"] += 1
                if row["status"] == "verified":
                    b["verified"] += 1
                else:
                    b["conflicts"][row["conflict"] or row["status"] or "unknown"] += 1
            elif row["kind"] == "silver_wrong":
                b["silver_wrong"] += 1
                b["wrong_verified"] += int(row["status"] == "verified")
            elif row["kind"] == "disputed":
                b["disputed"] += 1
    for b in (*by_tag.values(), *by_page.values()):
        b["recall_proxy"] = (b["verified"] / b["silver"]) if b["silver"] else 0.0
    for b in by_page.values():
        b["lost"] = b["silver"] - b["verified"]
    return {"store": store_path.name, "by_tag": dict(sorted(by_tag.items())),
            "by_page": dict(sorted(by_page.items())), "rows": rows}


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for scoring reader DB directories."""
    ap = argparse.ArgumentParser(description="Score page-figure checker using cross-reader silver labels.")
    ap.add_argument("--dirs", nargs="+", required=True, help="Store directories holding read_*.db files.")
    ap.add_argument("--out", required=True, help="Output CSV path for per-cell rows.")
    ap.add_argument("--json", default=None, help="Optional JSON summary output path.")
    args = ap.parse_args(list(argv) if argv is not None else None)
    results = [score(d) for d in args.dirs]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_CSV_COLS)
        w.writeheader()
        for res in results:
            for r in res["rows"]:
                w.writerow({**{k: r[k] for k in _CSV_COLS if k not in ("store", "silver_tags")},
                            "store": res["store"], "silver_tags": ",".join(r["silver_tags"])})

    print(f"{'store':<10} {'tag':<10} {'cells':>7} {'silver':>7} {'verif':>7} {'recall':>7} {'s_wrong':>8} {'wrong_v':>8} {'disput':>7}")
    print("-" * 79)
    total_conflicts: Counter[str] = Counter()
    for res in results:
        for tag, m in res["by_tag"].items():
            total_conflicts.update(m["conflicts"])
            print(f"{res['store']:<10} {tag:<10} {m['cells']:>7d} {m['silver']:>7d} {m['verified']:>7d} "
                  f"{m['recall_proxy']:>7.3f} {m['silver_wrong']:>8d} {m['wrong_verified']:>8d} {m['disputed']:>7d}")
    lost_total = sum(total_conflicts.values())
    print(f"\nTop 15 conflict reasons on unverified silver cells (total lost = {lost_total}):")
    for reason, cnt in total_conflicts.most_common(15):
        print(f"  {cnt:>6d} ({(100.0 * cnt / lost_total) if lost_total else 0.0:5.1f}%)  {reason}")

    if args.json:
        jpath = Path(args.json)
        jpath.parent.mkdir(parents=True, exist_ok=True)
        payload = {"stores": [{
            "store": res["store"],
            "by_tag": {t: {**m, "conflicts": dict(m["conflicts"])} for t, m in res["by_tag"].items()},
            "by_page": [{"doc_key": dk, "page": pg, **{**m, "conflicts": dict(m["conflicts"])}}
                        for (dk, pg), m in sorted(res["by_page"].items(), key=lambda kv: kv[1]["lost"], reverse=True)],
        } for res in results], "top_conflicts": total_conflicts.most_common(15)}
        jpath.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
