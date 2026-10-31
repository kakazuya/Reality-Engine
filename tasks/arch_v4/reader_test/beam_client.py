"""Free Beam reader call (OpenCode Go), with the usage ledger and a stable session id.

Free model, so there is no paid budget; every 200 response still goes through
``cost_ledger.record_usage`` as the brief requires.  Keys are read from the process
environment first and then from the registry (so a key set after the shell started is
still found); they are never printed or logged.
"""
from __future__ import annotations

import json
import os
import re
import time

import requests

from reality_engine.scripts.go_session import session_id
from reality_engine.toolbelt.cost_ledger import record_usage

URL = "https://opencode.ai/zen/go/v1/chat/completions"
MODEL = "beam-free"
JOB = "v4_reader_test"
REASONING_EFFORT = "low"
MAX_TOKENS = 3000
TIMEOUT = 240

SYSTEM = """You answer questions about Indian listed companies using ONLY the excerpts supplied.

Rules:
- Use only the excerpts. Never use outside knowledge.
- If the excerpts do not state the answer, answer exactly "not stated" and leave the quote empty.
- Reply with JSON only, no prose and no markdown:
  {"answer": "<one to three sentences>", "quote": "<verbatim words from one excerpt>", "chunk_id": <id>, "missing": "<what is not stated, or empty>"}
- The quote must be copied word for word from one excerpt, 10 to 45 consecutive words.
- Every number in the answer must appear in the quote. Do not calculate, convert, infer or
  combine numbers. Do not use a number that is not printed in the quote.
- If the question has several parts, answer the part the excerpts state and put the rest in
  "missing". A partial answer is better than a guess.
- The company asked about is fixed; ignore excerpts about any other company."""


class BeamError(RuntimeError):
    pass


class RateLimited(BeamError):
    pass


def _registry_env() -> dict[str, str]:
    env = dict(os.environ)
    try:
        import winreg

        for hive, sub in ((winreg.HKEY_CURRENT_USER, "Environment"),
                          (winreg.HKEY_LOCAL_MACHINE,
                           r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(hive, sub) as k:
                    i = 0
                    while True:
                        try:
                            name, val, _ = winreg.EnumValue(k, i)
                        except OSError:
                            break
                        i += 1
                        env.setdefault(name, val)
            except OSError:
                pass
    except ImportError:
        pass
    return env


def api_key() -> str:
    env = _registry_env()
    for name in ("OPENCODE_GO_API_KEY_2", "OPENCODE_GO_API_KEY"):
        val = (env.get(name) or "").strip()
        if val:
            return val
    raise BeamError("no OPENCODE_GO_API_KEY_2 / OPENCODE_GO_API_KEY in environment or registry")


def _window(body: str, terms: list[str], width: int = 1800) -> str:
    """For a long chunk, show the densest query-term window rather than its first 1,500 chars.

    The pilot chunks run to ~5,000 chars; the answering sentence is often deep inside one.
    """
    text = re.sub(r"\s+", " ", body or "").strip()
    if len(text) <= width:
        return text
    low = text.lower()
    positions: list[int] = []
    for term in terms[:14]:
        t = str(term).lower()
        if len(t) < 3:
            continue
        start = 0
        for _ in range(12):
            i = low.find(t, start)
            if i < 0:
                break
            positions.append(i)
            start = i + 1
    if not positions:
        return text[:width] + " …"
    best_lo, best_score = 0, -1
    for pos in positions:
        lo = max(0, min(pos - width // 3, len(text) - width))
        window = low[lo:lo + width]
        score = sum(1 for t in terms[:14] if len(str(t)) >= 3 and str(t).lower() in window)
        if score > best_score:
            best_lo, best_score = lo, score
    out = text[best_lo:best_lo + width]
    return ("… " if best_lo else "") + out + (" …" if best_lo + width < len(text) else "")


def excerpts(chunks: list[dict], terms: list[str] | None = None, width: int = 1800) -> str:
    parts = []
    for c in chunks:
        body = _window(c.get("body") or "", terms or [], width)
        head = c.get("header") or ""
        parts.append(f"[chunk {c['chunk_id']}] {c.get('doc_type')} known_at={c.get('known_at')} "
                     f"page={c.get('page_from')} section={c.get('section') or '-'}\n{head}\n{body}")
    return "\n\n".join(parts)


def user_prompt(q: dict, chunks: list[dict], terms: list[str] | None = None) -> str:
    return (f"QUESTION: {q['question']}\n"
            f"COMPANY: {q.get('name') or q.get('symbol')} ({q.get('symbol')})\n"
            f"AS OF: {q.get('as_of')}\n\n"
            f"EXCERPTS:\n{excerpts(chunks, terms)}")


def _parse(content: str) -> dict:
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.I).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise BeamError(f"no JSON in answer: {text[:160]!r}")
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise BeamError(f"bad JSON: {text[:200]!r}") from exc
    if not isinstance(obj, dict):
        raise BeamError("JSON root is not an object")
    return {
        "answer": str(obj.get("answer") or "").strip(),
        "quote": str(obj.get("quote") or "").strip(),
        "chunk_id": obj.get("chunk_id"),
        "missing": str(obj.get("missing") or "").strip(),
    }


def call(q: dict, chunks: list[dict], *, key: str | None = None,
         terms: list[str] | None = None) -> dict:
    key = key or api_key()
    body = {"model": MODEL, "max_tokens": MAX_TOKENS, "reasoning_effort": REASONING_EFFORT,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": user_prompt(q, chunks, terms)}]}
    last = ""
    for attempt in range(5):
        t0 = time.time()
        try:
            r = requests.post(
                URL, timeout=TIMEOUT,
                headers={"Authorization": f"Bearer {key}",
                         "x-opencode-session": session_id(JOB, MODEL, key, lane_no=0)},
                json=body)
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"[:200]
            time.sleep(4 * (attempt + 1))
            continue
        text = r.text or ""
        if r.status_code == 200:
            data = r.json()
            usage = data.get("usage") or {}
            record_usage(MODEL, usage, JOB)
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            out = _parse(content)
            out.update({"model": MODEL, "usage": usage, "secs": round(time.time() - t0, 2),
                        "reasoning": ((data.get("choices") or [{}])[0].get("message") or {}).get("reasoning_content") or ""})
            out["reasoning_chars"] = len(out.pop("reasoning"))
            return out
        if r.status_code == 429:
            last = "HTTP 429 rate limited"
            time.sleep(12 * (attempt + 1))
            continue
        if r.status_code == 402 or re.search(r"billing|quota|insufficient|credit", text, re.I):
            raise BeamError(f"HTTP {r.status_code}: {text[:180]}")
        last = f"HTTP {r.status_code}: {text[:180]}"
        if r.status_code >= 500:
            time.sleep(4 * (attempt + 1))
            continue
        break
    raise BeamError(f"{MODEL} failed: {last}")
