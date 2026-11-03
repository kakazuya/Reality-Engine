"""Q1-Q3: check the night loop's question set, and split it dev / hidden.

The set is JSON Lines, one question per line (``tasks/night_loop/questions/<SYMBOL>.jsonl``).  ``check``
validates every line's shape, then applies GOAL section 2: Q1 sector fit (every metric a question names is in
its sector's vocabulary, ``tasks/night_loop/sector_vocab.json``), Q2 coverage (lenses, orders, needed document
types) and Q3 variations (order-1 questions have >= 3 forms) and near-duplicates (normalised token Jaccard >
0.8 between any two questions).  ``split`` is the fixed hash split: dev 70 %, hidden 30 %.

Nothing here calls a model or the network, and a hidden question is never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "tasks" / "night_loop" / "questions"
VOCAB = ROOT / "tasks" / "night_loop" / "sector_vocab.json"
HIDDEN_OUT = ROOT / ".tmp" / "night_eval" / "hidden.jsonl"

ROW_TABLES = ("kpi_series", "fin_annual_line", "fin_quarter_xbrl", "ratio_panel", "guidance", "shp_category",
              "share_capital", "dividend_event", "price_delivery")
DOC_TYPES = ("deck", "transcript", "annual_report", "results", "press_release", "announcement")
ORDERS = (1, 2, 3)
MIN_LENS = 10
MIN_ORDER_RATE = {1: 0.40, 2: 0.25, 3: 0.10}
JACCARD = 0.8
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

_REQUIRED_STR = ("qid", "symbol", "sector", "text", "lens", "answer_kind", "as_of")


def norm_tokens(text: str) -> frozenset[str]:
    """Lower-case word tokens, punctuation dropped, one-letter words ignored."""
    return frozenset(t for t in re.findall(r"[a-z0-9%]+", (text or "").lower()) if len(t) > 1 or t.isdigit())


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def validate(q: dict[str, Any]) -> list[str]:
    """Every way one question breaks the format; an empty list means it is well formed."""
    errors: list[str] = []
    for key in _REQUIRED_STR:
        if not isinstance(q.get(key), str) or not q[key].strip():
            errors.append(f"{key}: missing or empty")
    if not DATE.fullmatch(str(q.get("as_of") or "")):
        errors.append("as_of: expected YYYY-MM-DD")
    if q.get("order") not in ORDERS:
        errors.append("order: expected 1, 2 or 3")
    for key in ("variations", "sector_fit", "needs"):
        if not isinstance(q.get(key), list):
            errors.append(f"{key}: expected a list")
    variations = q.get("variations") if isinstance(q.get("variations"), list) else []
    if variations and not all(isinstance(v, str) and v.strip() for v in variations):
        errors.append("variations: every form must be a non-empty string")
    fit = q.get("sector_fit") if isinstance(q.get("sector_fit"), list) else []
    if fit and not all(isinstance(m, str) and m.strip() for m in fit):
        errors.append("sector_fit: every metric id must be a non-empty string")
    mids = q.get("from_mids", "new")
    if mids != "new" and not (isinstance(mids, list) and all(isinstance(m, str) for m in mids)):
        errors.append('from_mids: expected a list of master-bank ids or "new"')
    if mids == "new" and not str(q.get("new_reason") or "").strip():
        errors.append('new_reason: required when from_mids is "new"')
    raw_needs = q.get("needs")
    needs = raw_needs if isinstance(raw_needs, list) else []
    for index, need in enumerate(needs):
        where = f"needs[{index}]"
        if not isinstance(need, dict):
            errors.append(f"{where}: expected an object")
            continue
        kind = need.get("kind")
        if kind == "row":
            if need.get("table") not in ROW_TABLES:
                errors.append(f"{where}.table: {need.get('table')!r} is not a typed table")
            if not isinstance(need.get("metric"), (str, type(None))):
                errors.append(f"{where}.metric: expected a string or null")
            if not str(need.get("period") or "").strip():
                errors.append(f"{where}.period: missing")
            if need.get("basis") not in (None, "consolidated", "standalone"):
                errors.append(f"{where}.basis: expected consolidated, standalone or null")
        elif kind == "text":
            if need.get("doc_type") not in DOC_TYPES:
                errors.append(f"{where}.doc_type: {need.get('doc_type')!r} is not a document type")
            terms = need.get("terms")
            if not (isinstance(terms, list) and terms and all(isinstance(t, str) and t.strip() for t in terms)):
                errors.append(f"{where}.terms: expected one or more non-empty strings")
            if need.get("period") is not None and not str(need["period"]).strip():
                errors.append(f"{where}.period: empty string, use null")
        else:
            errors.append(f"{where}.kind: expected 'row' or 'text'")
    return errors


def load_file(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Questions, schema errors and per-line problems from one JSONL file."""
    questions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            q = json.loads(raw)
        except ValueError as exc:
            errors.append({"file": path.name, "line": number, "qid": None, "errors": [f"invalid json: {exc}"]})
            continue
        if not isinstance(q, dict):
            errors.append({"file": path.name, "line": number, "qid": None, "errors": ["expected a json object"]})
            continue
        problems = validate(q)
        if problems:
            errors.append({"file": path.name, "line": number, "qid": q.get("qid"), "errors": problems})
        questions.append(q)
    return questions, errors, warnings


