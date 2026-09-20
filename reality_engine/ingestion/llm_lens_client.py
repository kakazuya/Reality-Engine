"""Local LLM lens-extraction backend over a llama.cpp OpenAI-compatible server.

Design (per the llama.cpp server doc — ``llama serve`` exposes OpenAI
``/v1/chat/completions`` with ``response_format: {type: json_object}``):

- ``llama-server`` (Vulkan build for the RX 6700 XT, ``-ngl all``) runs as a
  supervised process (``hub op:start``, name ``llama-server``). This module
  NEVER spawns it — it only talks HTTP to ``LLM_BASE_URL``.
- ``LensLLMClient`` exposes the two seams the engine already calls:
  ``extract_macro(context, raw_doc) -> dict`` (MacroEventExtraction lens) and
  ``synthesize(symbol, chunk_texts) -> dict`` (moat-delta lens). Both return
  Pydantic-validated dicts; any miss (server down, bad JSON, schema fail)
  raises, and every caller already falls back to regex/mock heuristics.
- JSON discipline: system prompt pins the exact schema keys, temperature 0,
  and the response is parsed with a brace-matching scan (not ``json.loads``
  on raw output) so trailing prose never breaks the lens.

Model: Qwen2.5-3B-Instruct Q4_K_M (~1.9 GB, bartowski GGUF, fully offloaded
to 12 GB VRAM). Bigger models (Qwen3-4B, gemma-3-4b) are gated behind HF
access and add nothing for schema-pinned extraction.

Sources:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
  (``llama serve``: OpenAI-compatible ``/v1/chat/completions``,
  ``-ngl`` GPU layers, ``-c`` context, ``--jinja`` chat templates)
- reality_engine/processing/distillation_engine.py::distill_macro_document
  (``llm_client.extract_macro(context, raw_doc)`` contract)
- reality_engine/processing/distillation_pruner.py::synthesize_and_update
  (``llm_client.synthesize(symbol, chunk_texts)`` contract)

Env:
  LLM_BASE_URL   server root (default http://127.0.0.1:8080)
  LLM_MODEL      model alias for the chat route (default: default)
  LLM_TIMEOUT_S  HTTP timeout per call (default 180)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("reality_engine.llm_lens_client")

BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "default")
TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "900"))

MACRO_SYSTEM = """You extract macro-policy events into STRICT JSON. Output ONLY a JSON object with exactly these keys:
{"event_name": str, "event_category": str, "primary_effects": [{"target_type": "Sector|Industry|Company", "target_name": str, "transmission_channel": str, "raw_magnitude": float (-5..5), "probability": float (0..1), "lag_time_months": int, "second_order_effects": []}]}
Rules: 1-3 primary effects max. No prose, no markdown, no extra keys."""

MOAT_SYSTEM = """You distill company text into STRICT JSON. Output ONLY a JSON object with exactly these keys:
{"summary": {"business": str, "key_drivers": [str], "key_risks": [str]}, "moat_updates": {"switching_costs_delta": int (-2..2), "network_effects_delta": int (-2..2), "cost_advantage_delta": int (-2..2), "intangible_assets_delta": int (-2..2), "efficient_scale_delta": int (-2..2), "moat_trajectory": "Expanding|Stable|Deteriorating"}}
Rules: deltas are small integers vs the heuristic baseline. No prose, no markdown, no extra keys."""


def _scan_json(text: str) -> Optional[Dict[str, Any]]:
    """First balanced-brace JSON object in ``text``; None when absent."""
    start = text.find("{")
    if start < 0:
        return None
    depth, instr, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
        elif ch == '"':
            instr = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


class LensLLMClient:
    """HTTP client for the local llama-server lens backend.

    ``base_url``/``model``/``timeout`` default from env so tests can inject
    fakes without touching process env. No import-time I/O.
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        model: str = MODEL,
        timeout_s: float = TIMEOUT_S,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def health(self) -> bool:
        try:
            import requests  # type: ignore

            r = requests.get(self.base_url + "/health", timeout=10)
            return r.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Core chat call
    # ------------------------------------------------------------------
    def _chat(self, system: str, user: str, max_tokens: int = 2000) -> Dict[str, Any]:
        import requests  # type: ignore

        resp = requests.post(
            self.base_url + "/v1/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.0,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
                "stream": False,
                "reasoning_effort": "none",
                "reasoning_format": "none",
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        body = resp.json()
        text = body["choices"][0]["message"]["content"] or ""
        parsed = _scan_json(text)
        if parsed is None:
            raise ValueError(f"no JSON object in LLM output: {text[:200]!r}")
        return parsed

    # ------------------------------------------------------------------
    # Engine seams
    # ------------------------------------------------------------------
    def extract_macro(self, context: str, raw_doc: Dict[str, Any]) -> Dict[str, Any]:
        """MacroEventExtraction lens dict. Raises on any miss (caller falls back)."""
        from reality_engine.agent.schemas import MacroEventExtraction

        title = (raw_doc or {}).get("title", "")
        parsed = self._chat(
            MACRO_SYSTEM,
            f"Document: {title}\n\n{(context or '')[:6000]}",
        )
        return MacroEventExtraction.model_validate(parsed).model_dump()

    def synthesize(self, symbol: str, chunk_texts: List[str]) -> Dict[str, Any]:
        """Moat-delta lens dict. Raises on any miss (caller falls back)."""
        joined = "\n---\n".join((chunk_texts or [])[:6])[:6000]
        parsed = self._chat(MOAT_SYSTEM, f"Company: {symbol}\n\n{joined}")
        summary = parsed.get("summary", {})
        moat = parsed.get("moat_updates", {})
        for k in (
            "switching_costs_delta", "network_effects_delta", "cost_advantage_delta",
            "intangible_assets_delta", "efficient_scale_delta",
        ):
            moat.setdefault(k, 0)
        moat.setdefault("moat_trajectory", "Stable")
        return {"summary": summary, "moat_updates": moat}


# Shared singleton (server process is supervised separately via hub).
lens_llm_client = LensLLMClient()


def llm_health() -> bool:
    return lens_llm_client.health()
