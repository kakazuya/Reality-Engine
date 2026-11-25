"""The seeded tool run (T-205 round 13, arm S): one agy model answers a question with the pack as a starting point.

The round-12 pack path is a fixed evidence set: a question the pack never gathered for is lost, whatever the model
knows (14 of 24 round-12 losses were exactly that). This arm keeps the pack -- the evidence the script already
gathered -- and gives the model the pilot3_* tools, so it can check the pack and follow up where the pack is empty.
It answers the same 64 frozen questions, with the same as_of.

Per question: ONE agy run (``gemini-4-hydrogen-high`` by default) whose prompt is the T-199 answer rules rewritten
for the MCP tools, the question and as_of, and the pack's reading copy labelled "evidence already gathered: start
from it, check it, fill what is missing with tools". The reply is one JSON object (answer, sources, confidence);
the tools actually called come from the agy event log, never from the model's own claim.

Output, one line appended per finished question so a stop keeps the work:

* ``answers.jsonl`` -- the ds_a shape: qid, question, as_of, answer, tools, sources, sql_reason, confidence
  (+ the round's own fields: tool_calls, parsed, model, seconds).
* ``calls.jsonl`` -- one line per agy run: qid, model, ok, seconds, attempts, tool calls by tool, tokens, error, log.

Usage:
    python -m reality_engine.answer.seeded_run --set bluestar --packs D:/RealityEngine/bluestar/pack_r11 \
        --out .tmp/r13_seeded [--questions <file>] [--limit N] [--model gemini-4-hydrogen-high]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from reality_engine.answer import agy_call

ARM = "S"
DEFAULT_MODEL = "gemini-4-hydrogen-high"
SYMBOLS = {"bluestar": "BLUESTARCO", "aurobindo": "AUROPHARMA"}

RULES = """You answer ONE investor question about an Indian listed company from the reality-data MCP store, exactly \
as a careful analyst would. The store is the only evidence: never use outside knowledge, the web, or any file under \
questions/, truth/, truth2/, report/, answers*/ or key_private/.

Tools (MCP server reality-data). ALWAYS pass symbol=<symbol> and as_of=<the question's as_of>: rows known after it
must not be used, and a document filed after it must never be cited.
- pilot3_fact: ONE answer-ready number (value, unit, period, basis, source page) -- call it FIRST for any single figure.
- pilot3_fin: reported/derived financial lines (revenue, PAT, EBITDA, capex, net debt, EPS) by measure, period, basis.
- pilot3_ratio: margins, ROE/ROCE, growth, PE/PB, days, market cap.
- pilot3_kpi: company-stated KPIs (order book, segment revenue, NIM, shipments, ...).
- pilot3_guidance: forward targets and their revisions, with the quote and call date.
- pilot3_statements: what management said in a call (topic / terms / period / role). For a question about ONE call
  ("In the 2026-05-27 call, what did management say about X?"), pass that call's date as date_from AND date_to
  (both YYYY-MM-DD): only that call's statements are then served, best match first.
- pilot3_topic: everything held on one theme across every call and document -- use it FIRST for list and
  "what did they say about X" questions, and raise limit when the reply says items were cut.
- pilot3_cells: every figure read from a table or chart page (results statements, decks, segment tables).
- pilot3_docs: the document list; pilot3_search: full-text page search; pilot3_semantic: pages closest in meaning
  (use semantic when the question words differ from the document words, then read the pages it returns).
- pilot3_holding: shareholding pattern, pledge, share count.
- pilot3_tech: price reaction to a filing, gaps, RSI, moving averages, volume spikes, 52-week range.
- pilot3_sql: a bounded read-only SELECT, ONLY when no typed tool answers (say why in the reply).
- pilot3_calc: arithmetic you did not copy from a row (a growth, margin, sum, market cap); pass the inputs.

Rules:
1. Answer EVERY part the question asks (each figure, each period, each segment, the reason). Re-read the question
   before writing and check each part is covered.
2. Try at least two routes, plus pilot3_search or pilot3_semantic, before saying a figure is not held.
3. Prefer the company's printed page (results statement, deck, transcript) over any derived row, and say when a
   figure is derived.
4. Compute what the filings do not state (margins, shares, growth) from stored inputs and show the inputs.
   Never hand-sum a quarter table.
5. Every figure needs its period, unit and basis (consolidated or standalone). Every management claim needs its
   call date. A percentage-point change is "pp", never "%".
6. only if the store truly lacks it: say "data not found", name what you searched, and give the nearest held point
   clearly labelled as nearest, not as the answer.
7. Do not cite a document known after the question's as_of.

EVIDENCE ALREADY GATHERED: the reading copy at the end of this prompt was gathered earlier for this question by a
script. Start from it, check it against the tools, and fill what it missed with lookups of your own. It is NOT
authoritative: a stale, wrong or missing item must be corrected or replaced from the store.

Reply with ONE JSON object and NOTHING else:
{"answer": "<1-5 sentences with figures, units, periods and basis; 'data not found' + what you searched when it is>",
 "sources": [{"doc_key": "<key or store row>", "doc_type": "<results|deck|transcript|annual_report|announcement|"
             "shareholding_xbrl|price|derived_ratio|store_row>", "page": <number or null>, "known_at": "<date>"}],
 "confidence": "high|medium|low"}