def load_dir(qdir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    questions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for path in sorted(qdir.glob("*.jsonl")):
        if path.name.startswith(("dev", "hidden")):
            continue
        found, problems, _ = load_file(path)
        questions.extend(found)
        errors.extend(problems)
    return questions, errors


def load_vocab(path: Path = VOCAB) -> dict[str, dict[str, list[str]]]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def q1_sector_fit(questions: list[dict[str, Any]], vocab: dict[str, dict[str, list[str]]]) -> dict[str, Any]:
    """Every sector_fit metric and every row-need metric must key that sector's vocabulary."""
    violations = []
    for q in questions:
        sector = str(q.get("sector") or "")
        allowed = vocab.get(sector)
        if not allowed:
            violations.append({"qid": q.get("qid"), "sector": sector, "metric": None, "kind": "unknown_sector"})
            continue
        for metric in q.get("sector_fit") or []:
            if metric not in allowed:
                violations.append({"qid": q.get("qid"), "sector": sector, "metric": metric, "kind": "sector_fit"})
        for need in q.get("needs") or []:
            if isinstance(need, dict) and need.get("kind") == "row" and need.get("metric"):
                if need["metric"] not in allowed:
                    violations.append({"qid": q.get("qid"), "sector": sector, "metric": need["metric"],
                                       "kind": "need", "table": need.get("table")})
    return {"violations": violations, "ok": not violations}


def order_rule(orders: list[int]) -> list[str]:
    """The Q2 order thresholds: 1st >= 40 %, 2nd >= 25 %, 3rd >= 10 % of the company's questions."""
    fails = []
    if not orders:
        return ["no questions"]
    for order in ORDERS:
        share = orders.count(order) / len(orders)
        if share + 1e-12 < MIN_ORDER_RATE[order]:
            fails.append(f"order {order}: {share:.0%} of {len(orders)} questions, needs >= {MIN_ORDER_RATE[order]:.0%}")
    return fails


def q2_coverage(questions: list[dict[str, Any]], held: tuple[str, ...] = ()) -> dict[str, Any]:
    """Per company: counts by lens, by order and by needed document type, with the GOAL thresholds."""
    companies: dict[str, dict[str, Any]] = {}
    by_company: dict[str, list[dict[str, Any]]] = {}
    for q in questions:
        by_company.setdefault(str(q.get("symbol") or "?"), []).append(q)
    for symbol, group in sorted(by_company.items()):
        lens: dict[str, int] = {}
        orders = [int(q.get("order") or 0) for q in group]
        doc_types: dict[str, int] = {}
        for q in group:
            lens[str(q.get("lens"))] = lens.get(str(q.get("lens")), 0) + 1
            for need in q.get("needs") or []:
                if isinstance(need, dict) and need.get("kind") == "text":
                    dtype = str(need.get("doc_type"))
                    doc_types[dtype] = doc_types.get(dtype, 0) + 1
        fails = order_rule(orders)
        for name, count in sorted(lens.items()):
            if count < MIN_LENS:
                fails.append(f"lens {name}: {count} questions, needs >= {MIN_LENS}")
        for dtype in held:
            if not doc_types.get(dtype):
                fails.append(f"document type {dtype}: no question needs it")
        companies[symbol] = {
            "questions": len(group), "lens": lens, "orders": {str(o): orders.count(o) for o in ORDERS},
            "order_rates": {str(o): round(orders.count(o) / len(group), 4) for o in ORDERS},
            "doc_types": doc_types, "fails": fails,
        }
    return {"companies": companies, "ok": bool(companies) and all(not c["fails"] for c in companies.values())}


def q3_variations(questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Order-1 questions need >= 3 forms; any two questions above Jaccard 0.8 are near-duplicates."""
    short = [q.get("qid") for q in questions if q.get("order") == 1 and len(q.get("variations") or []) < 3]
    duplicates = []
    forms = [(str(q.get("qid")),
              [norm_tokens(str(q.get("text") or ""))] + [norm_tokens(str(v)) for v in q.get("variations") or []])
             for q in questions]
    for index, (qid, tokens) in enumerate(forms):
        for other_qid, other in forms[index + 1:]:
            score = max((jaccard(a, b) for a in tokens for b in other), default=0.0)
            if score > JACCARD:
                duplicates.append({"qid": qid, "other": other_qid, "jaccard": round(score, 3)})
    return {"short_variations": short, "duplicates": duplicates, "ok": not short and not duplicates}


def check(qdir: Path, vocab_path: Path = VOCAB, held: tuple[str, ...] = ()) -> dict[str, Any]:
    questions, schema_errors = load_dir(qdir)
    qids = [q.get("qid") for q in questions]
    duplicates = sorted({qid for qid in qids if qid and qids.count(qid) > 1})
    if duplicates:
        schema_errors.append({"file": "*", "line": 0, "qid": ",".join(duplicates), "errors": ["duplicate qid"]})
    report = {
        "questions": len(questions),
        "schema_errors": schema_errors,
        "q1": q1_sector_fit(questions, load_vocab(vocab_path)),
        "q2": q2_coverage(questions, held),
        "q3": q3_variations(questions),
    }
    report["ok"] = (not schema_errors and report["q1"]["ok"] and report["q2"]["ok"] and report["q3"]["ok"])
    return report


def is_dev(qid: str) -> bool:
    """The fixed split: dev when the first 8 hex digits of sha256(qid) mod 10 are below 7."""
    return int(hashlib.sha256(qid.encode("utf-8")).hexdigest()[:8], 16) % 10 < 7


def split(qdir: Path, out: Path | None = None, hidden: Path | None = None) -> dict[str, Any]:
    questions, schema_errors = load_dir(qdir)
    dev_path = out or (qdir / "dev.jsonl")
    hidden_path = hidden or HIDDEN_OUT
    dev = [q for q in questions if is_dev(str(q.get("qid")))]
    held = [q for q in questions if not is_dev(str(q.get("qid")))]
    for path, rows in ((dev_path, dev), (hidden_path, held)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    counts: dict[str, dict[str, int]] = {}
    for label, rows in (("dev", dev), ("hidden", held)):
        for q in rows:
            symbol = str(q.get("symbol") or "?")
            counts.setdefault(symbol, {"dev": 0, "hidden": 0})[label] += 1
    return {"dev": len(dev), "hidden": len(held), "total": len(questions), "schema_errors": schema_errors,
            "by_company": dict(sorted(counts.items())), "dev_path": str(dev_path), "hidden_path": str(hidden_path)}


def _print_check(report: dict[str, Any]) -> None:
    print(f"questions: {report['questions']}  ok: {report['ok']}")
    for err in report["schema_errors"]:
        print(f"  SCHEMA {err['file']}:{err['line']} {err.get('qid')}: {'; '.join(err['errors'])}")
    for violation in report["q1"]["violations"]:
        print(f"  Q1 {violation['qid']} sector {violation['sector']}: {violation['metric']} ({violation['kind']})")
    print(f"  Q1 sector fit: {len(report['q1']['violations'])} violations")
    for symbol, company in report["q2"]["companies"].items():
        rates = " ".join(f"{o} {company['order_rates'][o]:.0%}" for o in ("1", "2", "3"))
        print(f"  Q2 {symbol}: {company['questions']} questions, {len(company['lens'])} lenses, orders {rates},"
              f" doc types {company['doc_types'] or '{}'}")
        for fail in company["fails"]:
            print(f"     FAIL {fail}")
    print(f"  Q3 short variations: {report['q3']['short_variations'] or 0}  duplicates:"
          f" {len(report['q3']['duplicates'])}")
    for dup in report["q3"]["duplicates"]:
        print(f"     DUP {dup['qid']} ~ {dup['other']} ({dup['jaccard']})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qset", description="night loop question-set checks (Q1-Q3) and split")
    sub = parser.add_subparsers(dest="cmd", required=True)
    one = sub.add_parser("check", help="validate, Q1 sector fit, Q2 coverage, Q3 variations/duplicates")
    one.add_argument("dir", nargs="?", default=str(QUESTIONS))
    one.add_argument("--vocab", default=str(VOCAB))
    one.add_argument("--held", default="", help="comma list of document types every company must need")
    one.add_argument("--out", default="", help="write the report json here")
    two = sub.add_parser("split", help="fixed 70/30 hash split: dev.jsonl here, hidden.jsonl under .tmp")
    two.add_argument("dir", nargs="?", default=str(QUESTIONS))
    two.add_argument("--out", default="")
    two.add_argument("--hidden", default="")
    args = parser.parse_args(argv)
    if args.cmd == "check":
        held = tuple(h.strip() for h in args.held.split(",") if h.strip())
        report = check(Path(args.dir), Path(args.vocab), held)
        _print_check(report)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return 0 if report["ok"] else 1
    report = split(Path(args.dir), Path(args.out) if args.out else None,
                   Path(args.hidden) if args.hidden else None)
    print(f"dev {report['dev']}  hidden {report['hidden']}  total {report['total']}")
    for symbol, counts in report["by_company"].items():
        print(f"  {symbol}: dev {counts['dev']}  hidden {counts['hidden']}")
    print(f"  dev -> {report['dev_path']}\n  hidden -> {report['hidden_path']}")
    for err in report["schema_errors"]:
        print(f"  SCHEMA {err['file']}:{err['line']} {err.get('qid')}: {'; '.join(err['errors'])}")
    return 0 if not report["schema_errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
