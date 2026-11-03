"""A3-A7: the night loop's guards, measured on a branch's pilot3 database and its build code.

A3 provenance -- on the rows a branch added (or, with no ``--base-db``, every quoted row up to ``--limit``), the
value is printed in the row's quote and the quote's first 80 normalised characters are on the cited ``doc_page``;
the guard passes at >= 98 %.  A4 counts -- XBRL disagreement of deck / release / transcript figures, point-in-time
violations, duplicate documents, junk rows: the wrapper compares them against the base run and they must not rise.
A5 build -- the changed ``build.py`` parts run on a COPY of the database with a ``sitecustomize`` that makes every
socket connect raise, and the added lines under ``reality_engine/pilot3/`` are scanned for company literals, ISINs,
BSE codes, raw-data paths and hashes; the protected files are listed here too.  A7 cost -- pages read and build
seconds, passed through from the web session's ``--timing`` json.

Read-only on the database; the only writes are under ``.tmp/night_eval``.  No model call, no network.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from reality_engine.night_eval.answerable import period_bounds

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".tmp" / "night_eval" / "guards"

PROTECTED_FILES = ("tasks/night_loop/GOAL.md", "tasks/RULINGS.md", "docs/DB_BUILD_GUIDELINES.md", "AGENTS.md",
                   ".mcp.json")
PROTECTED_PREFIXES = ("tasks/night_loop/questions/", "reality_engine/night_eval/", "plugins/dsh-worker/")

PROV_TABLES = {
    "kpi_series": ("symbol", "metric", "fiscal_period", "basis", "value"),
    "fin_annual_line": ("symbol", "line_item", "fiscal_year", "basis", "value"),
    "guidance": ("symbol", "metric", "target_period", "low", "high"),
}

KPI_TO_XBRL = {
    "revenue": ("revenue_from_operations", "revenue"),
    "revenue_from_operations": ("revenue_from_operations", "revenue"),
    "ebitda": ("ebitda",),
    "pat": ("pat", "profit_after_tax"),
    "profit_after_tax": ("profit_after_tax", "pat"),
    "finance_cost": ("finance_cost", "finance_costs"),
}

PART_FILES = {
    "registry": ("registry.py", "docs_collect.py"),
    "pages": ("ocr.py", "hp_ocr.py"),
    "stores": ("stores.py",),
    "ratios": ("ratios.py",),
    "kpi": ("kpi.py", "kpi_oracle.py"),
    "transcripts": ("transcripts.py", "statements.py", "call_dates.py"),
    "guidance": ("guidance.py",),
}
ALL_PARTS = ("registry", "pages", "stores", "ratios", "kpi", "transcripts", "guidance")

LITERAL_PATTERNS = (
    ("company", re.compile(r"\b(?:KEC|BAJFINANCE|HINDALCO|BAJAJ[A-Z0-9_]*)\b")),
    ("isin", re.compile(r"\bINE[A-Z0-9]{9}\b")),
    ("bse_code", re.compile(r"(?<![\d.])\d{6}(?![\d.])")),
    ("raw_path", re.compile(r"(?:pdfs|decks_full)[\\/]")),
    ("sha256", re.compile(r"\b[0-9a-f]{64}\b", re.I)),
)

SOCKET_GUARD = '''"""Night loop A5: the build may not open a socket."""
import socket


def _blocked(*args, **kwargs):
    raise PermissionError("night_eval A5: network blocked during the build")


socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
'''


def open_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").casefold()).strip()


def value_forms(value: Any) -> list[str]:
    """The spellings a quote may print a stored number in."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return []
    forms = []
    for text in (f"{number:.0f}" if number.is_integer() else "", f"{number:.1f}", f"{number:.2f}",
                 f"{number:,.0f}" if number.is_integer() else "", f"{number:,.2f}", f"{number:.3f}"):
        if text and text not in forms:
            forms.append(text)
    return forms


def value_in_quote(value: Any, quote: str) -> bool:
    flat = _norm(quote)
    squashed = flat.replace(",", "")
    for form in value_forms(value):
        if form in flat or form.replace(",", "") in squashed:
            return True
    return False


# --- git and diff ------------------------------------------------------------------------------------
def git(*args: str, cwd: Path = ROOT) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8")
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()[:300]}")
    return done.stdout


def changed_paths(base: str, branch: str, repo: Path = ROOT) -> list[tuple[str, str]]:
    """(status, path) for every file that differs between the two refs; renames report the new path."""
    out = []
    for line in git("diff", "--name-status", f"{base}...{branch}", cwd=repo).splitlines():
        fields = line.split("\t")
        if len(fields) >= 2:
            out.append((fields[0][:1], fields[-1]))
    return out


