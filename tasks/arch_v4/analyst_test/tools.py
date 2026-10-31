"""Read-only, point-in-time tools for the analyst-agent test.

The five tools the model can call are ``fact_query``, ``claim_search``,
``chunk_search``, ``list_atoms`` and ``calculator``.  The wrapper — not the model —
owns ``as_of``: every SQL statement adds ``known_at <= as_of`` and a tool argument
that names a later date is refused.  Every call and result is appended to a JSONL
log so the number check and the grader can replay it.
"""
from __future__ import annotations

import ast
import json
import math
import operator
import os
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path

MAX_CALLS = 12
DEFAULT_DATA_ROOT = Path(r"C:\RE\data")
DATA_ROOT = Path(os.environ.get("ANALYST_DATA_ROOT") or os.environ.get("REALITY_DATA_ROOT") or DEFAULT_DATA_ROOT)
FACT_DB = DATA_ROOT / "pilot" / "v4" / "fact_v4_pilot.db"
V4_DB = DATA_ROOT / "pilot" / "v4" / "v4.db"
CHUNKS_DB = DATA_ROOT / "pilot" / "pilot60" / "chunks_v3_pilot.db"

STOPWORDS = {
    "the", "and", "for", "with", "what", "was", "were", "does", "did", "say", "said",
    "from", "that", "this", "its", "his", "her", "how", "why", "when", "who", "which",
    "are", "has", "have", "had", "into", "over", "under", "about", "per", "now", "not",
    "but", "you", "your", "our", "their", "they", "will", "would", "should", "could",
}


class ToolError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    con = sqlite3.connect("file:///" + str(path).replace("\\", "/") + "?mode=ro&immutable=1",
                          uri=True)
    con.row_factory = sqlite3.Row
    return con


def _date10(value) -> str:
    return str(value or "").strip()[:10]


def _limit(value, default: int, cap: int) -> int:
    """The model sometimes sends ``5.0`` or ``"5"``; accept both, clamp to the cap."""
    try:
        return max(1, min(cap, int(float(value if value not in (None, "") else default))))
    except (TypeError, ValueError):
        return default


