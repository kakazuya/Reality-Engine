"""Shared headless Claude session runner for the T-045 doc loop and the T-048 gap loop.

One fresh ``claude -p`` process per unit, ``--output-format stream-json`` parsed as it runs, killed
when its context (input + cache read + cache creation tokens of any assistant event) reaches
``CONTEXT_LIMIT``.  The caller owns what the session is allowed to do and what its final answer
must look like; this module owns process, context accounting, usage, tool calls and the kill.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

CLAUDE = r"C:\Users\warri\.local\bin\claude.exe"
CONFIG_DIR = r"C:\Users\warri\.claude-neo"
MODEL = "claude-haiku-5-5"
EFFORT = "medium"
CONTEXT_LIMIT = 95_000  # Shivam's limit is 100k; the process is killed before it.
RUN_SECONDS = 30 * 60
MAX_TURNS = 60
LIMIT_SLEEP = 15 * 60
LIMIT_WORDS = ("usage limit", "rate limit", "limit reached", "hit your limit", "429", "overloaded")
USAGE_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")
SKIP_ENV = ("CLAUDE_CODE", "CLAUDE_PID", "CLAUDE_EFFORT")
# Haiku 5.5 list price, USD per million tokens: tasks/kilo_model_pricing_2026-10-12.csv row
# "anthropic/claude-haiku-5.5" (in 0.1, out 0.5).  Cache read is billed at 0.1x the input price and
# cache creation at 1.25x, the Anthropic published multipliers.  Used only when a session is killed
# before its ``result`` event carries the CLI's own ``total_cost_usd``.
HAIKU_IN_USD_PER_MTOK = 0.1
HAIKU_OUT_USD_PER_MTOK = 0.5
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25


def child_env(extra: dict | None = None) -> dict:
    """The session environment: the caller's, minus Claude's own control variables."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(SKIP_ENV) and k != "CLAUDECODE"}
    env.update(CLAUDE_CONFIG_DIR=CONFIG_DIR, PYTHONUTF8="1")
    env.update(extra or {})
    return env


def hidden_console() -> dict:
    """Popen arguments for a session nobody sees (Shivam, 2 Nov: no console pop-ups on this laptop).

    ``CREATE_NO_WINDOW`` leaves the session with no console at all, so every Bash or Python tool
    call it makes opens a new, visible window.  A new console that starts hidden is inherited by
    those children instead, so they stay out of sight too."""
    if os.name != "nt":
        return {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0  # SW_HIDE
    return {"creationflags": subprocess.CREATE_NEW_CONSOLE, "startupinfo": info}


def context_of(usage: dict) -> int:
    return sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))


def build_cmd(
    prompt: str,
    *,
    model: str = MODEL,
    effort: str = EFFORT,
    allowed_tools: tuple[str, ...] | list[str] = (),
    disallowed_tools: tuple[str, ...] | list[str] = (),
    mcp_config: str | None = None,
    max_turns: int = MAX_TURNS,
) -> list[str]:
    """The ``claude -p`` command line.  ``mcp_config`` is a JSON string or a config path."""
    cmd = [
        CLAUDE, "-p", prompt, "--model", model, "--effort", effort,
        "--output-format", "stream-json", "--verbose", "--max-turns", str(max_turns),
        "--allowedTools", ",".join(allowed_tools),
        "--disallowedTools", ",".join(disallowed_tools),
        "--no-session-persistence",
    ]
    if mcp_config is not None:
        cmd += ["--strict-mcp-config", "--mcp-config", mcp_config]
    return cmd


def parse_json_block(text: str) -> object | None:
    """The last fenced ```json block, parsed; None when there is none or it is invalid."""
    blocks = re.findall(r"```json\s*(.*?)```", text or "", re.S)
    if not blocks:
        return None
    try:
        return json.loads(blocks[-1])
    except ValueError:
        return None


def _pages(arg: object) -> int | None:
    """Page count from a Read tool's ``pages`` argument ('1-5', '3'); None when absent."""
    text = str(arg or "").strip()
    span = re.fullmatch(r"(\d+)\s*-\s*(\d+)", text)
    if span:
        return max(0, int(span.group(2)) - int(span.group(1)) + 1)
    return 1 if text.isdigit() else None


# Same CSV, row "anthropic/claude-sonnet-5.5" (in 2.0, out 10.0): the gap loop's tier 2 (Shivam, 2 Nov).
PRICES_USD_PER_MTOK = {
    "claude-haiku-5-5": (HAIKU_IN_USD_PER_MTOK, HAIKU_OUT_USD_PER_MTOK),
    "claude-sonnet-5-5": (2.0, 10.0),
}


