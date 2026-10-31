"""The analyst-agent loop: beam-free calls typed, point-in-time tools until it answers.

Native OpenAI-style tool calling is used (the free tier emits reliable ``tool_calls``
where a JSON-text protocol often returned reasoning only).  The wrapper owns the tool
budget and ``as_of``; the model never sees a row known after the question date.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import beam
from .number_check import check_answer
from .tools import MAX_CALLS, ToolError, ToolSession

SYSTEM = """You are a careful equity analyst answering one question about an Indian listed company.
You may use ONLY the tool results in this conversation. Never use outside knowledge.

Rules:
- The read-only tools are typed; call them directly. Start with list_atoms (with the
  company) when you do not know what the store holds; the fact store is the first place
  to look for a number.
- Never repeat a tool call with the same arguments; every call must add new information.
- Every number in the final answer must appear in a tool result or in a calculator result.
  Compute every derived number (growth, CAGR, ratio, difference) with the calculator tool
  and use its returned value. Do not do arithmetic in your head.
- as_of is fixed. Never ask for data after it; the wrapper refuses rows known later.
- Check the atom name and dims before using a series: ``price.close`` is the raw close.
  If the question asks for a split/dividend-adjusted series or total return and the store
  has no adjusted atom, say that exact measure is not in data; never call a raw series adjusted.
- Answer every part of the question with the exact measure asked. A near measure is wrong.
- If the held data does not answer a part, put the exact typed phrase "not in data" at the
  start of "missing" and name what is missing. That is a valid answer, not a failure.
