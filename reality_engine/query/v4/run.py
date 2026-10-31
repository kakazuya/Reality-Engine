"""The v4 run: question -> decompose -> execute per part -> render (§C.2, §D.1, §D.4).

One question text and an ``as_of`` in; one typed Ask, exactly one Result per part and
the rendered answer out.  This is the controller the three pieces were missing: the
decomposer reads text only, the executor reads a fact view, the renderer reads results
— this module is the only place that knows all three.

Stores are the v4 pilot builds, read-only (``mode=ro&immutable=1``):

    fact_v4_pilot.db   fact (WP2a), membership
    v4.db              claim (WP2b), own_estimate / own_estimate_band, edge

The executor takes one connection; SQLite's ATTACH with a URI filename depends on a
compile-time URI switch, so :class:`Stores` routes each statement to the connection
whose build owns the table.  Entity resolution reads the 60-name identity map
(``tasks/pilot60/UNIVERSE.csv`` plus the held ``master_companies`` row per pilot ISIN)
and nothing else.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import execute, render
#: ``reality_engine.query.v4.decompose`` is shadowed by the function of the same name in
#: the package ``__init__``, so import the names, never the module attribute.
from .decompose import decompose_case, load_registry

REPO = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("REALITY_DATA_ROOT") or (REPO / "reality_engine" / "data"))
V4_ROOT = Path(os.environ.get("REALITY_V4_PILOT") or (DATA / "pilot" / "v4"))
UNIVERSE_CSV = REPO / "tasks" / "pilot60" / "UNIVERSE.csv"

#: A blank ``as_of`` defaults to this declared snapshot date and the answer says so.
#: It is the store's latest complete market session: all 60 names carry a close on
#: 2026-10-19; later dates hold one name only.  Shivam's review changes this line.
DEFAULT_AS_OF = "2026-10-19"

#: tables that live in v4.db (WP2b), not in the WP2a fact store.
V4_TABLES = ("claim", "own_estimate", "own_estimate_band", "own_estimate_band_prev", "edge",
             "hypothesis", "attention", "reaction_lag")
OI_ATOM = "macro.oi"
_V4_TABLE = re.compile(r"\b(?:from|join)\s+(?:%s)\b" % "|".join(V4_TABLES), re.I)
#: one-value operators read one entity; these read a set.
CROSS_ENTITY = {"rank", "screen", "compare", "join_entity_set", "count", "exists",
                "list_distinct", "aggregate", "walk"}
#: legal-form words a question drops from a company name ("Grasim Industries Limited").
_LEGAL = {"limited", "ltd", "private", "pvt", "company", "co", "corporation", "corp",
          "the", "and"}
_WS = re.compile(r"\s+")


def _uri(path: Path) -> str:
    return f"file:{Path(path).as_posix()}?mode=ro&immutable=1"


class Stores:
    """The executor's one connection, routed to the read-only build that owns each table."""

    def __init__(self, root: Path | None = None):
        root = Path(root or V4_ROOT)
        self.fact = sqlite3.connect(_uri(root / "fact_v4_pilot.db"), uri=True)
        self.v4 = sqlite3.connect(_uri(root / "v4.db"), uri=True)
        #: macro.oi lives in its own side file (fact_oi.sql), same table shape as fact.
        oi_path = root / "fact_v4_pilot_oi.db"
        self.oi = sqlite3.connect(_uri(oi_path), uri=True) if oi_path.is_file() else None
        self.closed = False

    def execute(self, sql: str, params: Any = ()):
        params = tuple(params)
        if _V4_TABLE.search(sql):
            target = self.v4
        elif self.oi is not None and (OI_ATOM in sql or OI_ATOM in params):
            target = self.oi
        else:
            target = self.fact
        return target.execute(sql, params)

    def close(self) -> None:
        if not self.closed:
            self.fact.close()
            self.v4.close()
            if self.oi is not None:
                self.oi.close()
            self.closed = True

    def __enter__(self) -> "Stores":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# entity resolution: the text entity -> ISIN, at the run's as_of (§C.2)