def estimate_cost(usage: dict, model: str = MODEL) -> float:
    """USD at the model's list price for a session killed before its ``result`` event."""
    price_in, price_out = PRICES_USD_PER_MTOK.get(model, PRICES_USD_PER_MTOK[MODEL])
    price = (
        int(usage.get("input_tokens") or 0) * price_in
        + int(usage.get("cache_read_input_tokens") or 0) * price_in * CACHE_READ_MULTIPLIER
        + int(usage.get("cache_creation_input_tokens") or 0) * price_in * CACHE_WRITE_MULTIPLIER
        + int(usage.get("output_tokens") or 0) * price_out
    )
    return price / 1e6


@dataclass
class SessionResult:
    """What one killed-or-finished session did, as the ledger needs it."""

    peak: int = 0
    cost: float = 0.0
    cost_estimated: bool = False
    final: str = ""
    tail: str = ""
    over_limit: bool = False
    limited: bool = False
    error: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: dict[str, int] = field(default_factory=dict)
    bash_commands: list[str] = field(default_factory=list)
    reads: int = 0
    pages_read: int = 0
    pages_unknown: int = 0
    model: str = MODEL
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.over_limit and not self.error


def _add_usage(total: dict[str, int], usage: dict) -> None:
    for key in USAGE_KEYS:
        total[key] = total.get(key, 0) + int(usage.get(key) or 0)
    for key in ("thinking_tokens", "output_tokens_details"):
        value = usage.get(key)
        if isinstance(value, dict):
            for sub, amount in value.items():
                if "think" in str(sub).lower():
                    total["thinking_tokens"] = total.get("thinking_tokens", 0) + int(amount or 0)
        elif isinstance(value, (int, float)):
            total[key] = total.get(key, 0) + int(value)


def run_session(
    cmd: list[str],
    cwd: Path,
    *,
    logfile: Path | None = None,
    run_seconds: int = RUN_SECONDS,
    context_limit: int = CONTEXT_LIMIT,
    model: str = MODEL,
    env: dict | None = None,
) -> SessionResult:
    """Run one command, parse its stream, kill it at the context limit or after ``run_seconds``."""
    started = time.time()
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), env=env or child_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **hidden_console(),
    )
    timed_out: list[bool] = [False]

    def stop() -> None:
        timed_out[0] = True
        proc.kill()

    timer = threading.Timer(run_seconds, stop)
    timer.start()
    result = SessionResult(model=model)
    saw_result = False
    try:
        for raw in proc.stdout:  # type: ignore[union-attr]
            result.tail = raw[:400]
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            kind = event.get("type")
            if kind == "assistant":
                message = event.get("message") or {}
                usage = message.get("usage") or {}
                result.peak = max(result.peak, context_of(usage))
                _add_usage(result.usage, usage)
                for block in message.get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    name = str(block.get("name") or "?")
                    result.tool_calls[name] = result.tool_calls.get(name, 0) + 1
                    args = block.get("input") or {}
                    if name == "Bash":
                        result.bash_commands.append(str(args.get("command") or "")[:200])
                    elif name == "Read":
                        result.reads += 1
                        if str(args.get("file_path") or "").lower().endswith(".pdf"):
                            count = _pages(args.get("pages"))
                            if count is None:
                                result.pages_unknown += 1
                            else:
                                result.pages_read += count
                if result.peak >= context_limit:
                    result.over_limit = True
                    proc.kill()
                    break
            elif kind == "result":
                saw_result = True
                result.cost = float(event.get("total_cost_usd") or 0)
                result.final = str(event.get("result") or "")
                if event.get("is_error"):
                    result.error = result.final[:300] or "session reported an error"
    finally:
        timer.cancel()
        proc.wait()
        result.duration_s = time.time() - started
    if not saw_result and (result.usage or result.over_limit):
        # Killed before the CLI's result event: price the tokens it did spend, and say so.
        result.cost = round(estimate_cost(result.usage, result.model), 6)
        result.cost_estimated = True
    if timed_out[0] and not result.over_limit:
        result.error = result.error or f"session ran longer than {run_seconds}s"
    joined = (result.final + result.tail).lower()
    result.limited = any(word in joined for word in LIMIT_WORDS)
    if logfile is not None:
        line = (f"{time.strftime('%Y-%m-%d %H:%M:%S')} session model={model} peak={result.peak:,} "
                f"cost=${result.cost:.3f} over_limit={result.over_limit} error={result.error[:120]}")
        with Path(logfile).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return result