def diff_text(base: str, branch: str, repo: Path = ROOT, paths: list[str] | None = None) -> str:
    args = ["diff", "-U0", f"{base}...{branch}"]
    if paths:
        args += ["--", *paths]
    return git(*args, cwd=repo)


def parse_added(text: str) -> dict[str, list[tuple[int, str]]]:
    """{path: [(new line number, line)]} for the lines a diff adds."""
    added: dict[str, list[tuple[int, str]]] = {}
    path, number = None, 0
    for raw in text.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            path = path[2:] if path.startswith("b/") else path
            continue
        if raw.startswith("--- "):
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            number = int(match.group(1)) if match else 0
            continue
        if path is None:
            continue
        if raw.startswith("+"):
            added.setdefault(path, []).append((number, raw[1:]))
            number += 1
        elif raw.startswith(" "):
            number += 1
    return added


def parse_removed(text: str) -> dict[str, list[str]]:
    """{path: [line]} for the lines a diff removes or replaces."""
    removed: dict[str, list[str]] = {}
    path = None
    for raw in text.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            path = path[2:] if path.startswith("b/") else path
            continue
        if raw.startswith("--- ") or raw.startswith("@@") or path is None:
            continue
        if raw.startswith("-"):
            removed.setdefault(path, []).append(raw[1:])
    return removed


def literal_violations(added: dict[str, list[tuple[int, str]]]) -> list[dict[str, Any]]:
    """Company literals, ISINs, BSE codes, raw-data paths and hashes on the lines a branch added."""
    found = []
    for path, lines in sorted(added.items()):
        for number, line in lines:
            for kind, pattern in LITERAL_PATTERNS:
                match = pattern.search(line)
                if match:
                    found.append({"path": path, "line": number, "kind": kind, "token": match.group(0),
                                  "text": line.strip()[:160]})
                    break
    return found


def is_protected(path: str) -> bool:
    return path in PROTECTED_FILES or any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def protected_violations(changed: list[str], removed: dict[str, list[str]],
                         existing_tests: set[str]) -> list[dict[str, Any]]:
    """Protected files touched at all, and existing test files whose lines were removed or changed."""
    found: list[dict[str, Any]] = [{"path": path, "kind": "protected_path"} for path in sorted(set(changed))
                                   if is_protected(path)]
    for path in sorted(existing_tests):
        if path in set(changed) and removed.get(path):
            found.append({"path": path, "kind": "test_assertion", "lines": removed[path][:5]})
    return found


def existing_tests(base: str, repo: Path = ROOT) -> set[str]:
    out = git("ls-tree", "-r", "--name-only", base, "--", "reality_engine/tests", cwd=repo)
    return {line for line in out.splitlines() if line.endswith(".py")}


# --- A3 provenance -----------------------------------------------------------------------------------
def _prov_rows(con: sqlite3.Connection, table: str, limit: int | None) -> list[sqlite3.Row]:
    cap = f" LIMIT {int(limit)}" if limit else ""
    sql = (f'SELECT {", ".join(PROV_TABLES[table])}, quote, doc_key, page FROM "{table}" '
           f"WHERE quote IS NOT NULL AND trim(quote) <> '' AND doc_key IS NOT NULL AND page IS NOT NULL "
           f"ORDER BY rowid{cap}")
    return con.execute(sql).fetchall()


def _key(row: sqlite3.Row, columns: tuple[str, ...]) -> tuple:
    return tuple(row[c] for c in columns)