"""


def build_prompt(question: str, as_of: str, symbol: str, reading: str) -> str:
    """The one prompt: rules, question, as_of, then the pack's reading copy as the starting evidence."""
    body = reading.strip()
    if not body:
        body = "(the pack is empty for this question: gather the evidence with the tools)"
    return (f"{RULES}\n\nQUESTION (asked as of {as_of}):\n{question}\n\nsymbol: {symbol}\n\n"
            f"EVIDENCE ALREADY GATHERED (reading copy, {len(reading)} chars):\n{body}\n\n"
            "Answer that question now: one JSON object and nothing else.")


def parse_answer(text: str) -> dict:
    """The reply's JSON object, or the whole text as the answer (a model that ignored the protocol is still recorded)."""
    obj = agy_call.last_json(text)
    if isinstance(obj, dict) and str(obj.get("answer") or "").strip():
        sources = obj.get("sources")
        return {"answer": str(obj["answer"]).strip(),
                "sources": [s for s in sources if isinstance(s, dict)] if isinstance(sources, list) else [],
                "confidence": str(obj.get("confidence") or "").strip().lower(), "parsed": True}
    return {"answer": (text or "").strip(), "sources": [], "confidence": "", "parsed": False}


def _tool_names(reply: dict) -> list[str]:
    """The pilot3 tools the event log shows, in the ds_a spelling (``fact``, ``cells``, ``sql``)."""
    return sorted({t[len("pilot3_"):] if t.startswith("pilot3_") else t
                   for t in (reply.get("tools") or {}) if t.startswith("pilot3_") or t in agy_call.DATA_TOOLS})


def _existing(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("qid"):
                    rows[row["qid"]] = row
    return rows


def _append(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def run_set(questions_path: str | Path, packs: str | Path, out_dir: str | Path, *, model: str = DEFAULT_MODEL,
            symbol: str = "", limit: int = 0, workspace: str | Path = ".", timeout: int = 900,
            run=agy_call.run_agy) -> dict:
    """Answer every question once with the seeded tools; resumable on ``answers.jsonl``, one line per finish."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    answers_path, calls_path = out / "answers.jsonl", out / "calls.jsonl"
    done = _existing(answers_path)
    qs = json.loads(Path(questions_path).read_text(encoding="utf-8"))
    if limit:
        qs = qs[:limit]
    summary = {"arm": ARM, "model": model, "questions": len(qs), "answered": 0, "skipped": 0, "failed": 0,
               "unparsed": 0, "tool_calls": 0, "with_tools": 0, "seconds": 0.0, "packs": str(packs)}
    for q in qs:
        qid, question, as_of = q["qid"], q["question"], q["as_of"]
        sym = q.get("symbol") or symbol
        if qid in done:
            summary["skipped"] += 1
            summary["answered"] += 1
            continue
        reading_path = Path(packs) / f"pack_{qid}.txt"
        reading = reading_path.read_text(encoding="utf-8") if reading_path.is_file() else ""
        prompt = build_prompt(question, as_of, sym, reading)
        reply = run(prompt, model, cwd=workspace, timeout=timeout, log_path=out / "logs" / f"{qid}.jsonl")
        parsed = parse_answer(reply.get("text") or "")
        tools = _tool_names(reply)
        tools_full = {t: n for t, n in (reply.get("tools") or {}).items() if t.startswith("pilot3_") or t in agy_call.DATA_TOOLS}
        row = {"qid": qid, "question": question, "as_of": as_of, "answer": parsed["answer"],
               "tools": tools, "sources": parsed["sources"], "sql_reason": "",
               "confidence": parsed["confidence"], "tool_calls": reply.get("tool_calls", 0),
               "tools_by_name": tools_full, "parsed": parsed["parsed"], "model": model,
               "seconds": reply.get("seconds", 0), "ok": bool(reply.get("ok")),
               "error": reply.get("error", "")}
        if "sql" in tools:
            row["sql_reason"] = "pilot3_sql used: no typed tool answered"
        _append(answers_path, row)
        _append(calls_path, {"qid": qid, "model": model, "ok": row["ok"], "seconds": row["seconds"],
                             "attempts": reply.get("attempts"), "tool_calls": row["tool_calls"],
                             "tool_calls_by_tool": reply.get("tool_calls_by_tool") or {},
                             "tokens": reply.get("tokens") or {}, "status": reply.get("status"),
                             "error": row["error"], "log": reply.get("log", ""),
                             "prompt_chars": len(prompt)})
        summary["answered"] += 1
        summary["failed"] += 0 if row["ok"] else 1
        summary["unparsed"] += 0 if parsed["parsed"] else 1
        summary["tool_calls"] += int(row["tool_calls"] or 0)
        summary["with_tools"] += 1 if tools_full else 0
        summary["seconds"] = round(summary["seconds"] + float(row["seconds"] or 0), 2)
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m reality_engine.answer.seeded_run")
    ap.add_argument("--set", choices=sorted(SYMBOLS), required=True)
    ap.add_argument("--packs", required=True, help="the pack dir whose reading copies seed each question")
    ap.add_argument("--out", required=True)
    ap.add_argument("--questions", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--workspace", default=".")
    args = ap.parse_args(argv)
    questions = args.questions or f"D:/RealityEngine/{args.set}/answers/questions_in.json"
    summary = run_set(questions, args.packs, args.out, model=agy_call.model_id(args.model),
                      symbol=SYMBOLS.get(args.set, ""), limit=args.limit, workspace=args.workspace,
                      timeout=args.timeout)
    print(json.dumps(summary, indent=1))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