# ---------------------------------------------------------------------------
def _clean(text: str) -> str:
    return _WS.sub(" ", re.sub(r"[^A-Za-z0-9& ]+", " ", str(text or ""))).strip()


def _base_name(name: str) -> str:
    """A company name without its legal form: "Grasim Industries Limited" -> "Grasim"."""
    words = [word for word in _clean(name).split() if word.lower() not in _LEGAL]
    return " ".join(words) if len(words) >= 2 else ""


def universe(path: Path | None = None) -> dict[str, str]:
    """``SYMBOL -> ISIN`` from the pilot universe file (60 rows, 9 without a symbol)."""
    out: dict[str, str] = {}
    target = Path(path or UNIVERSE_CSV)
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    header = [cell.strip() for cell in lines[0].split(",")] if lines else []
    if "isin" not in header or "symbol" not in header:
        return out
    i_isin, i_symbol = header.index("isin"), header.index("symbol")
    for line in lines[1:]:
        cells = [cell.strip() for cell in line.split(",")]
        if len(cells) > max(i_isin, i_symbol) and cells[i_symbol]:
            out[cells[i_symbol].upper()] = cells[i_isin]
    return out


def universe_isins(path: Path | None = None) -> set[str]:
    """Every pilot ISIN, including the names that carry no NSE symbol."""
    target = Path(path or UNIVERSE_CSV)
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    header = [cell.strip() for cell in lines[0].split(",")] if lines else []
    if "isin" not in header:
        return set()
    i_isin = header.index("isin")
    out = set()
    for line in lines[1:]:
        cells = [cell.strip() for cell in line.split(",")]
        if len(cells) > i_isin and cells[i_isin]:
            out.add(cells[i_isin])
    return out


def identities(symbols: Mapping[str, str] | None = None,
               path: Path | None = None) -> dict[str, str]:
    """``name -> ISIN`` for the pilot names: the held master row of every pilot ISIN.

    ``master_companies`` is the identity map the instance questions were renamed from
    (``instantiate.py``), so a question's company name is a key here by construction.
    It is metadata, not a fact store; a failure degrades to the symbol map only.
    """
    out: dict[str, str] = {}
    target = Path(path) if path else (DATA / "equity_intelligence.db")
    if not target.exists():
        return out
    try:
        from reality_engine.db.readonly import connect_ro

        con = connect_ro(target, timeout_s=60)
        pilot = sorted(set((symbols or {}).values()) | universe_isins())
        marks = ",".join("?" for _ in pilot)
        rows = con.execute(
            "SELECT isin, nse_symbol, bse_code, company_name FROM master_companies "
            + (f"WHERE isin IN ({marks})" if marks else ""),
            tuple(pilot)).fetchall()
        con.close()
    except Exception:  # noqa: BLE001 - a missing master only costs name resolution
        return out
    for isin, nse_symbol, bse_code, name in rows:
        for key in (name, bse_code, nse_symbol):
            if key:
                out[_clean(str(key))] = str(isin)
    return out


_LEGAL_WORDS = _LEGAL