def a3_provenance(db: Path, base_db: Path | None = None, limit: int = 4000) -> dict[str, Any]:
    """Value in quote and quote's first 80 normalised chars on the cited page: >= 98 % of the rows checked."""
    con = open_ro(db)
    try:
        tables = _tables(con)
        rows: list[tuple[str, sqlite3.Row, tuple]] = []
        for table, columns in PROV_TABLES.items():
            if table not in tables:
                continue
            for row in _prov_rows(con, table, None if base_db else limit):
                rows.append((table, row, _key(row, columns)))
        if base_db is not None:
            base = open_ro(base_db)
            try:
                seen = {(table, _key(row, PROV_TABLES[table]))
                        for table in PROV_TABLES if table in _tables(base) for row in _prov_rows(base, table, None)}
            finally:
                base.close()
            rows = [item for item in rows if (item[0], item[2]) not in seen]
        pages: dict[tuple[str, int], str | None] = {}
        for _table, row, _key_row in rows:
            pages[(str(row["doc_key"]), int(row["page"]))] = None
        keys = list(pages)
        for start in range(0, len(keys), 400):
            chunk = keys[start:start + 400]
            marks = ",".join("(?,?)" for _ in chunk)
            params = [value for pair in chunk for value in pair]
            for found in con.execute(f"SELECT doc_key, page, text FROM doc_page WHERE (doc_key, page) IN ({marks})",
                                     params):
                pages[(str(found["doc_key"]), int(found["page"]))] = found["text"] or ""
        value_ok = page_ok = passed = page_missing = 0
        examples = []
        for table, row, _key_row in rows:
            columns = PROV_TABLES[table]
            values = [row[c] for c in columns if c in ("value", "low", "high") and row[c] is not None]
            good_value = bool(values) and all(value_in_quote(value, row["quote"]) for value in values)
            text = pages.get((str(row["doc_key"]), int(row["page"])))
            head = _norm(row["quote"])[:80]
            good_page = bool(text) and bool(head) and head in _norm(text)
            page_missing += text is None
            value_ok += good_value
            page_ok += good_page
            passed += good_value and good_page
            if (not good_value or not good_page) and len(examples) < 5:
                examples.append({"table": table, "symbol": row["symbol"], "doc_key": row["doc_key"],
                                 "page": row["page"], "value_in_quote": good_value, "quote_on_page": good_page,
                                 "quote": str(row["quote"])[:120]})
        checked = len(rows)
        rate = round(passed / checked, 4) if checked else None
        return {"table": "doc_page", "checked": checked, "value_in_quote": value_ok, "quote_on_page": page_ok,
                "passed": passed, "page_missing": page_missing, "rate": rate,
                "ok": rate is None or rate >= 0.98,
                "scope": "added_rows" if base_db else "all_rows", "examples": examples}
    finally:
        con.close()