- If the question's premise is contradicted by the data, say so in "missing" and do not invent.
- When you are done, call submit_answer exactly once with answer, working and missing.
- Keep "working" short: the tool values that support the answer.
- You have at most 12 data-tool calls."""

SUBMIT = {
    "type": "function",
    "function": {
        "name": "submit_answer",
        "description": "Submit the final answer. Call this exactly once when you are done.",
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "the answer to the question"},
                "working": {"type": "string",
                            "description": "short bullets: which tool values were used"},
                "missing": {"type": "string",
                            "description": "part not answerable; start with 'not in data' if so"},
            },
            "required": ["answer", "working", "missing"],
        },
    },
}


def native_tools() -> list[dict]:
    out = []
    for name, spec in ToolSession.SPECS.items():
        props = {}
        for k, v in spec["args"].items():
            typ = ["string", "integer"] if k == "limit" else "string"
            props[k] = {"type": typ, "description": v}
        out.append({"type": "function", "function": {
            "name": name, "description": spec["description"],
            "parameters": {"type": "object", "properties": props,
                           "additionalProperties": False}}})
    out.append(SUBMIT)
    return out


TOOLS = native_tools()


def question_prompt(q: dict) -> str:
    label = q.get("name") or q.get("symbol") or q["entity_isin"]
    return (f"QUESTION ({q['qid']} / {q['mid']}): {q['question']}\n\n"
            f"COMPANY: {label} (symbol {q.get('symbol') or '-'}, ISIN {q['entity_isin']})\n"
            f"AS OF: {q['as_of']}\n"
            f"PERIOD IN QUESTION: {q.get('period') or '-'}\n"
            f"CATEGORY: {q.get('category')}\n\n"
            f"Use the tools now; call submit_answer when you are done.")


def _summary(result: dict) -> str:
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= 10000:
        return text
    return text[:10000] + " … [truncated]"


def _tool_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        obj = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def run_question(q: dict, *, transcript_path: Path | None = None,
                 tool_log_path: Path | None = None, beam_call=None) -> dict:
    """Run one question to a final answer or a recorded error."""
    call = beam_call or beam.call_messages
    t0 = time.time()
    tools = ToolSession(q, log_path=tool_log_path)
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": question_prompt(q)}]
    transcript = []
    payloads: list[dict] = []
    calc_values: list = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    beam_calls = 0
    nags = 0
    status = "no_final"
    error = None
    final = {"answer": "", "working": "", "missing": ""}
    try:
        for turn in range(MAX_CALLS + 8):
            out = call(messages, tools=TOOLS)
            beam_calls += 1
            for key in usage:
                usage[key] += int((out.get("usage") or {}).get(key) or 0)
            content = (out.get("content") or "").strip()
            calls = out.get("tool_calls") or []
            assistant = {"role": "assistant", "content": content}
            if calls:
                assistant["tool_calls"] = calls
            messages.append(assistant)
            transcript.append({"turn": turn, "role": "assistant", "content": content,
                               "tool_calls": calls, "reasoning_chars": out.get("reasoning_chars"),
                               "secs": out["secs"], "usage": out.get("usage")})
            if not calls:
                nags += 1
                if nags > 3:
                    status = "no_tool_call"
                    error = "model returned no tool call four times"
                    break
                messages.append({"role": "user", "content":
                                 "Use a tool, or call submit_answer with your final answer now."})
                continue

            submitted = False
            for tc in calls:
                fn = tc.get("function") or {}
                name = str(fn.get("name") or "").strip()
                args = _tool_args(fn.get("arguments"))
                if name == "submit_answer":
                    final = {"answer": str(args.get("answer") or "").strip(),
                             "working": str(args.get("working") or "").strip(),
                             "missing": str(args.get("missing") or "").strip()}
                    status = "final"
                    submitted = True
                    if tool_log_path:
                        tools.log_event("submit_answer", args, {"ok": True})
                    transcript.append({"turn": turn, "role": "submit", "args": args})
                    break
                if tools.calls >= MAX_CALLS:
                    result = {"error": {"code": "call_budget",
                                        "message": f"tool budget of {MAX_CALLS} calls is exhausted"}}
                else:
                    try:
                        result = tools.call(name, args)
                    except ToolError as exc:
                        result = {"error": {"code": exc.code, "message": str(exc)}}
                payloads.append(result)
                if name == "calculator" and not result.get("error"):
                    calc_values.append(result)
                transcript.append({"turn": turn, "role": "tool", "tool": name,
                                   "args": args, "result": result})
                messages.append({"role": "tool", "tool_call_id": tc.get("id") or "",
                                 "name": name, "content": _summary(result)})
            if submitted:
                break
            if tools.calls >= MAX_CALLS:
                messages.append({"role": "user", "content":
                                 f"The {MAX_CALLS}-call budget is exhausted. Call submit_answer "
                                 "now with the results above."})
        else:
            status = "turn_limit"
    except beam.BeamError as exc:
        status = "beam_error"
        error = f"{type(exc).__name__}: {exc}"
        if "402" in str(exc) or "quota" in str(exc).lower() or "billing" in str(exc).lower():
            status = "free_tier_blocked"

    num = check_answer(final.get("answer", ""), payloads, calc_values, q["question"])
    pit = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for row in payload.get("rows") or []:
            known = str(row.get("known_at") or "")[:10]
            if known and known > q["as_of"]:
                pit.append({"known_at": known, "row": row})
    row = {
        "qid": q["qid"], "mid": q["mid"], "parent_mid": q["parent_mid"],
        "symbol": q.get("symbol"), "entity_isin": q["entity_isin"],
        "question": q["question"], "as_of": q["as_of"], "period": q.get("period"),
        "category": q.get("category"), "source_bank": q.get("source_bank"),
        "status": status, "error": error,
        "answer": final.get("answer", ""), "working": final.get("working", ""),
        "missing": final.get("missing", ""),
        "not_in_data": bool(final.get("missing") and "not in data" in final["missing"].lower()),
        "n_tool_calls": tools.calls, "tool_trace": [
            {"call": i + 1, "tool": t["tool"], "args": t["args"],
             "ok": not bool((t["result"] or {}).get("error"))}
            for i, t in enumerate(transcript) if t["role"] == "tool"],
        "n_beam_calls": beam_calls, "usage": usage,
        "beam_secs": round(time.time() - t0, 2), "total_secs": round(time.time() - t0, 2),
        "number_check": num, "pit_breach": pit,
        "calc_calls": [c for c in calc_values],
        "transcript": transcript,
    }
    tools.close()
    if transcript_path:
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
    return row