class Resolver:
    """Symbol / name / ISIN -> one pilot ISIN, or ``(None, why)``.

    ponytail: the pilot identity map is a static snapshot (current ``master_companies``
    names), not ``symbol_isin_history``.  The 60 names do not rename inside the pilot
    window; add the PIT symbol window when the run leaves the pilot.
    """

    def __init__(self, symbols: Mapping[str, str] | None = None,
                 names: Mapping[str, str] | None = None,
                 isins: Iterable[str] | None = None):
        self.symbols = {str(key).upper(): value for key, value in (symbols or {}).items()}
        self.names: dict[str, str] = {}
        for key, isin in (names or {}).items():
            cleaned = _clean(key)
            if cleaned.isdigit():
                self.symbols.setdefault(cleaned, isin)      # a BSE code names one ISIN
                continue
            if len(cleaned.split()) >= 2:
                self.names[cleaned.lower()] = isin
            base = _base_name(key)
            if base:
                self.names.setdefault(base.lower(), isin)
        self.isins = set(isins or ()) | set(self.symbols.values())
        self._pattern = None
        if self.names:
            ordered = sorted(self.names, key=len, reverse=True)
            self._pattern = re.compile(
                r"(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])"
                % "|".join(re.escape(name) for name in ordered), re.I)

    def by_text(self, text: str) -> list[str]:
        """Every pilot ISIN the text names, longest name first, in text order."""
        hits: list[tuple[int, str]] = []
        if self._pattern is not None:
            for match in self._pattern.finditer(text or ""):
                isin = self.names.get(_clean(match.group(0)).lower())
                if isin:
                    hits.append((match.start(), isin))
        found: list[str] = []
        for _, isin in sorted(hits):
            if isin not in found:
                found.append(isin)
        return found

    def from_case(self, case: Mapping[str, Any]) -> tuple[str, list[str], str] | None:
        """The case record's own entity, when it names one of the pilot ISINs.

        Every instance row carries ``entities`` — the company the question was
        instantiated for.  A handful of instance texts still name the pre-substitution
        company, so the record is the authority and the text is the fallback.
        """
        for entity in case.get("entities") or []:
            if not isinstance(entity, dict):
                continue
            isin = str(entity.get("isin") or "").strip().upper()
            if isin in self.isins:
                return isin, [isin], "case-isin"
            key = re.sub(r"[^A-Z0-9&]", "", str(entity.get("symbol") or "").upper())
            if key in self.symbols:
                return self.symbols[key], [self.symbols[key]], "case-symbol"
        return None

    def resolve(self, ask: Any) -> tuple[str | None, list[str], str]:
        entity = ask.entities[0] if getattr(ask, "entities", None) else None
        if entity is not None and entity.isin:
            return entity.isin, [entity.isin], "isin"
        text = (getattr(entity, "symbol", None) or "").strip() if entity else ""
        if text:
            key = re.sub(r"[^A-Z0-9&]", "", text.upper())
            if key in self.symbols:
                return self.symbols[key], [self.symbols[key]], "symbol"
            if len(key) >= 4:
                stems = [symbol for symbol in self.symbols if symbol.startswith(key)]
                if len(stems) == 1:
                    isin = self.symbols[stems[0]]
                    return isin, [isin], "symbol-prefix"
        found = self.by_text(getattr(ask, "question", "") or "")
        if found:
            return found[0], found, "name"
        if text:
            return None, [], (f"{text!r} is not one of the {len(self.symbols)} pilot "
                              f"identities (symbol / BSE code / name)")
        return None, [], (f"no pilot company named ({getattr(entity, 'how', 'no entity')})")


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, Any] | None = None


