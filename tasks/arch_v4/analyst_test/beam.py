"""beam-free chat client for the analyst-agent loop.

Same endpoint, model, retry rules, stable session id and usage ledger as
``tasks/arch_v4/reader_test/beam_client.py``; this module only adds a multi-turn
``messages`` call.  The key is read from the environment/registry and never logged.
"""
from __future__ import annotations

import json
import re
import time

import requests

from reality_engine.scripts.go_session import session_id
from reality_engine.toolbelt.cost_ledger import record_usage
from tasks.arch_v4.reader_test.beam_client import BeamError, RateLimited, api_key, _registry_env  # noqa: F401

URL = "https://opencode.ai/zen/go/v1/chat/completions"
MODEL = "beam-free"
JOB = "v4_analyst_agent"
REASONING_EFFORT = "low"
MAX_TOKENS = 3000
TIMEOUT = 240


def call_messages(messages: list[dict], *, key: str | None = None,
                  tools: list[dict] | None = None) -> dict:
    key = key or api_key()
    body = {"model": MODEL, "max_tokens": MAX_TOKENS, "reasoning_effort": REASONING_EFFORT,
            "messages": messages}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
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
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            reasoning = msg.get("reasoning_content") or ""
            return {"content": msg.get("content") or "",
                    "tool_calls": msg.get("tool_calls") or [],
                    "reasoning": reasoning,
                    "reasoning_chars": len(reasoning),
                    "usage": usage, "secs": round(time.time() - t0, 2)}
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


def parse_action(content: str) -> dict:
    """The model must return one JSON object; tolerate fenced prose around it."""
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.I | re.M).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise BeamError(f"no JSON object in model output: {text[:200]!r}")
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise BeamError(f"bad JSON: {text[:300]!r}") from exc
    if not isinstance(obj, dict):
        raise BeamError("model JSON root is not an object")
    return obj