def _window(text: str, terms: list[str], width: int = 1500) -> str:
    """Densest query-term window inside a long chunk (the answer is often deep inside)."""
    body = re.sub(r"\s+", " ", text or "").strip()
    if len(body) <= width:
        return body
    low = body.lower()
    positions = []
    for term in terms[:12]:
        t = term.lower()
        if len(t) < 3:
            continue
        start = 0
        for _ in range(10):
            i = low.find(t, start)
            if i < 0:
                break
            positions.append(i)
            start = i + 1
    if not positions:
        return body[:width] + " …"
    best_lo, best_score = 0, -1
    for pos in positions:
        lo = max(0, min(pos - width // 3, len(body) - width))
        win = low[lo:lo + width]
        score = sum(1 for t in terms[:12] if len(t) >= 3 and t.lower() in win)
        if score > best_score:
            best_lo, best_score = lo, score
    return ("… " if best_lo else "") + body[best_lo:best_lo + width] + (
        " …" if best_lo + width < len(body) else "")


class ToolSession:
    """One question's tool budget, PIT ceiling and call log."""

    def __init__(self, question: dict, *, log_path: Path | None = None,
                 fact_db: Path = FACT_DB, v4_db: Path = V4_DB, chunks_db: Path = CHUNKS_DB):
        self.qid = question["qid"]
        self.mid = question["mid"]
        self.as_of = _date10(question["as_of"])
        self.entity_isin = question.get("entity_isin") or ""
        self.entity_symbol = (question.get("symbol") or "").strip()
        self.question = question.get("question") or ""
        self.log_path = Path(log_path) if log_path else None
        self.calls = 0
        self.fact = _connect(fact_db)
        self.v4 = _connect(v4_db)
        self.chunks = _connect(chunks_db)
        self._symbols = {r[1].upper(): r[0] for r in self.fact.execute(
            "select isin, symbol from pilot_universe where symbol is not null and symbol != ''")}
        self._isin_symbol = {r[0]: r[1] for r in self.fact.execute(
            "select isin, symbol from pilot_universe")}

    def close(self) -> None:
        for con in (self.fact, self.v4, self.chunks):
            con.close()

    # ---------------------------------------------------------------- PIT guard
    def _ceiling(self, value) -> str:
        """Refuse a requested date after the question's as_of; return the effective date."""
        if value in (None, ""):
            return self.as_of
        try:
            got = _date10(value)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", got):
                raise ToolError("bad_date", f"date {value!r} is not YYYY-MM-DD")
        except ToolError:
            raise
        if got > self.as_of:
            raise ToolError("as_of_refused",
                            f"requested {got} is after the question as_of {self.as_of}; "
                            "the wrapper refuses rows known later")
        return got

    def _resolve(self, value: str, atom: str | None = None) -> str:
        raw = str(value or "").strip()
        if not raw:
            return self.entity_isin
        upper = raw.upper()
        if upper in self._symbols:
            return self._symbols[upper]
        if raw in self._isin_symbol:
            return raw
        # Macro atoms use series ids, not ISINs; accept a raw entity id that exists.
        if atom and self.fact.execute(
                "select 1 from fact where entity_id=? and atom=? limit 1", (raw, atom)).fetchone():
            return raw
        raise ToolError("unknown_entity",
                        f"entity {raw!r} is not a pilot symbol/ISIN. Pilot symbols: "
                        + ", ".join(sorted(self._symbols)[:80]))

    # ---------------------------------------------------------------- dispatch
    SPECS = {
        "fact_query": {
            "description": "One atom's dated rows for one entity. Use list_atoms first to find the atom.",
            "args": {"atom": "str, e.g. fin.revenue / price.close / hold.pct",
                     "entity": "pilot symbol or ISIN (defaults to the question entity)",
                     "dims": "optional substring, e.g. basis=consolidated or holder_class=promoter",
                     "period_from": "optional YYYY-MM-DD", "period_to": "optional YYYY-MM-DD",
                     "as_of": "optional, never later than the question as_of",
                     "order": "asc or desc (default desc = newest first)",
                     "limit": "1-50, default 20"},
        },
        "claim_search": {
            "description": "Guidance/claims extracted from concalls, decks and ARs.",
            "args": {"entity": "pilot symbol or ISIN", "terms": "optional words",
                     "topic": "optional topic filter", "date_from": "optional YYYY-MM-DD",
                     "date_to": "optional YYYY-MM-DD", "as_of": "optional, never later",
                     "limit": "1-20, default 10"},
        },
        "chunk_search": {
            "description": "Full-text search over the pilot document chunks (concall/deck/AR/announcement).",
            "args": {"entity": "pilot symbol or ISIN", "query": "words to search",
                     "doc_types": "optional list: concall, deck, annual_report, results_notes, announcement",
                     "date_from": "optional YYYY-MM-DD", "date_to": "optional YYYY-MM-DD",
                     "as_of": "optional, never later", "limit": "1-10, default 6"},
        },
        "list_atoms": {
            "description": "The atom catalogue; with an entity, the atoms that entity actually has.",
            "args": {"entity": "optional pilot symbol or ISIN",
                     "as_of": "optional, never later"},
        },
        "calculator": {
            "description": "Deterministic arithmetic. Use it for every derived number.",
            "args": {"expression": "e.g. (389.15/242.80)**(1/3)-1"},
        },
    }

    def log_event(self, name: str, args: dict, result: dict) -> None:
        """Log a non-data event (the submit_answer call) in the same call log."""
        if not self.log_path:
            return
        entry = {"qid": self.qid, "mid": self.mid, "call": self.calls + 1, "tool": name,
                 "args": args, "ok": not bool((result or {}).get("error")),
                 "error": (result or {}).get("error"), "result": result, "secs": 0.0}
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def call(self, name: str, args: dict | None) -> dict:
        if self.calls >= MAX_CALLS:
            raise ToolError("call_budget", f"tool budget of {MAX_CALLS} calls is exhausted")
        args = args if isinstance(args, dict) else {}
        t0 = time.time()
        error = None
        try:
            fn = {
                "fact_query": self.fact_query,
                "claim_search": self.claim_search,
                "chunk_search": self.chunk_search,
                "list_atoms": self.list_atoms,
                "calculator": self.calculator,
            }.get(name)
            if fn is None:
                raise ToolError("unknown_tool", f"unknown tool {name!r}; use one of "
                                + ", ".join(self.SPECS))
            result = fn(args)
        except ToolError as exc:
            error = {"code": exc.code, "message": str(exc)}
            result = {"error": error}
        except Exception as exc:  # data/format problem is returned, never raised to the model
            error = {"code": type(exc).__name__, "message": str(exc)[:300]}
            result = {"error": error}
        self.calls += 1
        entry = {"qid": self.qid, "mid": self.mid, "call": self.calls, "tool": name,
                 "args": args, "ok": error is None, "error": error, "result": result,
                 "secs": round(time.time() - t0, 4)}
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if name != "list_atoms" and len(json.dumps(result, ensure_ascii=False)) > 20000:
            result = dict(result)
            result["note"] = (result.get("note") or "") + " [result truncated for the model]"
            result["rows"] = (result.get("rows") or [])[:12]
        return result

    # ---------------------------------------------------------------- tools
    def fact_query(self, args: dict) -> dict:
        atom = str(args.get("atom") or "").strip()
        if not atom:
            raise ToolError("bad_args", "fact_query needs an atom")
        ceiling = self._ceiling(args.get("as_of"))
        entity = self._resolve(args.get("entity") or self.entity_isin, atom)
        limit = _limit(args.get("limit"), 20, 50)
        where = ["entity_id=?", "atom=?", "substr(known_at,1,10)<=?"]
        params: list = [entity, atom, ceiling]
        dims = str(args.get("dims") or "").strip()
        if dims:
            where.append("dims like ?")
            params.append(f"%{dims}%")
        for key, op in (("period_from", ">="), ("period_to", "<=")):
            if args.get(key):
                where.append(f"period_end {op} ?")
                params.append(_date10(args[key]))
        sql = ("select entity_id, atom, dims, period_start, period_end, value, unit, "
               "known_at, source_ref from fact where " + " and ".join(where)
               + " order by period_end " + ("asc" if str(args.get("order")).lower() == "asc" else "desc")
               + ", dims limit ?")
        rows = [dict(r) for r in self.fact.execute(sql, params + [limit])]
        if not rows and not self.fact.execute(
                "select 1 from fact where atom=? limit 1", (atom,)).fetchone():
            raise ToolError("unknown_atom", f"no atom {atom!r} in the fact store; "
                            "call list_atoms to see the catalogue")
        return {"tool": "fact_query", "as_of": ceiling, "entity": entity, "atom": atom,
                "rows": rows, "n_returned": len(rows),
                "note": "all rows have known_at <= as_of; period_end is the fact date, "
                        "known_at is when it became public"}

    def claim_search(self, args: dict) -> dict:
        entity = self._resolve(args.get("entity") or self.entity_isin)
        ceiling = self._ceiling(args.get("as_of"))
        date_from = self._ceiling(args.get("date_from")) if args.get("date_from") else ""
        date_to = self._ceiling(args.get("date_to")) if args.get("date_to") else ceiling
        limit = _limit(args.get("limit"), 10, 20)
        where = ["entity_id=?", "substr(known_at,1,10)<=?", "substr(known_at,1,10)>=?"]
        params: list = [entity, date_to, date_from or "0000-00-00"]
        terms = args.get("terms") or ""
        if isinstance(terms, (list, tuple)):
            terms = " ".join(str(t) for t in terms)
        else:
            terms = str(terms).strip()
        if terms.lstrip().startswith("["):
            try:
                parsed = json.loads(terms)
                if isinstance(parsed, list):
                    terms = " ".join(str(t) for t in parsed)
            except json.JSONDecodeError:
                pass
        if terms:
            words = [w for w in re.findall(r"[A-Za-z0-9&.]+", terms) if len(w) >= 3][:8]
            if words:
                where.append("(" + " or ".join(
                    ["lower(topic) like ? or lower(quote) like ? or lower(list_name) like ?"
                     for _ in words]) + ")")
                for w in words:
                    like = f"%{w.lower()}%"
                    params.extend([like, like, like])
        if args.get("topic"):
            where.append("lower(topic) like ?")
            params.append(f"%{str(args['topic']).lower()}%")
        sql = ("select claim_id, entity_id, topic, direction, direction_raw, magnitude, unit, "
               "horizon, certainty, guidance_vs_fact, substr(quote,1,500) as quote, page_no, "
               "doctype, list_name, known_at from claim where " + " and ".join(where)
               + " order by known_at desc limit ?")
        rows = [dict(r) for r in self.v4.execute(sql, params + [limit])]
        return {"tool": "claim_search", "as_of": ceiling, "entity": entity,
                "rows": rows, "n_returned": len(rows),
                "note": "claims are extracted statements, not audited facts"}

    def chunk_search(self, args: dict) -> dict:
        entity = self._resolve(args.get("entity") or self.entity_isin)
        ceiling = self._ceiling(args.get("as_of"))
        query = str(args.get("query") or self.question).strip()
        if not query:
            raise ToolError("bad_args", "chunk_search needs a query")
        tokens = [t for t in re.findall(r"[A-Za-z0-9]+", query) if len(t) >= 3
                  and t.lower() not in STOPWORDS][:12]
        if not tokens:
            raise ToolError("bad_args", "chunk_search query has no usable words")
        match = " OR ".join(f'"{t}"' for t in tokens)
        limit = _limit(args.get("limit"), 6, 10)
        where = ["chunk_fts match ?", "c.isin=?", "substr(c.known_at,1,10)<=?",
                 "c.quality_grade in ('A','B')", "c.char_len between 80 and 6000"]
        params: list = [match, entity, ceiling]
        types = args.get("doc_types")
        if types:
            if isinstance(types, str):
                s = types.strip()
                if s.startswith("["):
                    try:
                        types = json.loads(s)
                    except json.JSONDecodeError:
                        types = [s]
                else:
                    types = [s]
            if not isinstance(types, (list, tuple)):
                types = [types]
            types = [str(t).strip() for t in types if str(t).strip()]
            if types:
                where.append("c.doc_type in (" + ",".join("?" for _ in types) + ")")
                params.extend(types)
        if args.get("date_from"):
            where.append("substr(c.known_at,1,10)>=?")
            params.append(self._ceiling(args["date_from"]))
        if args.get("date_to"):
            where.append("substr(c.known_at,1,10)<=?")
            params.append(self._ceiling(args["date_to"]))
        sql = ("select c.chunk_id, c.doc_id, c.doc_type, c.header, c.body, c.section, "
               "c.speaker, c.known_at, c.event_date, c.fiscal_period, c.page_from, "
               "c.page_to, c.char_len, d.title, bm25(chunk_fts, 0.3, 1.0) as score "
               "from chunk_fts join chunk c on c.chunk_id=chunk_fts.rowid "
               "join doc d on d.doc_id=c.doc_id where " + " and ".join(where)
               + " order by score limit ?")
        rows = []
        for r in self.chunks.execute(sql, params + [limit]):
            d = dict(r)
            d["body_excerpt"] = _window(d.pop("body"), tokens)
            rows.append(d)
        return {"tool": "chunk_search", "as_of": ceiling, "entity": entity,
                "rows": rows, "n_returned": len(rows), "query_terms": tokens,
                "note": "excerpt is a window of the chunk; known_at <= as_of"}

    def list_atoms(self, args: dict) -> dict:
        ceiling = self._ceiling(args.get("as_of"))
        entity = None
        if args.get("entity"):
            entity = self._resolve(args["entity"])
        if not entity:
            rows = [dict(r) for r in self.fact.execute(
                "select atom_id, status, rows, entities, isin_coverage_pct, store "
                "from atom_status order by atom_id")]
            return {"tool": "list_atoms", "as_of": ceiling, "rows": rows,
                    "n_returned": len(rows),
                    "note": "atom_status counts over the whole pilot store"}
        rows = [dict(r) for r in self.fact.execute(
            "select atom, count(*) as rows, min(period_end) as first_period, "
            "max(period_end) as last_period, group_concat(distinct unit) as units "
            "from fact where entity_id=? and substr(known_at,1,10)<=? "
            "group by atom order by atom", (entity, ceiling))]
        for r in rows:
            sample = self.fact.execute(
                "select dims from fact where entity_id=? and atom=? "
                "and substr(known_at,1,10)<=? group by dims limit 2",
                (entity, r["atom"], ceiling)).fetchall()
            r["dims_sample"] = [s[0] for s in sample]
        return {"tool": "list_atoms", "as_of": ceiling, "entity": entity,
                "rows": rows, "n_returned": len(rows),
                "note": "all atoms this entity has at or before as_of; use fact_query with one atom"}

    def calculator(self, args: dict) -> dict:
        expr = str(args.get("expression") or "").strip()
        if not expr:
            raise ToolError("bad_args", "calculator needs an expression")
        value = safe_eval(expr)
        return {"tool": "calculator", "expression": expr, "value": value}


_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"round": round, "min": min, "max": max, "abs": abs, "sqrt": math.sqrt}


def safe_eval(expr: str):
    """Arithmetic only: numbers, + - * / ** %, parentheses and five named functions."""
    if len(expr) > 200:
        raise ToolError("bad_expression", "expression too long")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ToolError("bad_expression", f"cannot parse: {exc}") from exc

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ToolError("bad_expression", f"unsupported expression element: {type(node).__name__}")

    try:
        out = ev(tree)
    except ZeroDivisionError as exc:
        raise ToolError("bad_expression", "division by zero") from exc
    if isinstance(out, complex):
        raise ToolError("bad_expression", "complex result")
    return out


def collect_numbers(payload) -> set[str]:
    """Every numeric token present anywhere in a tool result (values, dates, quotes)."""
    text = json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload
    return {m.group(0).replace(",", "") for m in re.finditer(r"-?\d+(?:\.\d+)?", text)}