def execute_registry() -> dict[str, Any]:
    """The executor's registry dict, read once per process (the JSON is ~450 KB)."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = execute.load_registry()
    return _REGISTRY


def _looks_like_company(entity: Any) -> bool:
    """True when the decomposer's text entity is a company name, not a misread word.

    ``_entity`` falls back to "a token before a colon" or a capitalised span, so a
    question with no company can emit "was the" / "which" as a "symbol".  A company
    token starts upper-case; anything else is a market-wide ask, not an unresolved one.
    """
    if entity is None:
        return False
    if getattr(entity, "isin", None):
        return True
    if str(getattr(entity, "how", "") or "").startswith("theme stem"):
        return False
    symbol = str(getattr(entity, "symbol", None) or "").strip()
    return bool(symbol) and symbol[0].isupper()


def _unresolved(part: Any, index: int, why: str, as_of: str) -> "execute.Result":
    """A typed NOT IN DATA for a part whose named entity could not be resolved.

    The controller resolved the identity (§C.2 defers it here); when that fails, an
    answer from *some* entity's rows would be a silent wrong company, so the part says
    so instead.
    """
    return execute.Result(
        part_index=index, atom=part.atom, formula=part.formula, dims=dict(part.dims),
        operator=part.operator, shape=part.shape, answer_type="not_in_data",
        nid_reason=f"entity not resolved: {why}",
        tried=[{"store": "identity", "query": why, "rows_after_pit": 0, "at": as_of}],
        to_close="resolve the named company against the 60-name pilot identity map "
                 "(ISIN / symbol / held master name) and re-run")


def run_case(case: Mapping[str, Any], stores: Stores | None = None,
             resolver: Resolver | None = None, registry: Any = None,
             decon: Any = None) -> dict[str, Any]:
    """One master-bank case -> the typed Ask, one Result per part, and the answer text."""
    started = time.perf_counter()
    ask = decompose_case(dict(case), decon or load_registry())
    assumed = ""
    if not str(ask.as_of or "").strip():
        ask.as_of = DEFAULT_AS_OF
        assumed = f"as_of was blank; assumed the declared snapshot date {DEFAULT_AS_OF}"
    resolver = resolver or Resolver(universe(), identities(), universe_isins())
    by_case = resolver.from_case(case)
    isin, found, how = by_case if by_case else resolver.resolve(ask)
    named = bool(ask.entities) and _looks_like_company(ask.entities[0])
    if isin is None:
        # The case record names the company even when the question text does not
        # ("P/B now vs stored"): when that company is outside the pilot, the parts
        # would otherwise read whichever entity's rows sorted last.
        stated = next((item for item in (case.get("entities") or [])
                       if isinstance(item, Mapping)
                       and (item.get("isin") or item.get("symbol"))), None)
        if stated is not None:
            named = True
            how = (f"the case names {stated.get('symbol') or stated.get('isin')}, "
                   f"not one of the {len(resolver.isins)} pilot ISINs")
    windows = [window.to_dict() for window in ask.windows]
    results = []
    if named and isin is None:
        results = [_unresolved(part, index, how, ask.as_of)
                   for index, part in enumerate(ask.parts)]
    else:
        for index, part in enumerate(ask.parts):
            cross = part.operator in CROSS_ENTITY
            results.append(execute.execute(
                part, ask.as_of, stores, windows=windows,
                entity=None if cross else isin, entities=found if cross else None,
                registry=registry if registry is not None else execute_registry(),
                part_index=index))
    text = render.render_run(results, question=ask.question, as_of=ask.as_of,
                             assumption=assumed or None)
    row = {
        "mid": str(case.get("mid") or ""),
        "question": ask.question,
        "as_of": ask.as_of,
        "assumed_as_of": assumed or None,
        "ask": ask.to_dict(),
        "entity": isin,
        "entity_how": how,
        "results": [result.to_dict() for result in results],
        "answer": text,
        "parts": len(results),
        "case_answered": render.answer_contract(results)["case_answered"],
        "seconds": round(time.perf_counter() - started, 3),
        "status": ask.status,
        "residues": ask.residues,
        "nid_reasons": ask.nid_reasons,
    }
    for key in ("bucket", "sector", "kind", "family", "entity_level", "parent_mid",
                "source_bank", "regression", "template", "period"):
        if case.get(key) is not None:
            row[key] = case.get(key)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--question", help="one question text")
    parser.add_argument("--mid", help="one master-bank / instance mid")
    parser.add_argument("--as-of", default="2026-10-31")
    parser.add_argument("--json", action="store_true", help="print the whole row")
    args = parser.parse_args(argv)

    case: dict[str, Any] = {"question": args.question or "", "as_of": args.as_of}
    if args.mid:
        for name in (REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl",
                     REPO / "tasks" / "pilot60" / "INSTANCES.jsonl"):
            if not name.exists():
                continue
            for line in name.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if str(row.get("mid")) == args.mid:
                        case = row
                        break
            if case.get("mid"):
                break
    if not case.get("question"):
        parser.error("pass --question or a --mid present in the bank")
    with Stores() as stores:
        row = run_case(case, stores)
    print(json.dumps(row, ensure_ascii=False, indent=1) if args.json else row["answer"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