# --- A4 counts ---------------------------------------------------------------------------------------
def a4_counts(db: Path) -> dict[str, Any]:
    """The junk and disagreement counts the wrapper compares against the base run ("not up")."""
    con = open_ro(db)
    try:
        tables = _tables(con)
        counts: dict[str, int] = {}
        detail: dict[str, Any] = {}
        counts["duplicate_sha256"] = 0
        if "doc" in tables:
            groups = con.execute("SELECT sha256, COUNT(*) c FROM doc WHERE sha256 IS NOT NULL AND sha256 <> '' "
                                 "GROUP BY sha256 HAVING c > 1").fetchall()
            counts["duplicate_sha256"] = sum(int(g[1]) - 1 for g in groups)
            detail["duplicate_sha256"] = [(g[0][:12], g[1]) for g in groups[:10]]
        counts["xbrl_disagreements"] = 0
        if "kpi_series" in tables and "fin_quarter_xbrl" in tables:
            # a segment row compared with a company total is not a disagreement: only the total dimension counts
            dimension = (" AND COALESCE(dimension, 'total') = 'total'"
                         if "dimension" in _columns(con, "kpi_series") else "")
            kpi = con.execute("SELECT symbol, metric, fiscal_period, basis, value FROM kpi_series "
                              "WHERE value IS NOT NULL AND metric IN (%s)%s"
                              % (",".join("?" * len(KPI_TO_XBRL)), dimension),
                              tuple(KPI_TO_XBRL)).fetchall()
            lines = sorted({line for lines_ in KPI_TO_XBRL.values() for line in lines_})
            xbrl: dict[tuple, float] = {}
            for row in con.execute("SELECT symbol, fiscal_period, basis, line_item, value FROM fin_quarter_xbrl "
                                   "WHERE value IS NOT NULL AND line_item IN (%s)" % ",".join("?" * len(lines)),
                                   tuple(lines)):
                xbrl.setdefault((row["symbol"], row["fiscal_period"], row["basis"], row["line_item"]), row["value"])
            misses = []
            for row in kpi:
                for line in KPI_TO_XBRL.get(str(row["metric"]), ()):
                    other = xbrl.get((row["symbol"], row["fiscal_period"], row["basis"], line))
                    if other is None:
                        continue
                    if abs(float(row["value"]) - float(other)) > max(abs(float(other)) * 0.01, 0.01):
                        misses.append((row["symbol"], row["metric"], row["fiscal_period"], row["value"], other))
                    break
            counts["xbrl_disagreements"] = len(misses)
            detail["xbrl_disagreements"] = misses[:10]
        counts["period_after_doc"] = 0
        if "kpi_series" in tables and "doc" in tables:
            misses = []
            for row in con.execute("SELECT k.symbol, k.metric, k.fiscal_period, d.filing_date FROM kpi_series k "
                                   "JOIN doc d ON d.doc_key = k.doc_key WHERE d.filing_date IS NOT NULL"):
                bounds = period_bounds(str(row["fiscal_period"] or ""))
                if bounds and str(row["filing_date"])[:10] < bounds[0]:
                    misses.append((row["symbol"], row["metric"], row["fiscal_period"], row["filing_date"]))
            counts["period_after_doc"] = len(misses)
            detail["period_after_doc"] = misses[:10]
        counts["known_before_filing"] = 0
        misses = []
        for table in ("kpi_series", "fin_annual_line", "guidance"):
            if table not in tables or "doc" not in tables:
                continue
            for row in con.execute(f"SELECT t.symbol, t.known_at, d.filing_date FROM {table} t "
                                   f"JOIN doc d ON d.doc_key = t.doc_key WHERE t.known_at IS NOT NULL "
                                   f"AND d.filing_date IS NOT NULL"):
                if str(row["known_at"])[:10] < str(row["filing_date"])[:10]:
                    misses.append((table, row["symbol"], row["known_at"], row["filing_date"]))
        counts["known_before_filing"] = len(misses)
        detail["known_before_filing"] = misses[:10]
        counts["pages_above_p99"] = 0
        counts["fact_rows"] = 0
        per_page: dict[tuple[str, int], int] = {}
        for table in ("kpi_series", "fin_annual_line", "guidance"):
            if table not in tables:
                continue
            for row in con.execute(f"SELECT doc_key, page, COUNT(*) c FROM {table} "
                                   f"WHERE doc_key IS NOT NULL AND page IS NOT NULL GROUP BY doc_key, page"):
                per_page[(str(row["doc_key"]), int(row["page"]))] = int(row["c"])
        counts["fact_rows"] = sum(per_page.values())
        if per_page:
            values = sorted(per_page.values())
            p99 = values[max(0, math.ceil(0.99 * len(values)) - 1)]
            above = [count for count in values if count > p99]
            counts["pages_above_p99"] = len(above)
            counts["rows_above_p99"] = sum(above)
            detail["p99_rows_per_page"] = p99
        counts["margins_over_100"] = 0
        if "ratio_panel" in tables:
            row = con.execute("SELECT COUNT(*) FROM ratio_panel WHERE value IS NOT NULL AND "
                              "(lower(metric) LIKE '%margin%') AND abs(value) > 100").fetchone()
            counts["margins_over_100"] = int(row[0])
        return {"counts": counts, "detail": detail}
    finally:
        con.close()


# --- A5 build ----------------------------------------------------------------------------------------
def parts_for(changed: list[str]) -> list[str]:
    """The build parts a branch's changed pilot3 files can affect; ``build.py``/``schema.py``/a new module means all."""
    hit: set[str] = set()
    unknown = False
    for path in changed:
        if not path.startswith("reality_engine/pilot3/"):
            continue
        name = Path(path).name
        if name in ("build.py", "schema.py"):
            return list(ALL_PARTS)
        matched = [part for part, files in PART_FILES.items() if name in files]
        if matched:
            hit.update(matched)
        else:
            unknown = True
    return list(ALL_PARTS) if unknown else [part for part in ALL_PARTS if part in hit]


