"""gemini-worker: Gemini (Google AI Studio API) as an MCP tool; thinking level default "low" for gemini-3/4 (minimal is refused by 3.8) over Shivam's AI Studio key pool (26 Nov 2026).

Keys: user env GEMINI_API_KEY, GEMINI_API_KEY_2 .. GEMINI_API_KEY_N (read via resource_watchdog.user_env; never
printed - replies name a key only by its number). Every key is paced per model under the free-tier limits in LIMITS
(requests/min, requests/day); a 429 rests that key+model (the rest of the minute, or the rest of the day for a daily
quota) and the call moves to the next key. Usage is logged to C:/RealityEngine/gemini_worker/usage.jsonl (no prompt
text, no key).

Usage:
  python plugins/gemini-worker/gemini_worker.py --ask "text" [--model gemini-3.8-flash]
  python plugins/gemini-worker/gemini_worker.py --mcp       # stdio MCP server: tools gemini_ask, gemini_models, gemini_status
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path("C:/RealityEngine/gemini_worker")
USAGE = ROOT / "usage.jsonl"
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemma-4-31b-it"  # 26 Nov (Shivam): Hydrogen/Argon only 10 req/key/day; Gemma 31B 14,000
# Free-tier pacing per key (rpm, rpd), kept just under the AI Studio limits; unknown models get the strictest pair.
LIMITS = {
    "gemini-3.8-flash": (4, 19), "gemini-3.7-flash": (4, 19), "gemini-3.6-flash": (4, 19), "gemini-3.5-flash": (4, 19),
    "gemini-3.5-flash-lite": (14, 480), "gemini-3.1-flash-lite": (14, 480), "gemini-2.5-flash": (9, 240),
    "gemini-2.5-flash-lite": (14, 980), "gemini-2.5-pro": (4, 95), "gemma-4-31b-it": (25, 14000),
    "gemma-4-26b-a4b-it": (25, 14000), "gemini-4-hydrogen": (2, 10), "gemini-4-argon": (2, 10),
}
STRICT = (2, 10)
_LOCK = threading.Lock()


def _keys() -> list[tuple[int, str]]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from reality_engine.scripts.resource_watchdog import user_env
    env = user_env()
    out = []
    if env.get("GEMINI_API_KEY"):
        out.append((1, env["GEMINI_API_KEY"]))
    for name, val in env.items():
        m = re.fullmatch(r"GEMINI_API_KEY_(\d+)", name)
        if m and val:
            out.append((int(m.group(1)), val))
    return sorted(out)


class Pool:
    """Per (key number, model): call times in the last minute, calls today, and a rest-until time after a 429."""

    def __init__(self) -> None:
        self.minute: dict[tuple[int, str], list[float]] = {}
        self.day: dict[tuple[int, str], int] = {}
        self.rest: dict[tuple[int, str], float] = {}
        self.today = datetime.now().strftime("%Y-%m-%d")
        self._load_today()

    def _load_today(self) -> None:
        if not USAGE.exists():
            return
        for line in USAGE.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if str(r.get("at", "")).startswith(self.today) and r.get("ok"):
                k = (int(r["key"]), r["model"])
                self.day[k] = self.day.get(k, 0) + 1

    def pick(self, nums: list[int], model: str) -> int | None:
        rpm, rpd = LIMITS.get(model, STRICT)
        now = time.time()
        if datetime.now().strftime("%Y-%m-%d") != self.today:
            self.today, self.day, self.rest = datetime.now().strftime("%Y-%m-%d"), {}, {}
        best = None
        for n in nums:
            k = (n, model)
            if self.rest.get(k, 0) > now or self.day.get(k, 0) >= rpd:
                continue
            recent = [t for t in self.minute.get(k, []) if now - t < 60]
            self.minute[k] = recent
            if len(recent) >= rpm:
                continue
            if best is None or self.day.get(k, 0) < self.day.get((best, model), 0):
                best = n
        return best

    def used(self, n: int, model: str) -> None:
        k = (n, model)
        self.minute.setdefault(k, []).append(time.time())
        self.day[k] = self.day.get(k, 0) + 1

    def throttled(self, n: int, model: str, daily: bool) -> None:
        now = time.time()
        if daily:
            end = datetime.now().replace(hour=23, minute=59, second=59).timestamp()
            self.rest[(n, model)] = end
        else:
            self.rest[(n, model)] = now + 65


POOL = Pool()


def _log(rec: dict) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    with USAGE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def ask(prompt: str, model: str = DEFAULT_MODEL, system: str | None = None, max_tokens: int = 8192,
        timeout: float = 180, max_keys: int = 40, thinking: str = "low") -> dict:
    import requests
    keys = _keys()
    if not keys:
        return {"ok": False, "error": "no GEMINI_API_KEY* set"}
    by_num = dict(keys)
    gen = {"maxOutputTokens": max_tokens}
    if model.startswith(("gemini-3", "gemini-4")):
        gen["thinkingConfig"] = {"thinkingLevel": thinking}
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    tried = []
    for _ in range(min(max_keys, len(keys))):
        with _LOCK:
            n = POOL.pick([k for k, _ in keys if k not in tried], model)
            if n is None:
                break
            POOL.used(n, model)
        tried.append(n)
        t0 = time.time()
        try:
            r = requests.post(API.format(model=model), params={"key": by_num[n]}, json=body, timeout=timeout)
        except Exception as exc:                                       # network: next key
            _log({"at": datetime.now().isoformat(timespec="seconds"), "key": n, "model": model, "ok": False,
                  "error": type(exc).__name__})
            continue
        sec = round(time.time() - t0, 1)
        if r.status_code == 503:                                       # model overloaded: try the next key soon
            _log({"at": datetime.now().isoformat(timespec="seconds"), "key": n, "model": model, "ok": False,
                  "error": "503 overloaded"})
            time.sleep(2)
            continue
        if r.status_code == 429:
            daily = "PerDay" in r.text or "per day" in r.text.lower()
            with _LOCK:
                POOL.throttled(n, model, daily)
            _log({"at": datetime.now().isoformat(timespec="seconds"), "key": n, "model": model, "ok": False,
                  "error": "429 daily" if daily else "429 minute"})
            continue
        if r.status_code != 200:
            msg = r.text[:300].replace(by_num[n], "***")
            _log({"at": datetime.now().isoformat(timespec="seconds"), "key": n, "model": model, "ok": False,
                  "error": f"HTTP {r.status_code}"})
            if r.status_code in (400, 404):                             # bad request / model: no point rotating
                return {"ok": False, "error": f"HTTP {r.status_code}: {msg}", "key": n}
            continue
        data = r.json()
        parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        um = data.get("usageMetadata", {})
        _log({"at": datetime.now().isoformat(timespec="seconds"), "key": n, "model": model, "ok": True,
              "seconds": sec, "in_tok": um.get("promptTokenCount"), "out_tok": um.get("candidatesTokenCount")})
        return {"ok": True, "answer": text, "model": model, "key": n, "seconds": sec,
                "tokens": {"in": um.get("promptTokenCount"), "out": um.get("candidatesTokenCount")}}
    return {"ok": False, "error": f"no key free for {model} right now (tried {len(tried)}; all paced or rested)",
            "tried": tried}


def status() -> dict:
    keys = [n for n, _ in _keys()]
    now = time.time()
    per_model: dict[str, dict] = {}
    for (n, model), c in POOL.day.items():
        d = per_model.setdefault(model, {"calls_today": 0, "rested_keys": 0})
        d["calls_today"] += c
    for (n, model), until in POOL.rest.items():
        if until > now:
            per_model.setdefault(model, {"calls_today": 0, "rested_keys": 0})["rested_keys"] += 1
    cap = {m: {"rpm_per_key": v[0], "rpd_per_key": v[1], "pool_rpd": v[1] * len(keys)} for m, v in LIMITS.items()}
    return {"keys": len(keys), "today": per_model, "limits": cap}


def serve() -> None:
    from mcp.server import MCPServer
    app = MCPServer(name="gemini-worker", version="0.1.0",
                    instructions="Gemini via Shivam's AI Studio key pool (free tier, paced per key). gemini_ask / gemini_status.")

    @app.tool()
    def gemini_ask(prompt: str, model: str = DEFAULT_MODEL, system: str | None = None, max_tokens: int = 8192,
                   thinking: str = "low") -> dict:
        """Ask a Gemini model through the AI Studio key pool (free tier, paced per key). Returns answer, key number,
        seconds and tokens; on 429 the next key is used; 'no key free' when every key is paced or rested."""
        return ask(prompt, model, system, max_tokens, thinking=thinking)

    @app.tool()
    def gemini_status() -> dict:
        """Keys in the pool, calls today per model, rested keys, and per-key/pool daily limits."""
        return status()

    app.run("stdio")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ask")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--mcp", action="store_true")
    a = ap.parse_args()
    if a.mcp:
        serve()
    elif a.ask:
        print(json.dumps(ask(a.ask, a.model), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(status(), indent=1))