def socket_guard(workdir: Path) -> Path:
    """A directory holding ``sitecustomize.py``; put it first on PYTHONPATH and every socket connect raises."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "sitecustomize.py").write_text(SOCKET_GUARD, encoding="utf-8")
    return workdir


def run_blocked(cmd: list[str], cwd: Path, guard_dir: Path, timeout: int = 1800) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(guard_dir), env.get("PYTHONPATH", "")]).strip(os.pathsep)
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def run_build_part(part: str, db_copy: Path, guard_dir: Path, repo: Path = ROOT,
                   timeout: int = 1800) -> dict[str, Any]:
    done = run_blocked([sys.executable, "-m", "reality_engine.pilot3.build", "--part", part,
                        "--out", str(db_copy)], repo, guard_dir, timeout)
    return {"part": part, "returncode": done.returncode, "tail": (done.stdout + done.stderr)[-800:]}


def a5_build(db: Path, base: str, branch: str, workdir: Path = WORK, repo: Path = ROOT,
             parts: list[str] | None = None,
             build_runner: Callable[[str, Path], dict[str, Any]] | None = None) -> dict[str, Any]:
    """No company literals in added extractor lines, no protected file touched, and the build runs socket-free."""
    changed = changed_paths(base, branch, repo)
    text = diff_text(base, branch, repo)
    added = parse_added(text)
    removed = parse_removed(text)
    literals = literal_violations({path: lines for path, lines in added.items()
                                   if path.startswith("reality_engine/pilot3/")})
    protected = protected_violations([path for _status, path in changed], removed, existing_tests(base, repo))
    parts = list(parts) if parts is not None else parts_for([path for _status, path in changed])
    guard = socket_guard(Path(workdir))
    runner = build_runner or (lambda part, copy: run_build_part(part, copy, guard, repo))
    builds = []
    if parts and Path(db).is_file():
        Path(workdir).mkdir(parents=True, exist_ok=True)
        for part in parts:
            copy = Path(workdir) / f"pilot3_{part}.db"
            shutil.copyfile(db, copy)
            builds.append(runner(part, copy))
    ok = not literals and not protected and all(int(b.get("returncode") or 0) == 0 for b in builds)
    return {"ok": ok, "literals": literals, "protected": protected, "parts": parts, "builds": builds}


# --- A7 cost -----------------------------------------------------------------------------------------
def a7_timing(path: Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"source": str(path), **data}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="guards", description="night loop guards A3-A7")
    parser.add_argument("--db", required=True, help="the branch's pilot3 database (read-only)")
    parser.add_argument("--base", required=True, help="git ref the branch started from")
    parser.add_argument("--branch", required=True, help="git ref to check")
    parser.add_argument("--base-db", default="", help="the base build's database, to score only added rows")
    parser.add_argument("--timing", default="", help="json with pages read and build seconds (A7)")
    parser.add_argument("--parts", default="", help="comma list overriding the changed build parts")
    parser.add_argument("--a6", default="", choices=("", "ok", "fail"), help="the fast test suite's result")
    parser.add_argument("--limit", type=int, default=4000, help="A3 rows to check without --base-db")
    parser.add_argument("--workdir", default=str(WORK))
    parser.add_argument("--out", default="")
    started = time.time()
    args = parser.parse_args(argv)
    report: dict[str, Any] = {
        "db": str(args.db), "base": args.base, "branch": args.branch,
        "a3": a3_provenance(Path(args.db), Path(args.base_db) if args.base_db else None, args.limit),
        "a4": a4_counts(Path(args.db)),
        "a5": a5_build(Path(args.db), args.base, args.branch, Path(args.workdir),
                       parts=[p.strip() for p in args.parts.split(",") if p.strip()] or None),
        "a6": {"ok": None if not args.a6 else args.a6 == "ok"},
        "a7": a7_timing(Path(args.timing) if args.timing else None),
    }
    a3, a5 = report["a3"], report["a5"]
    report["ok"] = bool(a3["ok"] and a5["ok"] and (report["a6"]["ok"] is not False))
    report["elapsed_s"] = round(time.time() - started, 2)
    print(f"A3 provenance: {a3['passed']}/{a3['checked']} = {a3['rate']} ({a3['scope']},"
          f" {a3.get('page_missing', 0)} cited pages not in doc_page) -> {'pass' if a3['ok'] else 'FAIL'}")
    for example in a3["examples"]:
        print(f"  A3 miss {example['table']} {example['symbol']} p{example['page']}:"
              f" value_in_quote={example['value_in_quote']} quote_on_page={example['quote_on_page']}")
    print("A4 counts: " + "  ".join(f"{key} {value}" for key, value in report["a4"]["counts"].items()))
    print(f"A5 build: parts {a5['parts'] or '-'} literals {len(a5['literals'])}"
          f" protected {len(a5['protected'])} -> {'pass' if a5['ok'] else 'FAIL'}")
    for hit in a5["literals"][:10]:
        print(f"  A5 literal {hit['path']}:{hit['line']} {hit['kind']} {hit['token']}")
    for hit in a5["protected"][:10]:
        print(f"  A5 protected {hit['path']} ({hit['kind']})")
    for build in a5["builds"]:
        print(f"  A5 build {build['part']}: exit {build['returncode']}")
    if report["a7"]:
        print(f"A7 cost: {report['a7']}")
    print(f"guards {'pass' if report['ok'] else 'FAIL'} in {report['elapsed_s']} s")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
